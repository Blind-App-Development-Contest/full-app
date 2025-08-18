import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api import users
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api.speech_routes import router as speech_router
from config.settings import get_settings


settings = get_settings()

# FastAPI 앱 생성
app = FastAPI(title="음성 명령 인식 테스트 API", version="1.0.0")

# CORS 설정 (Flutter 앱에서 호출 가능하도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(users.router)
app.include_router(speech_router, prefix="/api/users/speech", tags=["Speech Recognition"])

@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "message": "음성 명령 인식 테스트 서버가 실행 중입니다",
        "endpoint": "/api/users/speech/recognition",
        "version": "1.0.0",
        "status": "running"
    }

if __name__ == "__main__":
    print("🚀 음성 명령 인식 테스트 서버 시작")
    
    uvicorn.run(
        app, 
        host=settings.HOST, 
        port=settings.PORT,
        reload=settings.DEBUG
    )