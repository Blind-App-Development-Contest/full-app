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
import torch
import torch.nn as nn
import tarfile

logger = logging.getLogger("uvicorn.error")

# ─────────────────────────────────────────────────────────────
# 모델 로드
# ─────────────────────────────────────────────────────────────

# YOLO 모델 로드
try:
    yolo_model = YOLO('yolov8n.pt')
    logger.info("YOLO model loaded successfully.")
except Exception as e:
    logger.exception("Failed to load YOLO model.")
    yolo_model = None

# FastDepth 모델은 사용하지 않음
# MiDaS 모델 로드 (FastDepth 대체)
midas_model = None
midas_transform = None
try:
    # MiDaS 모델 로드 (DPT_Hybrid_384 사용)
    # torch.hub를 사용하여 모델을 로드합니다.
    # 필요한 경우 'intel-isl/MiDaS' 저장소를 로컬에 클론하거나, 인터넷 연결이 필요합니다.
    midas_model_type = "MiDaS_small"  # 또는 "DPT_Hybrid", "DPT_Large"
    midas_model = torch.hub.load("intel-isl/MiDaS", midas_model_type)
    midas_model.eval()

    # MiDaS 모델에 맞는 변환기 로드
    midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
    midas_transform = midas_transforms.small_transform if midas_model_type == "MiDaS_small" else midas_transforms.dpt_transform

    logger.info(f"MiDaS model ({midas_model_type}) loaded successfully.")
except Exception as e:
    logger.exception("Failed to load MiDaS model.")
    midas_model = None
    midas_transform = None


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

def estimate_distance(image: np.ndarray, bbox: dict) -> Optional[float]:
    """MiDaS 모델로 객체까지의 거리 추정"""
    if midas_model is None or midas_transform is None:
        return None

    try:
        # BBox에서 객체 이미지 추출
        x, y, w, h = bbox['x'], bbox['y'], bbox['width'], bbox['height']
        # Ensure bbox coordinates are within image bounds
        x = max(0, x)
        y = max(0, y)
        w = min(w, image.shape[1] - x)
        h = min(h, image.shape[0] - y)
        
        if w <= 0 or h <= 0:
            logger.warning(f"Invalid bbox dimensions: w={w}, h={h}")
            return None

        object_img = image[y:y+h, x:x+w]
        
        # MiDaS 모델 입력에 맞게 이미지 전처리
        # OpenCV 이미지를 PIL 이미지로 변환 (MiDaS transform은 PIL 이미지를 선호)
        object_img_rgb = cv2.cvtColor(object_img, cv2.COLOR_BGR2RGB)
        input_batch = midas_transform(object_img_rgb).to("cpu") # Assuming CPU for now

        with torch.no_grad():
            prediction = midas_model(input_batch)

            # MiDaS 출력은 원본 이미지 크기로 스케일링
            prediction = torch.nn.functional.interpolate(
                prediction.unsqueeze(1),
                size=object_img_rgb.shape[:2],
                mode="bicubic",
                align_corners=False,
            ).squeeze()

        depth_map = prediction.cpu().numpy()

        # 깊이 맵에서 객체 영역의 평균 깊이 계산
        # MiDaS는 깊이 값을 출력하며, 값이 작을수록 가까움
        # 실제 거리로 변환하기 위한 스케일링이 필요할 수 있음
        mean_depth = np.mean(depth_map)
        
        # MiDaS 출력은 실제 거리가 아닌 상대적인 깊이이므로,
        # 이를 실제 미터 단위로 변환하기 위한 임시 스케일링 팩터 적용
        # 이 값은 실제 환경 및 카메라 캘리브레이션에 따라 조정되어야 합니다.
        # 예를 들어, 1.0 / mean_depth * K (K는 스케일링 상수)
        # 여기서는 간단하게 역수를 취하고 임의의 스케일링 팩터를 곱합니다.
        if mean_depth > 0:
            distance = 1.0 / mean_depth * 100.0 # 임의의 스케일링 팩터
            return float(distance)
        else:
            return None
        
    except Exception as e:
        logger.exception("Failed to estimate distance with MiDaS.")
        return None


def detect_objects_yolo(image: np.ndarray) -> List[DetectedObject]:
    """YOLO 모델로 객체 탐지 및 거리 추정"""
    if yolo_model is None:
        raise RuntimeError("YOLO model is not loaded.")

    results = yolo_model(image, verbose=False)
    
    detected_objects = []
    for result in results:
        names = result.names
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            confidence = float(box.conf[0])
            cls_id = int(box.cls[0])
            cls_name = names[cls_id]
            
            bbox = {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}
            
            # 거리 추정
            distance = estimate_distance(image, bbox)
            
            detected_obj = DetectedObject(
                name=cls_name,
                confidence=confidence,
                bbox=bbox,
                distance=distance
            )
            detected_objects.append(detected_obj)
            
    return detected_objects

def calculate_threat_level(obj: DetectedObject) -> int:
    """객체 종류와 거리를 기반으로 위험도 계산"""
    # 객체 종류별 거리 임계값 및 위험도 매핑
    # (거리_미만, 해당_위험도) 튜플 리스트. 거리가 가까울수록 먼저 매칭됨.
    threat_thresholds = {
        "knife": [(1.0, 5), (3.0, 4), (float('inf'), 3)], # 1m 미만:5, 3m 미만:4, 3m 이상:3
        "scissors": [(1.0, 5), (3.0, 4), (float('inf'), 3)],
        "person": [(1.0, 5), (3.0, 4), (7.0, 3), (float('inf'), 2)], # 1m 미만:5, 3m 미만:4, 7m 미만:3, 7m 이상:2
        "car": [(2.0, 5), (5.0, 4), (15.0, 3), (float('inf'), 2)], # 2m 미만:5, 5m 미만:4, 15m 미만:3, 15m 이상:2
        "truck": [(2.0, 5), (5.0, 4), (15.0, 3), (float('inf'), 2)],
        "bus": [(2.0, 5), (5.0, 4), (15.0, 3), (float('inf'), 2)],
        "motorcycle": [(1.5, 5), (4.0, 4), (10.0, 3), (float('inf'), 2)],
        "bicycle": [(1.0, 4), (3.0, 3), (float('inf'), 2)], # 1m 미만:4, 3m 미만:3, 3m 이상:2
        "train": [(5.0, 5), (20.0, 4), (float('inf'), 3)], # 기차는 크고 빠르므로 임계값 높게 설정
        "airplane": [(float('inf'), 1)], # 비행기는 지상 위협이 아니므로 기본 위험도
        "traffic light": [(3.0, 4), (10.0, 3), (float('inf'), 2)], # 고정 장애물
        "fire hydrant": [(1.0, 4), (3.0, 3), (float('inf'), 2)],
        "stop sign": [(2.0, 4), (7.0, 3), (float('inf'), 2)],
        "parking meter": [(1.0, 4), (3.0, 3), (float('inf'), 2)],
        "bench": [(1.0, 3), (5.0, 2), (float('inf'), 1)], # 다른 고정 장애물보다 덜 치명적
        "dog": [(1.0, 4), (3.0, 3), (float('inf'), 2)], # 예측 불가능하게 움직일 수 있음
        "cat": [(1.0, 3), (3.0, 2), (float('inf'), 1)], # 작고 직접적인 위협은 적음
        "bird": [(float('inf'), 1)], # 지상 위협 최소
        "umbrella": [(1.0, 3), (3.0, 2), (float('inf'), 1)], # 방해물
        "suitcase": [(1.0, 3), (3.0, 2), (float('inf'), 1)],
    }

    threat_level = 1 # 기본값: 안전

    if obj.name in threat_thresholds:
        thresholds = threat_thresholds[obj.name]
        if obj.distance is not None:
            for dist_threshold, level in thresholds:
                if obj.distance < dist_threshold:
                    threat_level = level
                    break
        else:
            # 거리를 알 수 없을 경우, 신뢰도를 기반으로 한 기본 위험도 (기존 로직 유지)
            if obj.confidence > 0.7:
                threat_level = 2  # 경고
            else:
                threat_level = 1 # 낮음
    
    return threat_level

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
async def get_latest_detection(user_id: UUID, request: Request):
    """
    실시간 스트림의 최신 객체 탐지 결과를 반환합니다.
    결과는 인메모리 캐시에서 우선 조회하고, 없을 경우 DB의 최근 로그를 반환합니다.
    """
    user_id_str = str(user_id)
    
    if user_id_str in latest_detection_results:
        return latest_detection_results[user_id_str]
    
    pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            latest_log = await conn.fetchrow(
                """
                SELECT log_data, timestamp
                FROM dashboard_logs
                WHERE user_id = $1 AND log_type = 'threat_detected'
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                user_id
            )
    except Exception as e:
        logger.exception(f"Database error while fetching latest log for user {user_id_str}")
        raise HTTPException(status_code=500, detail="Database error.")

    if latest_log:
        log_data = json.loads(latest_log['log_data'])
        return {
            "status": "retrieved_from_db",
            "timestamp": latest_log['timestamp'].isoformat(),
            "user_id": user_id_str,
            "objects": [log_data],
            "vibration": None
        }
    
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


