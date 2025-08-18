from fastapi import APIRouter, Depends
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL")
engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session

class UserRegister(BaseModel):
    app_uuid: UUID
    user_name: str | None = None

router = APIRouter()

@router.post("/users/register")
async def register_user(payload: UserRegister, session: AsyncSession = Depends(get_session)):
    # 이미 있으면 반환
    result = await session.execute(
        text("SELECT user_id FROM users WHERE user_id = :uid"),
        {"uid": str(payload.app_uuid)}
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {"user_id": existing, "status": "already_exists"}

    # 새로 생성
    await session.execute(
        text("INSERT INTO users (user_id, user_name) VALUES (:uid, :uname)"),
        {"uid": str(payload.app_uuid), "uname": payload.user_name}
    )
    await session.commit()
    return {"user_id": str(payload.app_uuid), "status": "created"}
