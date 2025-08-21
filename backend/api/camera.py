# api/camera.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from uuid import UUID
import json
import base64
import logging
import time
import cv2
import numpy as np

# api.objects 모듈에서 객체 탐지 함수와 모델을 임포트
from .objects import detect_objects_yolo, DetectedObject, calculate_threat_level, VibrationPattern, save_threat_to_log
from core.cache import latest_detection_results

# 보폭 측정 기능을 위한 추가 임포트
from services.singleton import service_manager
from utils.fastdepth_processor import get_fastdepth_processor
from models.step_models import StepCalculationResult
from typing import Optional

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/camera", tags=["camera"])

# (사용자 ID, 객체 이름)을 키로, 마지막 로그 시간을 값으로 저장
last_threat_log_time: dict[tuple[str, str], float] = {}

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"User {user_id} connected to camera stream.")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        # 사용자 연결 종료 시, 해당 사용자의 로그 기록 삭제
        keys_to_del = [key for key in last_threat_log_time if key[0] == user_id]
        for key in keys_to_del:
            del last_threat_log_time[key]
        logger.info(f"User {user_id} disconnected from camera stream.")

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_text(message)

manager = ConnectionManager()

def _base64_to_image(base64_str: str) -> np.ndarray:
    """Base64 문자열을 OpenCV 이미지(np.ndarray)로 디코딩"""
    if "," in base64_str:
        base64_str = base64_str.split(',')[1]
    
    img_bytes = base64.b64decode(base64_str)
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    image = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    return image

def _check_measurement_session(user_id_str: str) -> bool:
    """
    사용자의 활성 측정 세션 확인 (기존 기능에 영향 없음)
    
    Args:
        user_id_str: 사용자 ID 문자열
        
    Returns:
        bool: 측정 세션이 활성화되어 있으면 True
    """
    try:
        command_executor = service_manager.get_command_executor()
        return command_executor.is_measurement_active()
    except Exception as e:
        logger.warning(f"측정 세션 확인 실패 (user: {user_id_str}): {e}")
        return False

@router.websocket("/stream/{user_id}")
async def camera_stream(websocket: WebSocket, user_id: UUID):
    """
    실시간 카메라 스트리밍 및 객체 탐지 WebSocket
    클라이언트에서 Base64로 인코딩된 카메라 프레임을 전송하면,
    객체 탐지 결과를 JSON 형태로 응답합니다.
    """
    user_id_str = str(user_id)
    await manager.connect(websocket, user_id_str)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                frame_data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON from user {user_id_str}")
                continue

            if "frame" in frame_data and isinstance(frame_data["frame"], str):
                cv_image = _base64_to_image(frame_data["frame"])
                if cv_image is None:
                    logger.warning(f"Could not decode image from user {user_id_str}")
                    continue
                
                try:
                    detected_objects = detect_objects_yolo(cv_image)
                    
                    vibration_pattern = None
                    highest_threat_level = 0
                    
                    threats = [(obj, calculate_threat_level(obj)) for obj in detected_objects]
                    
                    if threats:
                        highest_threat_obj, highest_threat_level = max(threats, key=lambda item: item[1])

                        if highest_threat_level >= 2:
                            # 세분화된 진동 패턴 매핑
                            if highest_threat_level == 5:
                                pattern_type, intensity, duration_ms = "danger", 10, 1500 # 즉각적인 위험
                            elif highest_threat_level == 4:
                                pattern_type, intensity, duration_ms = "warning", 8, 800  # 높은 위협
                            elif highest_threat_level == 3:
                                pattern_type, intensity, duration_ms = "warning", 5, 400  # 중간 위협
                            elif highest_threat_level == 2:
                                pattern_type, intensity, duration_ms = "info", 3, 200    # 낮은 위협/인지
                            else: # highest_threat_level == 1 (안전)
                                pattern_type, intensity, duration_ms = "info", 1, 100 # 매우 미미한 진동 또는 없음
                            
                            vibration_pattern = VibrationPattern(
                                user_id=user_id,
                                pattern_type=pattern_type,
                                intensity=intensity,
                                duration_ms=duration_ms,
                                reason=f"'{highest_threat_obj.name}' detected"
                            )
                            
                            # ─── 5초에 한 번만 로그 저장하는 로직 ───
                            log_key = (user_id_str, highest_threat_obj.name)
                            current_time = time.time()
                            last_log_time = last_threat_log_time.get(log_key, 0)

                            if current_time - last_log_time > 5:
                                pool = websocket.app.state.db_pool
                                await save_threat_to_log(
                                    pool=pool, 
                                    user_id=user_id, 
                                    obj=highest_threat_obj, 
                                    threat_level=highest_threat_level
                                )
                                last_threat_log_time[log_key] = current_time
                                logger.info(f"Threat log saved for {log_key}")
                            # ────────────────────────────────────────

                    objects_list = [obj.model_dump() for obj in detected_objects]
                    
                    # 클라이언트에 결과 전송
                    response = {
                        "status": "processed",
                        "timestamp": frame_data.get("timestamp"),
                        "user_id": user_id_str,
                        "objects": objects_list,
                        "highest_threat_level": highest_threat_level, # 추가된 부분
                        "vibration": vibration_pattern.model_dump() if vibration_pattern else None
                    }
                    
                    # 최신 결과를 캐시에 저장
                    latest_detection_results[user_id_str] = response
                    
                    await websocket.send_text(json.dumps(jsonable_encoder(response)))

                except Exception as e:
                    logger.exception(f"Error during object detection for user {user_id_str}")
                    # 에러 발생 시 클라이언트에게 알림
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    await websocket.send_text(json.dumps(error_response))

    except WebSocketDisconnect:
        manager.disconnect(user_id_str)
    except Exception as e:
        logger.exception(f"An unexpected error occurred in camera stream for user {user_id_str}")
        manager.disconnect(user_id_str)
