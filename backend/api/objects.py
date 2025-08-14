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
from ultralytics import YOLO

logger = logging.getLogger("uvicorn.error")

# YOLO 모델 로드 (애플리케이션 시작 시 한 번만 로드)
# 'yolov8n.pt'는 작고 빠른 모델입니다. 필요에 따라 다른 모델을 사용할 수 있습니다.
try:
    model = YOLO('yolov8n.pt')
    logger.info("YOLO model loaded successfully.")
except Exception as e:
    logger.exception("Failed to load YOLO model.")
    model = None

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



# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
def load_image_from_upload(file_content: bytes) -> np.ndarray:
    """업로드된 파일을 OpenCV 이미지로 변환"""
    nparr = np.frombuffer(file_content, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return image

def detect_objects_yolo(image: np.ndarray) -> List[DetectedObject]:
    """YOLO 모델로 객체 탐지"""
    if model is None:
        raise RuntimeError("YOLO model is not loaded.")

    # YOLO 모델로 추론 수행
    results = model(image, verbose=False)  # verbose=False로 설정하여 로그 출력 줄임
    
    detected_objects = []
    # 결과 파싱
    for result in results:
        # 클래스 이름 목록
        names = result.names
        for box in result.boxes:
            # 경계 상자 좌표 (xyxy 형식)
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            # 신뢰도
            confidence = float(box.conf[0])
            # 클래스 ID
            cls_id = int(box.cls[0])
            # 클래스 이름
            cls_name = names[cls_id]
            
            # DetectedObject 모델에 맞게 데이터 변환
            detected_obj = DetectedObject(
                name=cls_name,
                confidence=confidence,
                bbox={
                    "x": x1,
                    "y": y1,
                    "width": x2 - x1,
                    "height": y2 - y1
                },
                # TODO: 거리 측정 로직 추가 필요
                distance=None 
            )
            detected_objects.append(detected_obj)
            
    return detected_objects

def calculate_threat_level(obj: DetectedObject) -> int:
    """객체와 거리를 기반으로 위험도 계산"""
    dangerous_objects = ["car", "truck", "motorcycle", "bicycle"]
    
    if obj.name in dangerous_objects:
        # TODO: 거리(distance)가 측정되면 위험도 계산 로직 고도화 필요
        if obj.distance and obj.distance < 2.0:
            return 5  # 매우 위험
        elif obj.distance and obj.distance < 5.0:
            return 4  # 위험
        else:
            # 거리를 알 수 없을 경우, 신뢰도를 기반으로 한 기본 위험도 설정
            if obj.confidence > 0.7:
                return 3 # 보통
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


