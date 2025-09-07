from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, insert
from models.database_models import User, Voice, Caregiver, Footstep, UserSetting
from core.database import get_async_db as get_session
import logging
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# 요청 스키마
class UserRegister(BaseModel):
    app_uuid: UUID
    user_name: str | None = None

class UpdateName(BaseModel):
    app_uuid: UUID
    user_name: str

class OnboardingComplete(BaseModel):
    """온보딩 완료 데이터"""
    app_uuid: UUID
    user_name: str
    # 음성 설정
    voice_gender: str = "F"  # M/F
    voice_speed: int = 10    # 1-20 (10이 기본)
    # 보폭 설정
    step_length_cm: int
    # 보호자 정보
    caregiver_name: str = ""
    caregiver_phone: str = ""

class ImprovedMeasurement(BaseModel):
    """개선된 10m 표준거리 + 사용자 걸음수 측정 결과"""
    user_id: str
    step_length_cm: float
    step_count: int
    method: str = "10m_standard_distance_user_counted"
    confidence: float = 0.85
    measurement_distance_cm: float = 1000.0

# FastAPI 앱
router = APIRouter()

@router.get("/")
def root():
    return {"status": "ok"}

# 사용자 목록 조회
@router.get("/users")
async def get_users(session: AsyncSession = Depends(get_session)):
    """사용자 목록 조회"""
    try:
        result = await session.execute(text("SELECT app_uuid, user_name FROM users ORDER BY created_at DESC LIMIT 100"))
        users = [{"app_uuid": str(row[0]), "user_name": row[1]} for row in result.fetchall()]
        return {"users": users, "count": len(users)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 조회 실패: {str(e)}")

# 사용자 최초 등록(UUID 생성 및 이름 동시 갱신)
@router.post("/users/register")
async def register_user(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session)
):
    try:
        # 이미 존재하는지 확인
        result = await session.execute(
            text("SELECT user_id FROM users WHERE user_id = :uid"),
            {"uid": str(payload.app_uuid)}
        )
        exists = result.scalar_one_or_none()

        if exists:
            # 이름이 넘어왔으면 갱신
            if payload.user_name:
                await session.execute(
                    text("UPDATE users SET user_name = :uname WHERE user_id = :uid"),
                    {"uid": str(payload.app_uuid), "uname": payload.user_name}
                )
                await session.commit()
            return {
                "user_id": str(payload.app_uuid),
                "status": "already_exists",
                "user_name": payload.user_name
            }

        # 신규 삽입
        await session.execute(
            text("INSERT INTO users (user_id, user_name) VALUES (:uid, :uname)"),
            {"uid": str(payload.app_uuid), "uname": payload.user_name}
        )
        await session.commit()
        return {
            "user_id": str(payload.app_uuid),
            "status": "created",
            "user_name": payload.user_name
        }
    
    # 디버깅
    except Exception as e:
        if settings.DEBUG:
            logger.exception("register_user failed")
        else:
            logger.error(f"register_user failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# 이름 수정
@router.patch("/users/update_name")
async def update_name(
    payload: UpdateName,
    session: AsyncSession = Depends(get_session)
):
    try:
        result = await session.execute(
            text("UPDATE users SET user_name = :uname WHERE user_id = :uid RETURNING user_id"),
            {"uid": str(payload.app_uuid), "uname": payload.user_name}
        )
        updated = result.scalar_one_or_none()
        await session.commit()

        if not updated:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "user_id": str(payload.app_uuid),
            "status": "updated",
            "user_name": payload.user_name
        }

    except HTTPException:
        raise
    except Exception as e:
        if settings.DEBUG:
            logger.exception("update_name failed")
        else:
            logger.error(f"update_name failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 온보딩 완료 - 모든 사용자 정보를 한 번에 저장
@router.post("/users/onboarding/complete")
async def complete_onboarding(
    payload: OnboardingComplete,
    session: AsyncSession = Depends(get_session)
):
    """
    온보딩 과정에서 수집된 모든 사용자 정보를 DB에 저장
    - 사용자 기본 정보 (users 테이블)
    - 음성 설정 (voice 테이블)  
    - 보폭 정보 (footstep 테이블)
    - 보호자 정보 (caregivers 테이블) - 선택적
    - 통합 설정 (user_settings 테이블)
    """
    try:
        # 1. 사용자 기본 정보 저장/업데이트
        user_result = await session.execute(
            text("INSERT INTO users (user_id, user_name) VALUES (:uid, :uname) ON CONFLICT (user_id) DO UPDATE SET user_name = :uname RETURNING user_id"),
            {"uid": str(payload.app_uuid), "uname": payload.user_name}
        )
        
        # 2. 음성 설정 저장
        voice_result = await session.execute(
            text("""
                INSERT INTO voice (user_id, gender, speed) 
                VALUES (:uid, :gender, :speed) 
                ON CONFLICT (user_id) DO UPDATE SET 
                    gender = :gender, 
                    speed = :speed,
                    voice_updated_at = NOW()
                RETURNING voice_id
            """),
            {
                "uid": str(payload.app_uuid), 
                "gender": payload.voice_gender,
                "speed": payload.voice_speed
            }
        )
        voice_id = voice_result.scalar_one()
        
        # 3. 보폭 정보 저장
        footstep_result = await session.execute(
            text("""
                INSERT INTO footstep (user_id, step_length) 
                VALUES (:uid, :step_length) 
                ON CONFLICT (user_id) DO UPDATE SET 
                    step_length = :step_length,
                    step_updated_at = NOW()
                RETURNING step_id
            """),
            {
                "uid": str(payload.app_uuid),
                "step_length": payload.step_length_cm
            }
        )
        step_id = footstep_result.scalar_one()
        
        # 4. 보호자 정보 저장 (이름이 있을 경우만)
        caregiver_id = None
        if payload.caregiver_name.strip():
            caregiver_result = await session.execute(
                text("""
                    INSERT INTO caregivers (user_id, caregivers_name, phone_number) 
                    VALUES (:uid, :name, :phone) 
                    ON CONFLICT (user_id) DO UPDATE SET 
                        caregivers_name = :name,
                        phone_number = :phone,
                        caregiver_updated_at = NOW()
                    RETURNING caregiver_id
                """),
                {
                    "uid": str(payload.app_uuid),
                    "name": payload.caregiver_name,
                    "phone": payload.caregiver_phone
                }
            )
            caregiver_id = caregiver_result.scalar_one()
        
        # 5. 통합 설정 테이블 업데이트
        await session.execute(
            text("""
                INSERT INTO user_settings (user_id, voice_id, step_id, caregiver_id) 
                VALUES (:uid, :vid, :sid, :cid) 
                ON CONFLICT (user_id) DO UPDATE SET 
                    voice_id = :vid,
                    step_id = :sid,
                    caregiver_id = :cid,
                    setting_updated_at = NOW()
            """),
            {
                "uid": str(payload.app_uuid),
                "vid": voice_id,
                "sid": step_id,
                "cid": caregiver_id
            }
        )
        
        await session.commit()
        
        return {
            "user_id": str(payload.app_uuid),
            "status": "onboarding_completed",
            "message": "모든 사용자 정보가 성공적으로 저장되었습니다",
            "data": {
                "user_name": payload.user_name,
                "voice_settings": {
                    "gender": payload.voice_gender,
                    "speed": payload.voice_speed
                },
                "step_length_cm": payload.step_length_cm,
                "caregiver": {
                    "name": payload.caregiver_name,
                    "phone": payload.caregiver_phone
                } if caregiver_id else None
            }
        }
        
    except Exception as e:
        await session.rollback()
        if settings.DEBUG:
            logger.exception("complete_onboarding failed")
        else:
            logger.error(f"complete_onboarding failed: {e}")
        raise HTTPException(status_code=500, detail=f"온보딩 완료 처리 실패: {str(e)}")
