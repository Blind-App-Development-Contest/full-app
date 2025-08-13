# api/objects.py
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from uuid import UUID
import cv2
import numpy as np
import io
import logging
from datetime import datetime

# YOLO 모델 (추후 로드)
# from ultralytics import YOLO

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/objects", tags=["objects"])

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class DetectedObject(BaseModel):
    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: dict  # {"x": int, "y": int, "width": int, "height": int}
    distance: Optional[float] = None  # 미터 단위

class ObjectDetectionResponse(BaseModel):
    user_id: UUID
    objects: List[DetectedObject]
    image_size: dict  # {"width": int, "height": int}
    processed_at: datetime

class ThreatData(BaseModel):
    user_id: UUID
    object_name: str
    threat_level: int = Field(..., ge=1, le=5)  # 1=낮음, 5=매우위험
    coordinates: dict  # {"x": int, "y": int}
    distance: Optional[float] = None
    description: Optional[str] = None

class VibrationPattern(BaseModel):
    user_id: UUID
    pattern_type: Literal["danger", "warning", "info"] = "warning"
    intensity: int = Field(5, ge=1, le=10)
    duration_ms: int = Field(500, ge=100, le=2000)
    reason: Optional[str] = None

class TextReadRequest(BaseModel):
    user_id: UUID
    language_code: str = "ko-KR"
    read_aloud: bool = True  # TTS로 읽어줄지 여부

# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
def load_image_from_upload(file_content: bytes) -> np.ndarray:
    """업로드된 파일을 OpenCV 이미지로 변환"""
    nparr = np.frombuffer(file_content, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return image

def detect_objects_yolo(image: np.ndarray) -> List[DetectedObject]:
    """YOLO 모델로 객체 탐지 (추후 구현)"""
    # TODO: YOLO 모델 로드 및 추론
    # model = YOLO('yolov8n.pt')
    # results = model(image)
    
    # 임시 더미 데이터
    dummy_objects = [
        DetectedObject(
            name="person",
            confidence=0.95,
            bbox={"x": 100, "y": 150, "width": 200, "height": 300},
            distance=2.5
        ),
        DetectedObject(
            name="car",
            confidence=0.87,
            bbox={"x": 300, "y": 100, "width": 400, "height": 250},
            distance=10.0
        )
    ]
    return dummy_objects

def calculate_threat_level(obj: DetectedObject) -> int:
    """객체와 거리를 기반으로 위험도 계산"""
    dangerous_objects = ["car", "truck", "motorcycle", "bicycle"]
    
    if obj.name in dangerous_objects:
        if obj.distance and obj.distance < 2.0:
            return 5  # 매우 위험
        elif obj.distance and obj.distance < 5.0:
            return 4  # 위험
        else:
            return 2  # 경고
    
    return 1  # 안전

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/", response_model=ObjectDetectionResponse)
async def detect_objects(
    request: Request,
    image: UploadFile = File(...),
    user_id: UUID = Form(...)
):
    """
    사물 인식 API
    업로드된 이미지에서 객체를 탐지하고 결과 반환
    """
    pool: asyncpg.Pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=500, detail="DB pool not initialized")

    # 사용자 존재 확인
    async with pool.acquire() as conn:
        user_exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE user_id = $1", user_id
        )
        if not user_exists:
            raise HTTPException(status_code=404, detail="User not found")

    try:
        # 이미지 로드
        image_content = await image.read()
        cv_image = load_image_from_upload(image_content)
        
        if cv_image is None:
            raise HTTPException(status_code=400, detail="Invalid image format")
        
        height, width = cv_image.shape[:2]
        
        # 객체 탐지
        detected_objects = detect_objects_yolo(cv_image)
        
        # 객체 탐지 완료
        
        return ObjectDetectionResponse(
            user_id=user_id,
            objects=detected_objects,
            image_size={"width": width, "height": height},
            processed_at=datetime.now()
        )
        
    except Exception as e:
        logger.exception("Object detection error")
        raise HTTPException(status_code=500, detail=f"Detection error: {str(e)}")

@router.post("/threats")
async def process_threat(threat: ThreatData):
    """
    위험 감지 처리 API
    탐지된 위험 상황을 처리하고 응답
    """
    return {
        "status": "processed",
        "user_id": str(threat.user_id),
        "threat_level": threat.threat_level,
        "object_name": threat.object_name,
        "coordinates": threat.coordinates,
        "distance": threat.distance
    }

@router.post("/vibration")
async def trigger_vibration(vibration: VibrationPattern):
    """
    진동 알림 트리거 API
    클라이언트에서 진동 패턴 정보를 받아 처리
    """
    return {
        "status": "triggered",
        "user_id": str(vibration.user_id),
        "pattern": vibration.pattern_type,
        "intensity": vibration.intensity,
        "duration_ms": vibration.duration_ms,
        "reason": vibration.reason
    }

@router.post("/texts")
async def read_text_ocr(
    image: UploadFile = File(...),
    user_id: UUID = Form(...),
    language_code: str = Form("ko-KR"),
    read_aloud: bool = Form(True)
):
    """
    OCR 텍스트 읽기 API
    이미지에서 텍스트를 추출하고 TTS로 변환
    """

    try:
        # 이미지 로드
        image_content = await image.read()
        cv_image = load_image_from_upload(image_content)
        
        if cv_image is None:
            raise HTTPException(status_code=400, detail="Invalid image format")
        
        # TODO: OCR 처리 (예: Google Vision API, EasyOCR 등)
        # 임시 더미 텍스트
        extracted_text = "안전보행 신호등 앞 횡단보도"
        
        # OCR 텍스트 추출 완료
        
        if read_aloud:
            # 기존 TTS API 활용
            from google.cloud import texttospeech
            
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=extracted_text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            return StreamingResponse(
                io.BytesIO(response.audio_content),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": "inline; filename=\"ocr_text.mp3\"",
                    "X-Extracted-Text": extracted_text
                }
            )
        else:
            return {
                "user_id": str(user_id),
                "extracted_text": extracted_text,
                "language_code": language_code
            }
            
    except Exception as e:
        logger.exception("OCR text reading error")
        raise HTTPException(status_code=500, detail=f"OCR error: {str(e)}")
