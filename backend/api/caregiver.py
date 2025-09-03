from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import logging

from .users import get_session  # users.py의 세션 생성기 재사용

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/users", tags=["caregiver"])

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class CaregiverCreate(BaseModel):
    user_id: UUID
    caregivers_name: str = Field(..., max_length=32)
    phone_number: str = Field(..., max_length=32)

class CaregiverUpdate(BaseModel):
    caregivers_name: Optional[str] = Field(None, max_length=32)
    phone_number: Optional[str] = Field(None, max_length=32)

class CaregiverResponse(BaseModel):
    caregiver_id: int
    user_id: UUID
    caregivers_name: str
    phone_number: str

# message 필드 제거
class AlertRequest(BaseModel):
    user_id: UUID

class CaregiverAlertResponse(BaseModel):
    status: str
    message: str
    caregiver_phone: str
    current_location: str = Field(..., description="사용자의 현재 위치 주소")

# ─────────────────────────────────────────────────────────────
# POST /api/users/caregiver : 보호자 정보 등록
# ─────────────────────────────────────────────────────────────
@router.post("/caregiver", response_model=CaregiverResponse)
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
        await session.commit()

        if not row:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create caregiver")

        return CaregiverResponse.model_validate(row, from_attributes=True)

    except IntegrityError as e:
        await session.rollback()
        if "violates foreign key constraint" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User with id '{user_id_str}' not found")
        if "violates unique constraint" in str(e.orig):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Caregiver already exists for this user")
        logger.exception("DB integrity error during caregiver creation")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database integrity error")
    except Exception as e:
        await session.rollback()
        logger.exception("DB error during caregiver creation")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")

# ─────────────────────────────────────────────────────────────
# PATCH /api/users/caregiver/{user_id} : 보호자 정보 수정
# ─────────────────────────────────────────────────────────────
@router.patch("/caregiver/{user_id}", response_model=CaregiverResponse)
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

        return CaregiverResponse.model_validate(row, from_attributes=True)
    except Exception as e:
        await session.rollback()
        logger.exception("DB error during caregiver update")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")

# ─────────────────────────────────────────────────────────────
# POST /api/users/caregiver/alert : 위험 감지시 보호자 호출
# ─────────────────────────────────────────────────────────────
@router.post("/caregiver/alert", response_model=CaregiverAlertResponse)
async def send_caregiver_alert(req: AlertRequest, session: AsyncSession = Depends(get_session)):
    user_id_str = str(req.user_id)
    try:
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

        # 서버에서 자동 메시지 생성
        auto_message = f"[긴급] {caregiver.user_name}님에게 위급 상황이 발생했습니다. 확인이 필요합니다."

        log_query = text("""
                         INSERT INTO dashboard_logs (user_id, log_type, log_data)
                         VALUES (:user_id, 'EMERGENCY_ALERT', :log_data)
                         """)
        await session.execute(log_query, {
            "user_id": user_id_str,
            "log_data": f"Emergency alert sent to {caregiver.caregivers_name} ({caregiver.phone_number}): {auto_message}"
        })
        await session.commit()

        current_location = "위치 정보 확인 불가"

        return CaregiverAlertResponse(
            status="success",
            message=f"Alert sent to {caregiver.caregivers_name}",
            caregiver_phone=caregiver.phone_number,
            current_location=current_location
        )

    except Exception as e:
        await session.rollback()
        logger.exception("Error sending caregiver alert")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")
