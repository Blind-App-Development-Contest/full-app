# app/main.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import asyncpg
import logging
import uvicorn

from api.speech_routes import router as speech_router
from config.settings import get_settings

from api import users, caregiver
from api import voice as voice_module

from fastapi.responses import HTMLResponse

settings = get_settings()

app = FastAPI(title="Full App")

load_dotenv()
logger = logging.getLogger("uvicorn.error")

def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

# CORS 설정 (Flutter 앱에서 호출 가능하도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)  
  
@app.on_event("startup")
async def on_startup():
    try:
        dsn = _normalize_dsn(os.getenv("DB_URL", "postgresql://appuser:1111@localhost:5432/appdb"))
        app.state.db_pool = await asyncpg.create_pool(dsn=dsn)
        logger.info("Database connection pool started successfully.")
    except Exception as e:
        logger.critical(f"FATAL: Could not connect to database via asyncpg pool: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    pool = getattr(app.state, "db_pool", None)
    if pool:
        await pool.close()

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
        
# 음성 확인용 [http://localhost:8000/play]
@app.get("/play", response_class=HTMLResponse)
def play_page():
    return """
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
"""

# 라우터 등록
app.include_router(users.router)
app.include_router(voice_module.router)  # /api/users/voice
app.include_router(caregiver.router)
app.include_router(speech_router, prefix="/api/users/speech", tags=["Speech Recognition"])

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}
