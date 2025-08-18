import os
import httpx
from fastapi import HTTPException
from dotenv import load_dotenv

class SpeechService:
    def __init__(self):
        load_dotenv()  # .env 파일 로드
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")

    async def transcribe_audio(self, file_content: bytes) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": ("audio.m4a", file_content, "audio/m4a")}
        data = {"model": "whisper-1", "language": "ko"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60.0
                )
                response.raise_for_status()
                
                result = response.json()
                return result.get("text", "")

            except httpx.HTTPStatusError as e:
                print(f"OpenAI API 에러: {e.response.status_code}")
                print(f"에러 내용: {e.response.text}")
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"OpenAI API 에러: {e.response.text}"
                )
            except Exception as e:
                print(f"내부 서버 오류: {e}")
                raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")