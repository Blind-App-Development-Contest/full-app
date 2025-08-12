from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from api.users import get_session  # 기존 DB 세션 재사용

router = APIRouter()

class UpdateName(BaseModel):
    app_uuid: UUID
    user_name: str

@router.patch("/users/update_name")
async def update_name(payload: UpdateName, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text("UPDATE users SET user_name = :uname WHERE user_id = :uid RETURNING user_id"),
        {"uid": str(payload.app_uuid), "uname": payload.user_name}
    )
    updated = result.scalar_one_or_none()
    await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user_id": str(payload.app_uuid), "status": "updated", "user_name": payload.user_name}
