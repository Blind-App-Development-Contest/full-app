"""
사용자 통합 설정 관리 API
user_settings 테이블과의 완전한 연동
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import logging

from models.database_models import UserSetting, Voice, Caregiver, Footstep
from core.database import get_async_db
from api.voice import speed_float_to_int_percent, int_percent_to_speed_float

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["User Settings"])

# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────

class UserSettingsResponse(BaseModel):
    """사용자 통합 설정 조회 응답"""
    setting_id: int
    user_id: UUID
    user_name: Optional[str] = None
    
    # Voice settings
    voice_id: Optional[int] = None
    voice_gender: Optional[str] = None  # M/F
    voice_speed: Optional[int] = None
    
    # Footstep settings  
    step_id: Optional[int] = None
    step_length: Optional[int] = None
    
    # Caregiver settings
    caregiver_id: Optional[int] = None
    caregiver_name: Optional[str] = None
    caregiver_phone: Optional[str] = None
    
    # Timestamps
    setting_created_at: Any
    setting_updated_at: Any

class UserSettingsUpdate(BaseModel):
    """사용자 설정 업데이트 요청"""
    voice_gender: Optional[str] = Field(None, description="음성 성별 (M/F)")
    voice_speed: Optional[float] = Field(None, ge=0.25, le=4.0, description="음성 속도 (Google TTS speaking_rate, 0.25-4.0)")
    step_length: Optional[int] = Field(None, gt=20, lt=200, description="보폭 길이 (cm)")
    caregiver_name: Optional[str] = Field(None, max_length=32, description="보호자 이름")
    caregiver_phone: Optional[str] = Field(None, max_length=32, description="보호자 전화번호")

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/settings/{user_id}", response_model=UserSettingsResponse)
async def get_user_settings(
    user_id: UUID, 
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자 통합 설정 조회 - 모든 관련 테이블 JOIN
    """
    try:
        # 복합 쿼리로 모든 설정 한번에 조회
        query = text("""
            SELECT 
                us.setting_id,
                us.user_id,
                u.user_name,
                us.voice_id,
                v.gender as voice_gender,
                v.speed as voice_speed,
                us.step_id,
                f.step_length,
                us.caregiver_id,
                c.caregivers_name as caregiver_name,
                c.phone_number as caregiver_phone,
                us.setting_created_at,
                us.setting_updated_at
            FROM user_settings us
            LEFT JOIN users u ON us.user_id = u.user_id
            LEFT JOIN voice v ON us.voice_id = v.voice_id
            LEFT JOIN footstep f ON us.step_id = f.step_id
            LEFT JOIN caregivers c ON us.caregiver_id = c.caregiver_id
            WHERE us.user_id = :user_id
        """)
        
        result = await session.execute(query, {"user_id": str(user_id)})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User settings not found for user {user_id}"
            )
        
        return UserSettingsResponse.model_validate(row, from_attributes=True)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user settings"
        )

@router.put("/settings/{user_id}")
async def update_user_settings(
    user_id: UUID,
    settings: UserSettingsUpdate,
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자 통합 설정 업데이트 - 관련 테이블들 동시 업데이트
    """
    try:
        # 먼저 user_settings 존재 확인
        settings_check = await session.execute(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        user_setting = settings_check.scalar_one_or_none()
        
        if not user_setting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User settings not found for user {user_id}"
            )
        
        updates = []
        
        # Voice 설정 업데이트
        if settings.voice_gender is not None or settings.voice_speed is not None:
            voice_updates = []
            params = {"user_id": str(user_id)}
            
            if settings.voice_gender is not None:
                voice_updates.append("gender = :gender")
                params["gender"] = settings.voice_gender
                
            if settings.voice_speed is not None:
                if not (0.25 <= settings.voice_speed <= 4.0):
                    raise HTTPException(status_code=400, detail=f"Invalid voice speed: {settings.voice_speed}")
                speed_db_value = speed_float_to_int_percent(settings.voice_speed)
                voice_updates.append("speed = :speed")
                params["speed"] = str(speed_db_value)
            
            if voice_updates:
                voice_updates.append("voice_updated_at = NOW()")
                voice_query = text(f"""
                    UPDATE voice SET {', '.join(voice_updates)}
                    WHERE user_id = :user_id
                """)
                await session.execute(voice_query, params)
                updates.append("voice")
        
        # Footstep 설정 업데이트
        if settings.step_length is not None:
            step_query = text("""
                UPDATE footstep 
                SET step_length = :step_length, step_updated_at = NOW()
                WHERE user_id = :user_id
            """)
            await session.execute(step_query, {
                "user_id": str(user_id),
                "step_length": str(settings.step_length)
            })
            updates.append("footstep")
        
        # Caregiver 설정 업데이트
        if settings.caregiver_name is not None or settings.caregiver_phone is not None:
            caregiver_updates = []
            params = {"user_id": str(user_id)}
            
            if settings.caregiver_name is not None:
                caregiver_updates.append("caregivers_name = :name")
                params["name"] = settings.caregiver_name
                
            if settings.caregiver_phone is not None:
                caregiver_updates.append("phone_number = :phone")
                params["phone"] = settings.caregiver_phone
            
            if caregiver_updates:
                caregiver_updates.append("caregiver_updated_at = NOW()")
                caregiver_query = text(f"""
                    UPDATE caregivers SET {', '.join(caregiver_updates)}
                    WHERE user_id = :user_id
                """)
                await session.execute(caregiver_query, params)
                updates.append("caregiver")
        
        # user_settings 테이블의 updated_at 갱신
        if updates:
            settings_query = text("""
                UPDATE user_settings 
                SET setting_updated_at = NOW()
                WHERE user_id = :user_id
            """)
            await session.execute(settings_query, {"user_id": str(user_id)})
        
        await session.commit()
        
        return {
            "success": True,
            "message": f"User settings updated successfully",
            "updated_sections": updates,
            "user_id": str(user_id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to update user settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user settings"
        )

@router.post("/settings/initialize/{user_id}")
async def initialize_user_settings(
    user_id: UUID,
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자 설정 초기화 - 온보딩 완료 시 호출
    모든 관련 테이블의 ID를 user_settings에 연결
    """
    try:
        # 각 테이블에서 해당 사용자의 ID들 조회
        voice_result = await session.execute(
            select(Voice.voice_id).where(Voice.user_id == user_id)
        )
        voice_id = voice_result.scalar_one_or_none()
        
        footstep_result = await session.execute(
            select(Footstep.step_id).where(Footstep.user_id == user_id)
        )
        step_id = footstep_result.scalar_one_or_none()
        
        caregiver_result = await session.execute(
            select(Caregiver.caregiver_id).where(Caregiver.user_id == user_id)
        )
        caregiver_id = caregiver_result.scalar_one_or_none()
        
        # user_settings 테이블에 upsert
        settings_query = text("""
            INSERT INTO user_settings (user_id, voice_id, step_id, caregiver_id)
            VALUES (:user_id, :voice_id, :step_id, :caregiver_id)
            ON CONFLICT (user_id) DO UPDATE SET
                voice_id = COALESCE(:voice_id, user_settings.voice_id),
                step_id = COALESCE(:step_id, user_settings.step_id),
                caregiver_id = COALESCE(:caregiver_id, user_settings.caregiver_id),
                setting_updated_at = NOW()
            RETURNING setting_id
        """)
        
        result = await session.execute(settings_query, {
            "user_id": str(user_id),
            "voice_id": str(voice_id) if voice_id is not None else None,
            "step_id": str(step_id) if step_id is not None else None,
            "caregiver_id": str(caregiver_id) if caregiver_id is not None else None
        })
        
        setting_id = result.scalar_one()
        await session.commit()
        
        return {
            "success": True,
            "message": "User settings initialized successfully",
            "setting_id": setting_id,
            "linked_ids": {
                "voice_id": voice_id,
                "step_id": step_id,
                "caregiver_id": caregiver_id
            }
        }
        
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to initialize user settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize user settings"
        )