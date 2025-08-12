from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("DB_URL is not set")

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


# 요청 스키마
class UserRegister(BaseModel):
    app_uuid: UUID
    user_name: str | None = None

class UpdateName(BaseModel):
    app_uuid: UUID
    user_name: str

# FastAPI 앱
router = APIRouter()

@router.get("/")
def root():
    return {"status": "ok"}

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
        import traceback; traceback.print_exc()
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
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))