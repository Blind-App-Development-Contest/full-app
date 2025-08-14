# app/main.py
import os
from fastapi import FastAPI
from dotenv import load_dotenv
import asyncpg

from api import users, update_name
from api import voice as voice_module  # /api/users/voice 라우터
from api import camera, objects

from fastapi.responses import HTMLResponse

app = FastAPI(title="Full App")

load_dotenv()

def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

@app.on_event("startup")
async def on_startup():
    dsn = _normalize_dsn(os.getenv("DB_URL", "postgresql://appuser:1111@localhost:5432/appdb"))
    app.state.db_pool = await asyncpg.create_pool(dsn=dsn)

@app.on_event("shutdown")
async def on_shutdown():
    # 존재 확인 후 종료
    pool = getattr(app.state, "db_pool", None)
    if pool:
        await pool.close()

# 음성 확인용 [http://localhost:8000/play]
@app.get("/play", response_class=HTMLResponse)
def play_page():
    # ... (HTML content is long, keeping it as is)
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
app.include_router(update_name.router)
app.include_router(voice_module.router)  # /api/users/voice
app.include_router(camera.router)        # /api/camera
app.include_router(objects.router)       # /api/objects

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

