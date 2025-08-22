import sys
import os
import logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import asyncpg
import logging
import uvicorn

# 통합 에러 처리 미들웨어
from middleware.error_handler import ErrorHandlerMiddleware

# API 라우터 imports
from api.speech import router as speech_router
from api.measurement import router as measurement_router
from api.execution import router as execution_router
from api.footstep import router as footstep_router
from api import users, update_name, caregiver
from api import voice as voice_module
from api import camera, objects
from api import realtime_routes

# Config & Services
from config.settings import get_settings
from services.singleton import service_manager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Full App")

load_dotenv()
logger = logging.getLogger("uvicorn.error")

def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

# 통합 에러 처리 미들웨어
app.add_middleware(ErrorHandlerMiddleware)

# CORS 설정 (Flutter 앱 및 웹 테스트 페이지에서 호출 가능하도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
  
    """서버 시작 시 초기화"""
    logger.info("🚀 음성 명령 인식 서버 시작")
    
    # 데이터베이스 연결 풀 생성
    dsn = _normalize_dsn(os.getenv("DB_URL", "postgresql://appuser:1111@localhost:5432/appdb"))
    app.state.db_pool = await asyncpg.create_pool(dsn=dsn)
    
    # 싱글톤 서비스 인스턴스 미리 생성
    command_executor = service_manager.get_command_executor()
    speech_analyzer = service_manager.get_speech_analyzer()
    speech_service = service_manager.get_speech_service()
    
    logger.info("✅ 서비스 인스턴스 생성 완료")
    logger.info("🎤 음성 명령 인식 시스템 준비 완료!")

    try:
        dsn = _normalize_dsn(os.getenv("DB_URL", "postgresql://appuser:1111@localhost:5432/appdb"))
        app.state.db_pool = await asyncpg.create_pool(dsn=dsn)
        logger.info("Database connection pool started successfully.")
    except Exception as e:
        logger.critical(f"FATAL: Could not connect to database via asyncpg pool: {e}")
        
@app.on_event("shutdown")
async def on_shutdown():
    """서버 종료 시 정리"""
    
    # 데이터베이스 연결 종료
    pool = getattr(app.state, "db_pool", None)
    if pool:
        await pool.close()
    
    logger.info(" 서버 종료 완료")

@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "message": "시각장애인 음성 보조 시스템 API 서버",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "speech_processing": "/api/users/speech",
            "measurement_system": "/api/users/measurement",
            "command_execution": "/api/users/action", 
            "footstep_management": "/api/users/footstep",
            "user_management": "/users",
            "voice_synthesis": "/api/users/voice",
            "api_docs": "/docs"
        },
    }

if __name__ == "__main__":
    logger.info("🚀 시각장애인 음성 보조 시스템 서버 시작")
    logger.info(f"📍 서버 주소: http://{settings.HOST}:{settings.PORT}")
    logger.info(f"📖 API 문서: http://{settings.HOST}:{settings.PORT}/docs")
    
    uvicorn.run(
        app, 
        host=settings.HOST, 
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )        
        
# 음성 확인용 [http://localhost:8000/play]
@app.get("/play", response_class=HTMLResponse)
def play_page():
    # ... (HTML content is long, keeping it as is)
    return '''
<!doctype html><meta charset="utf-8">
<h2>TTS Quick Play</h2>
<label>User ID <input id="uid" style="width:320px" placeholder="users 테이블의 ID"/></label><br><br>
<label>Text <input id="text" style="width:480px" value="테스트 음성입니다."/></label><br><br>
<label>Gender
  <select id="gender"><option>female</option><option>male</option></select>
</label>
<label>Speed <input id="speed" type="number" step="0.05" value="1.0"></label>
<button id="go">재생</button>
<div id="status" style="margin-top:8px;color:#666"></div>
<audio id="player" controls style="display:block;margin-top:10px;width:480px"></audio>
<script>
const $ = id=>document.getElementById(id);
$("go").onclick = async () => {
  const body = {
    user_id: $("uid").value.trim(),
    text: $("text").value,
    gender: $("gender").value,
    speed: parseFloat($("speed").value),
    audio_encoding: "MP3",
  };
  $("status").textContent = "합성 중...";
  try {
    const r = await fetch("/api/users/voice", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(body)
    });
    if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob(); // audio/mpeg
    $("player").src = URL.createObjectURL(blob);
    $("player").play();
    $("status").textContent = "재생 중";
  } catch(e) {
    $("status").textContent = "에러: " + e.message;
  }
};
</script>
'''

# 웹캠 테스트용 엔드포인트
@app.get("/test-camera", response_class=HTMLResponse)
async def test_camera_page():
    """웹캠 객체 탐지 테스트 페이지를 반환합니다."""
    try:
        with open("templates/camera_test.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Test page not found.</h1>", status_code=404)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}


# 라우터 등록
app.include_router(users.router)
app.include_router(voice_module.router)  # /api/users/voice
app.include_router(caregiver.router)
app.include_router(footstep_router, prefix="/api/users/footstep", tags=["Footstep Management"])
app.include_router(speech_router, prefix="/api/users/speech", tags=["Speech Processing"])
app.include_router(measurement_router, prefix="/api/users/measurement", tags=["Measurement System"])
app.include_router(execution_router, prefix="/api/users/action", tags=["Command Execution"])

# 테스트용 라우터
app.include_router(realtime_routes.router, prefix="/api/realtime", tags=["Real-time FastDepth Processing"])

app.include_router(camera.router)        # /api/camera
app.include_router(objects.router)       # /api/objects
app.include_router(camera.router)        # /api/camera
app.include_router(objects.router)       # /api/objects
