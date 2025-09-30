from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field, AliasChoices
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import logging
import os

from .users import get_session  # users.py의 세션 생성기 재사용

# ── Solapi SDK & utils (동기 SDK를 비동기에서 안전하게 호출)
from solapi import SolapiMessageService
from solapi.model import RequestMessage
from starlette.concurrency import run_in_threadpool
from config.settings import get_settings

# (개발환경 편의를 위해 .env 로드; 프로덕션은 런타임 시크릿 주입 권장)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logger = logging.getLogger("uvicorn.error")
settings = get_settings()

router = APIRouter(prefix="/api/users", tags=["caregiver"])

# ─────────────────────────────────────────────────────────────
# Solapi 설정
# ─────────────────────────────────────────────────────────────
SOLAPI_API_KEY = os.getenv("SOLAPI_API_KEY")
SOLAPI_API_SECRET = os.getenv("SOLAPI_API_SECRET")
SOLAPI_SENDER = os.getenv("SOLAPI_SENDER")  # 등록된 발신번호(하이픈 없이)

if not all([SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_SENDER]):
    logger.warning("SOLAPI 환경변수(SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_SENDER)가 설정되지 않았습니다.")

_solapi_service: Optional[SolapiMessageService] = None
def get_solapi_service() -> SolapiMessageService:
    global _solapi_service
    if _solapi_service is None:
        if not all([SOLAPI_API_KEY, SOLAPI_API_SECRET]):
            raise RuntimeError("Solapi API Key/Secret이 설정되지 않았습니다.")
        _solapi_service = SolapiMessageService(api_key=SOLAPI_API_KEY, api_secret=SOLAPI_API_SECRET)
    return _solapi_service

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class CaregiverCreate(BaseModel):
    user_id: UUID = Field(validation_alias=AliasChoices('uuid', 'user_id'))
    caregivers_name: str = Field(..., max_length=32)
    phone_number: str = Field(..., max_length=32)
    context: Optional[str] = Field("onboarding", description="설정 컨텍스트: onboarding, reset")

class CaregiverUpdate(BaseModel):
    caregivers_name: Optional[str] = Field(None, max_length=32)
    phone_number: Optional[str] = Field(None, max_length=32)
    context: Optional[str] = Field("reset", description="설정 컨텍스트: onboarding, reset")

class CaregiverResponse(BaseModel):
    caregiver_id: int
    user_id: UUID
    caregivers_name: str
    phone_number: str
    
class AlertRequest(BaseModel):
    user_id: UUID = Field(validation_alias=AliasChoices('uuid', 'user_id'))

class CaregiverAlertResponse(BaseModel):
    status: str
    message: str
    caregiver_phone: str
    current_location: str = Field(..., description="사용자의 현재 위치 주소")

# ─────────────────────────────────────────────────────────────
# POST /api/users/caregiver : 보호자 정보 등록
# ─────────────────────────────────────────────────────────────
@router.post("/caregiver")
async def create_caregiver(req: CaregiverCreate, session: AsyncSession = Depends(get_session)):
    user_id_str = str(req.user_id)
    try:
        query = text("""
                     INSERT INTO caregivers (user_id, caregivers_name, phone_number)
                     VALUES (:user_id, :name, :phone)
                     RETURNING caregiver_id, user_id, caregivers_name, phone_number
                     """)
        result = await session.execute(
            query,
            {"user_id": user_id_str, "name": req.caregivers_name, "phone": req.phone_number}
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create caregiver")
        
        caregiver_id = row.caregiver_id
        
        # user_settings 테이블도 자동 업데이트
        settings_query = text("""
            INSERT INTO user_settings (user_id, caregiver_id)
            VALUES (:user_id, :caregiver_id)
            ON CONFLICT (user_id) DO UPDATE SET
                caregiver_id = EXCLUDED.caregiver_id,
                setting_updated_at = NOW()
        """)
        await session.execute(settings_query, {
            "user_id": user_id_str,
            "caregiver_id": caregiver_id
        })
        
        await session.commit()

        # 컨텍스트에 따른 음성 안내 메시지 생성 (CommandExecutor에서 가져오기)
        from services.singleton import service_manager
        command_executor = service_manager.get_command_executor()
        
        context = getattr(req, 'context', 'onboarding')
        if context == "onboarding":
            voice_message = command_executor.get_voice_message("caregiver_create_onboarding")
            next_step = "onboarding_complete"
        else:
            voice_message = command_executor.get_voice_message("caregiver_create_reset")
            next_step = "settings_return"

        # 응답에 음성 안내 정보 추가
        caregiver_response = CaregiverResponse.model_validate(row, from_attributes=True)
        response_dict = caregiver_response.model_dump()
        response_dict.update({
            "voice_message": voice_message,
            "next_step": next_step,
            "context": context,
            "message": f"보호자 정보가 성공적으로 {'등록' if context == 'onboarding' else '업데이트'}되었습니다."
        })
        
        return response_dict

    except IntegrityError as e:
        await session.rollback()
        if "violates foreign key constraint" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id '{user_id_str}' not found")
        if "violates unique constraint" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Caregiver already exists for this user")
        if settings.DEBUG:
            logger.exception("DB integrity error during caregiver creation")
        else:
            logger.error("DB integrity error during caregiver creation")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database integrity error")
    except Exception as e:
        await session.rollback()
        if settings.DEBUG:
            logger.exception("DB error during caregiver creation")
        else:
            logger.error(f"DB error during caregiver creation: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")

# ─────────────────────────────────────────────────────────────
# PATCH /api/users/caregiver/{user_id} : 보호자 정보 수정
# ─────────────────────────────────────────────────────────────
@router.patch("/caregiver/{user_id}")
async def update_caregiver(user_id: UUID, req: CaregiverUpdate, session: AsyncSession = Depends(get_session)):
    if req.caregivers_name is None and req.phone_number is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field must be provided")

    user_id_str = str(user_id)
    try:
        update_fields = []
        params = {"user_id": user_id_str}
        if req.caregivers_name is not None:
            update_fields.append("caregivers_name = :name")
            params["name"] = req.caregivers_name
        if req.phone_number is not None:
            update_fields.append("phone_number = :phone")
            params["phone"] = req.phone_number

        update_clause = ", ".join(update_fields)
        query = text(f"""
            UPDATE caregivers
            SET {update_clause}, caregiver_updated_at = NOW()
            WHERE user_id = :user_id
            RETURNING caregiver_id, user_id, caregivers_name, phone_number
        """)

        result = await session.execute(query, params)
        row = result.fetchone()
        await session.commit()

        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver not found for the specified user")

        # 컨텍스트에 따른 음성 안내 메시지 생성 (CommandExecutor에서 가져오기)
        from services.singleton import service_manager
        command_executor = service_manager.get_command_executor()
        
        context = getattr(req, 'context', 'reset')
        if context == "onboarding":
            voice_message = command_executor.get_voice_message("caregiver_update_onboarding")
            next_step = "onboarding_complete"
        else:
            voice_message = command_executor.get_voice_message("caregiver_update_reset")
            next_step = "settings_return"

        # 응답에 음성 안내 정보 추가
        caregiver_response = CaregiverResponse.model_validate(row, from_attributes=True)
        response_dict = caregiver_response.model_dump()
        response_dict.update({
            "voice_message": voice_message,
            "next_step": next_step,
            "context": context,
            "message": f"보호자 정보가 성공적으로 {'완료' if context == 'onboarding' else '변경'}되었습니다."
        })
        
        return response_dict
    except Exception as e:
        await session.rollback()
        if settings.DEBUG:
            logger.exception("DB error during caregiver update")
        else:
            logger.error(f"DB error during caregiver update: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")

# ─────────────────────────────────────────────────────────────
# POST /api/users/caregiver/alert : 위험 감지시 보호자 호출 (Solapi 문자 발송)
# ─────────────────────────────────────────────────────────────
@router.post("/caregiver/alert", response_model=CaregiverAlertResponse)
async def send_caregiver_alert(req: AlertRequest, session: AsyncSession = Depends(get_session)):
    user_id_str = str(req.user_id)
    try:
        # 1) 보호자/사용자 조회
        query = text("""
            SELECT c.caregivers_name, c.phone_number, u.user_name
            FROM caregivers c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.user_id = :user_id
        """)
        result = await session.execute(query, {"user_id": user_id_str})
        caregiver = result.fetchone()

        if not caregiver:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver not found for this user")

        # 2) 자동 메시지 생성
        auto_message = f"[긴급] {caregiver.user_name}님에게 위급 상황이 발생했습니다. 확인이 필요합니다."

        # 3) 문자 발송 (Solapi) - 동기 SDK를 스레드풀에서 실행
        svc = get_solapi_service()
        msg = RequestMessage(
            from_=SOLAPI_SENDER,
            to=caregiver.phone_number,
            text=auto_message
        )
        solapi_resp = await run_in_threadpool(svc.send, msg)

        # 발송 성공/실패 간단 검증 (등록 성공 카운트 확인)
        reg_ok = getattr(getattr(solapi_resp, "group_info", None), "count", None)
        registered_success = getattr(reg_ok, "registered_success", 0) if reg_ok else 0
        if registered_success <= 0:
            # Solapi 응답을 그대로 노출하긴 과하니 요약 메시지로 반환
            raise HTTPException(status_code=502, detail="Failed to register SMS to Solapi")

        # 4) 대시보드 로그 적재
        log_query = text("""
            INSERT INTO dashboard_logs (user_id, log_type, log_data)
            VALUES (:user_id, 'EMERGENCY_ALERT', :log_data)
        """)
        await session.execute(log_query, {
            "user_id": user_id_str,
            "log_data": f"Emergency alert sent to {caregiver.caregivers_name} ({caregiver.phone_number}): {auto_message}"
        })
        await session.commit()

        # 5) 현재 위치(추후 실제 위치 연동) - 지금은 placeholder
        current_location = "위치 정보 확인 불가"

        return CaregiverAlertResponse(
            status="success",
            message=f"Alert SMS sent to {caregiver.caregivers_name}",
            caregiver_phone=caregiver.phone_number,
            current_location=current_location
        )

    except HTTPException:
        # 위에서 raise한 HTTPException은 그대로 전달
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        if settings.DEBUG:
            logger.exception("Error sending caregiver alert")
        else:
            logger.error(f"Error sending caregiver alert: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")
