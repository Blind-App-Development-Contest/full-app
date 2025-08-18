from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from models.transcription import Transcription
from services.speech_service import SpeechService

router = APIRouter()
speech_service = SpeechService()

@router.post("/api/users/speech/recognition")
async def transcribe_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    오디오 파일을 받아 OpenAI Whisper로 변환하고, 결과를 DB에 저장합니다.
    """
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="오디오 파일이 아닙니다.")

    # 파일 내용을 바이트로 읽기
    audio_bytes = await file.read()
    
    # 음성 인식 서비스 호출
    transcribed_text = await speech_service.transcribe_audio(audio_bytes)
    
    if transcribed_text:
        # DB에 결과 저장
        db_transcription = Transcription(text=transcribed_text)
        db.add(db_transcription)
        db.commit()
        db.refresh(db_transcription)
        
        return {
            "text": db_transcription.text,
            "id": db_transcription.id,
            "created_at": db_transcription.created_at
        }
    else:
        return {"text": ""}