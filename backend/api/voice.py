# app/api/voice.py
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from pydantic import AliasChoices
from pydantic.config import ConfigDict
from typing import Literal, Optional
from uuid import UUID
import io
import logging

import asyncpg
from asyncpg import exceptions as pg_exc
from google.cloud import texttospeech
# voice_speed_converter 불필요 - 간단한 로컬 함수 사용

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/users", tags=["voice"])

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    # Accept both 'uuid' and 'user_id' from clients using validation_alias
    user_id: UUID = Field(validation_alias=AliasChoices('uuid', 'user_id'), description="User ID")
    text: str
    gender: Literal["female", "male"] = "female"
    # 요구사항: speed (배속, 0.25~4.0)
    speed: float = Field(1.0, ge=0.25, le=4.0)
    # 옵션
    pitch: float = Field(0.0, ge=-20.0, le=20.0)
    language_code: str = "ko-KR"
    audio_encoding: Literal["MP3", "OGG_OPUS"] = "MP3"

    model_config = ConfigDict(populate_by_name=True)

class VoiceSettings(BaseModel):
    user_id: UUID
    gender: Literal["female", "male"]
    speed: float  # 배속(예: 1.0, 0.9, 1.2)
    language_code: str = "ko-KR"

class UpdateVoiceRequest(BaseModel):
    gender: Optional[Literal["female", "male"]] = None
    speed: Optional[float] = Field(None, ge=0.25, le=4.0)
    context: Optional[str] = Field("reset", description="설정 컨텍스트: onboarding, reset")

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _media_type(enc: str) -> str:
    return "audio/mpeg" if enc == "MP3" else "audio/ogg"

# 공개 함수로 변경하여 다른 파일에서도 사용 가능
def speed_float_to_int_percent(v: float) -> int:
    """1.0배속 -> 100 (DB speed는 INTEGER %로 저장)"""
    return int(round(v * 100))

def int_percent_to_speed_float(v: Optional[int]) -> float:
    """DB의 speed(INT, %) -> 배속 float (NULL이면 100%로 간주)"""
    return (v if v is not None else 100) / 100.0

# 하위 호환성을 위한 내부 함수들
def _speed_float_to_int_percent(v: float) -> int:
    return speed_float_to_int_percent(v)

def _int_percent_to_speed_float(v: Optional[int]) -> float:
    return int_percent_to_speed_float(v)

# ─────────────────────────────────────────────────────────────
# POST /api/users/voice : 선호 저장(업서트) + 합성  (Swagger에서 오디오로 표시)
# ─────────────────────────────────────────────────────────────
@router.post(
    "/voice",
    responses={
        200: {
            "description": "Audio stream",
            "content": {
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
                "audio/ogg":  {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def synthesize_and_save(req: TTSRequest, request: Request):
    # validation_alias로 처리된 user_id 사용
    user_id = req.user_id
    
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")

    # 0) 사용자 존재 검증 및 자동 생성 (Get or Create)
    async with pool.acquire() as conn:
        user_exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE user_id = $1",
            user_id
        )
        if not user_exists:
            # 사용자가 없으면 새로 생성
            try:
                await conn.execute(
                    "INSERT INTO users (user_id, user_name) VALUES ($1, $2)",
                    user_id,
                    "새 사용자"  # 기본 사용자 이름
                )
                logger.info(f"신규 사용자 자동 생성: {user_id}")
            except pg_exc.UniqueViolationError:
                # 매우 드문 경우: 동시성 문제로 다른 요청이 방금 사용자를 생성함
                logger.warning(f"신규 사용자 생성 중 UniqueViolationError 발생 (무시): {user_id}")
                pass # 그냥 계속 진행
            except Exception as e:
                logger.exception(f"사용자 자동 생성 중 DB 오류 발생: {e}")
                raise HTTPException(status_code=500, detail="사용자 자동 생성 실패")

    # 1) 텍스트 길이 검증
    if not req.text or len(req.text.strip()) == 0:
        raise HTTPException(status_code=400, detail="텍스트가 비어있습니다")
    
    if len(req.text) > 5000:  # Google TTS 제한
        raise HTTPException(status_code=400, detail="텍스트가 너무 깁니다 (최대 5000자)")
    
    # 2) 속도 값 유효성 검증 (Google TTS 범위: 0.25-4.0)
    if not (0.25 <= req.speed <= 4.0):
        raise HTTPException(status_code=400, detail=f"Invalid speed value: {req.speed}")
    normalized_speed = req.speed
    
    logger.info(f"TTS 요청 - 사용자: {user_id}, 텍스트 길이: {len(req.text)}, 속도: {normalized_speed}, 성별: {req.gender}")
    
    # 2) 선호 저장(UPSERT)
    gender_char = "F" if req.gender == "female" else "M"
    speed_int = _speed_float_to_int_percent(normalized_speed)

    try:
        async with pool.acquire() as conn:
            # voice 테이블 업데이트
            voice_result = await conn.fetchrow(
                """
                INSERT INTO voice (user_id, gender, speed)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET
                    gender = EXCLUDED.gender,
                    speed  = EXCLUDED.speed,
                    voice_updated_at = NOW()
                RETURNING voice_id;
                """,
                user_id,  # asyncpg는 UUID 객체를 그대로 처리 가능
                gender_char,
                speed_int,
            )
            voice_id = voice_result['voice_id']
            
            # user_settings 테이블도 자동 업데이트
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, voice_id)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET
                    voice_id = EXCLUDED.voice_id,
                    setting_updated_at = NOW();
                """,
                user_id,
                voice_id
            )
    except pg_exc.ForeignKeyViolationError:
        raise HTTPException(status_code=400, detail="Foreign key violation: user_id not found in users")
    except pg_exc.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Duplicate user_id")
    except Exception as e:
        logger.exception("DB error during voice upsert")
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    # 2) Google TTS 합성 (API 키 방식)
    try:
        import os
        from google.oauth2 import service_account
        from google.cloud import texttospeech
        
        # API 키 방식으로 인증
        api_key = os.getenv("GOOGLE_TTS_API_KEY")
        if not api_key:
            logger.error("GOOGLE_TTS_API_KEY 환경변수가 설정되지 않았습니다.")
            # 사용 가능한 환경변수 목록 출력 (디버깅용)
            available_vars = [k for k in os.environ.keys() if 'GOOGLE' in k or 'TTS' in k]
            logger.debug(f"사용 가능한 Google/TTS 환경변수: {available_vars}")
            raise ValueError("GOOGLE_TTS_API_KEY 환경변수가 설정되지 않았습니다.")
        
        logger.info(f"Google TTS API 키 확인됨 (길이: {len(api_key)} 문자)")
        
        # API 키를 사용한 클라이언트 생성
        try:
            client = texttospeech.TextToSpeechClient(
                client_options={"api_key": api_key}
            )
            logger.info("Google TTS 클라이언트 초기화 성공")
        except Exception as client_error:
            logger.error(f"Google TTS 클라이언트 초기화 실패: {client_error}")
            raise ValueError(f"TTS 클라이언트 초기화 실패: {client_error}")
        
        synthesis_input = texttospeech.SynthesisInput(text=req.text)

        gender_enum = (
            texttospeech.SsmlVoiceGender.FEMALE
            if req.gender == "female"
            else texttospeech.SsmlVoiceGender.MALE
        )

        voice = texttospeech.VoiceSelectionParams(
            language_code=req.language_code,
            ssml_gender=gender_enum,  # 보이스 이름 고정 없이 성별만 지정
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=getattr(texttospeech.AudioEncoding, req.audio_encoding),
            speaking_rate=normalized_speed,   # 정규화된 속도 사용
            pitch=req.pitch,
        )

        resp = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # 오디오 콘텐츠 검증
        if not resp.audio_content:
            raise ValueError("TTS 응답에 오디오 콘텐츠가 없습니다")
        
        logger.info(f"TTS 생성 성공 - 텍스트: '{req.text[:50]}...', 오디오 크기: {len(resp.audio_content)} bytes")
    except Exception as e:
        logger.exception(f"Google TTS synthesize error - Speed: {normalized_speed}, Pitch: {req.pitch}, Gender: {req.gender}")
        raise HTTPException(status_code=502, detail=f"TTS error: {e}")

    content = resp.audio_content
    fname = "speech.mp3" if req.audio_encoding == "MP3" else "speech.ogg"

    # 오디오 재생을 위한 헤더 설정
    headers = {
        "Content-Disposition": f'inline; filename="{fname}"',
        "Content-Length": str(len(content)),
        "Accept-Ranges": "bytes",  # 브라우저 오디오 재생 지원
        "Cache-Control": "no-cache",  # 캐시 방지
        "Access-Control-Allow-Origin": "*",  # CORS 허용
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }

    logger.info(f"TTS 응답 전송 - 파일명: {fname}, 크기: {len(content)} bytes, 미디어 타입: {_media_type(req.audio_encoding)}")

    return StreamingResponse(
        io.BytesIO(content),
        media_type=_media_type(req.audio_encoding),
        headers=headers,
    )

# ─────────────────────────────────────────────────────────────
# GET /api/users/voice?user_id=... : 저장값 조회(쿼리)
# ─────────────────────────────────────────────────────────────
@router.get("/voice", response_model=VoiceSettings)
async def get_voice_by_query(request: Request, user_id: UUID = Query(...)):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT gender, speed FROM voice WHERE user_id = $1",
            user_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="voice settings not found for user_id")

    gender = "female" if row["gender"] == "F" else "male"
    speed = _int_percent_to_speed_float(row["speed"])
    return VoiceSettings(user_id=user_id, gender=gender, speed=speed)

# ─────────────────────────────────────────────────────────────
# GET /api/users/{user_id}/voice : 저장값 조회(path)
# ─────────────────────────────────────────────────────────────
@router.get("/{user_id}/voice", response_model=VoiceSettings)
async def get_voice_by_path(user_id: UUID, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT gender, speed FROM voice WHERE user_id = $1",
            user_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="voice settings not found for user_id")

    gender = "female" if row["gender"] == "F" else "male"
    speed = _int_percent_to_speed_float(row["speed"])
    return VoiceSettings(user_id=user_id, gender=gender, speed=speed)

# ─────────────────────────────────────────────────────────────
# PATCH /api/users/{user_id}/voice : 설정만 수정(부분 업데이트, TTS 없음)
# ─────────────────────────────────────────────────────────────
@router.patch("/{user_id}/voice")
async def update_voice(user_id: UUID, req: UpdateVoiceRequest, request: Request):
    """
    설정만 수정(부분 업데이트). TTS 합성 없음.
    - gender 또는 speed 중 적어도 하나는 포함해야 함.
    - voice 행이 없어도 업서트로 생성됨(미지정 필드는 기본값: gender=F, speed=100%).
    """
    if req.gender is None and req.speed is None:
        raise HTTPException(status_code=400, detail="At least one of gender or speed must be provided")

    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")

    # users에 존재하는지 확인
    async with pool.acquire() as conn:
        user_exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
        if not user_exists:
            raise HTTPException(status_code=400, detail="Unknown user_id (users row not found)")

    gender_char = None if req.gender is None else ("F" if req.gender == "female" else "M")
    
    # 속도 값이 제공된 경우 유효성 검증 및 변환
    speed_int = None
    if req.speed is not None:
        if not (0.25 <= req.speed <= 4.0):
            raise HTTPException(status_code=400, detail=f"Invalid speed value: {req.speed}")
        speed_int = _speed_float_to_int_percent(req.speed)

    # 업서트 + 부분 업데이트 (NULL이면 기존값 유지)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO voice (user_id, gender, speed)
            VALUES ($1,
                    COALESCE($2, 'F'),          -- 새로 만들 때 기본: 여성
                    COALESCE($3, 100))          -- 새로 만들 때 기본: 100%
            ON CONFLICT (user_id) DO UPDATE SET
                gender = COALESCE(EXCLUDED.gender, voice.gender),
                speed  = COALESCE(EXCLUDED.speed,  voice.speed),
                voice_updated_at = NOW()
            RETURNING gender, speed;
            """,
            user_id, gender_char, speed_int
        )

    gender_out = "female" if row["gender"] == "F" else "male"
    speed_out = (row["speed"] or 100) / 100.0
    
    # 컨텍스트에 따른 음성 안내 메시지 생성 (CommandExecutor에서 가져오기)
    from services.singleton import service_manager
    command_executor = service_manager.get_command_executor()
    
    context = getattr(req, 'context', 'reset')
    if context == "onboarding":
        voice_message = command_executor.get_voice_message("voice_setting_complete_onboarding")
        next_step = "caregiver_setup"
    else:
        voice_message = command_executor.get_voice_message("voice_setting_complete_reset")
        next_step = "settings_return"
    
    # VoiceSettings에 음성 안내 정보 추가
    result = VoiceSettings(user_id=user_id, gender=gender_out, speed=speed_out)
    
    # 응답에 음성 안내 정보 추가하기 위해 딕셔너리로 변환
    response_dict = result.model_dump()
    response_dict.update({
        "voice_message": voice_message,
        "next_step": next_step,
        "context": context,
        "message": f"음성 설정이 성공적으로 {'완료' if context == 'onboarding' else '변경'}되었습니다."
    })
    
    return response_dict
