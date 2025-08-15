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
import json
import asyncpg
from datetime import datetime
from ultralytics import YOLO
from core.cache import latest_detection_results

logger = logging.getLogger("uvicorn.error")

# YOLO 모델 로드 (애플리케이션 시작 시 한 번만 로드)
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
    dangerous_objects = ["car", "truck", "motorcycle", "bicycle", "keyboard"]
    
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

async def save_threat_to_log(
    pool: asyncpg.Pool,
    user_id: UUID,
    obj: DetectedObject,
    threat_level: int
):
    """탐지된 위험 객체를 dashboard_logs 테이블에 저장"""
    if pool is None:
        logger.error("Database pool is not available.")
        return

    log_data = {
        "object_name": obj.name,
        "threat_level": threat_level,
        "confidence": obj.confidence,
        "bbox": obj.bbox,
        "distance": obj.distance,
    }

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dashboard_logs (user_id, log_type, log_data)
                VALUES ($1, 'threat_detected', $2)
                """,
                user_id,
                json.dumps(log_data)
            )
        logger.info(f"Saved threat to log for user {user_id}: {obj.name}")
    except Exception as e:
        logger.exception(f"Failed to save threat to log for user {user_id}")

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/{user_id}")
async def get_latest_detection(user_id: UUID):
    """
    실시간 스트림의 최신 객체 탐지 결과를 반환합니다.
    결과는 인메모리 캐시에서 조회합니다.
    """
    user_id_str = str(user_id)
    if user_id_str in latest_detection_results:
        return latest_detection_results[user_id_str]
    else:
        raise HTTPException(
            status_code=404,
            detail="No active stream or detection result found for this user."
        )

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


