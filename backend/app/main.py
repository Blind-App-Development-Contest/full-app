# app/main.py
import sys
import os

# === 패키지 경로 설정 ===
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import asyncpg
import uvicorn

# === .env는 가장 먼저 로드해야 settings에 반영됨 ===
load_dotenv()

# === 라우터들 ===
from api.speech_routes import router as speech_router
from api import users, update_name
from api import voice as voice_module            # /api/users/voice
from api.maps import router as maps_router       # ✅ /maps/* 라우트

# === 설정 ===
from config.settings import get_settings
settings = get_settings()

app = FastAPI(title="Full App", debug=settings.DEBUG)


def _normalize_dsn(dsn: str) -> str:
    """sqlalchemy 스타일 DSN을 asyncpg용으로 보정"""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS or ["*"],  # 개발 중엔 * 허용, 운영에선 도메인 제한 권장
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === 앱 라이프사이클 ===
@app.on_event("startup")
async def on_startup():
    # DB 연결
    dsn = _normalize_dsn(os.getenv("DB_URL", settings.db_url or "postgresql://appuser:1111@localhost:5432/appdb"))
    app.state.db_pool = await asyncpg.create_pool(dsn=dsn)

    # 유용한 환경키 로딩 여부 로깅 (값은 노출하지 않음)
    has_mapbox = bool(os.getenv("MAPBOX_ACCESS_TOKEN"))
    has_naver_id = bool(os.getenv("NAVER_CLIENT_ID") or getattr(settings, "NAVER_CLIENT_ID", None))
    has_naver_secret = bool(os.getenv("NAVER_CLIENT_SECRET") or getattr(settings, "NAVER_CLIENT_SECRET", None))
    print(f"🔑 ENV CHECK | MAPBOX_TOKEN={'OK' if has_mapbox else 'MISSING'} "
          f"| NAVER_ID={'OK' if has_naver_id else 'MISSING'} "
          f"| NAVER_SECRET={'OK' if has_naver_secret else 'MISSING'}")


@app.on_event("shutdown")
async def on_shutdown():
    pool = getattr(app.state, "db_pool", None)
    if pool:
        await pool.close()


# === 루트/헬스 ===
@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "message": "서버 실행 중",
        "version": "1.0.0",
        "endpoints": {
            "speech_recognition": "/api/users/speech/recognition",
            "tts_play_page": "/play",
            "maps_directions": "/maps/directions",
            # 아래 둘은 구현된 경우만 사용하세요 (미구현이면 제거 권장)
            "places_autocomplete": "/maps/places/autocomplete",
            "place_detail": "/maps/places/detail",
        },
        "status": "running",
    }


# === 음성 재생 테스트 페이지 ===
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
    const blob = await r.blob();
    $("player").src = URL.createObjectURL(blob);
    $("player").play();
    $("status").textContent = "재생 중";
  } catch(e) {
    $("status").textContent = "에러: " + e.message;
  }
};
</script>
"""


# === 라우터 등록 ===
app.include_router(users.router)
app.include_router(update_name.router)
app.include_router(voice_module.router)                         # /api/users/voice
app.include_router(speech_router, prefix="/api/users/speech", tags=["Speech Recognition"])
app.include_router(maps_router)                                 # ✅ /maps/* 라우트 (api/maps.py에서 prefix="/maps")


# === 로컬 실행 ===
if __name__ == "__main__":
    print("🚀 서버 시작: http://%s:%s" % (settings.HOST, settings.PORT))
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
