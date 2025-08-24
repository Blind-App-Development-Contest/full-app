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

# api.objects 모듈에서 필요한 함수와 클래스를 가져옵니다.
from .objects import detect_objects_yolo, DetectedObject, calculate_threat_level, VibrationPattern, save_threat_to_log
from core.cache import latest_detection_results

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/camera", tags=["camera"])

# (사용자 ID, 객체 이름)을 키로, 마지막 로그 시간을 값으로 저장하여 중복 로깅을 방지합니다.
last_threat_log_time: dict[tuple[str, str], float] = {}

class ConnectionManager:
    """WebSocket 연결을 관리하는 클래스"""
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"User {user_id} connected to camera stream.")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        keys_to_del = [key for key in last_threat_log_time if key[0] == user_id]
        for key in keys_to_del:
            del last_threat_log_time[key]
        logger.info(f"User {user_id} disconnected from camera stream.")

manager = ConnectionManager()

def _base64_to_image(base64_str: str) -> np.ndarray:
    """Base64 문자열을 OpenCV 이미지로 디코딩하는 헬퍼 함수"""
    if "," in base64_str:
        base64_str = base64_str.split(',')[1]
    img_bytes = base64.b64decode(base64_str)
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

@router.websocket("/stream/{user_id}")
async def camera_stream(websocket: WebSocket, user_id: UUID):
    """
    실시간 카메라 스트리밍 WebSocket 엔드포인트.
    - 기본 동작: 프레임을 받아 위험도를 분석하고, 위험도에 따른 진동 패턴을 응답합니다.
    - 'action' 필드 포함 시: 요청에 맞는 특별 동작을 수행합니다.
      - action='list_all_objects': 해당 프레임의 모든 객체 목록을 응답합니다.
    """
    user_id_str = str(user_id)
    await manager.connect(websocket, user_id_str)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                # 클라이언트로부터 받은 JSON 데이터를 파싱합니다.
                frame_data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON from {user_id_str}")
                continue

            # 프레임 데이터에 'action' 필드가 있는지 확인합니다.
            action = frame_data.get("action")

            if "frame" not in frame_data or not isinstance(frame_data["frame"], str):
                logger.warning(f"Invalid frame data from {user_id_str}")
                continue

            cv_image = _base64_to_image(frame_data["frame"])
            if cv_image is None:
                logger.warning(f"Could not decode image from {user_id_str}")
                continue
            
            try:
                # YOLO 모델로 객체 탐지를 수행합니다. (두 기능 모두 공통으로 필요)
                detected_objects = detect_objects_yolo(cv_image)

                # ─── 1. [새로운 기능] 객체 목록 요청 처리 ───
                if action == "list_all_objects":
                    # 탐지된 모든 객체의 이름만 추출하여 리스트를 만듭니다.
                    object_names = [obj.name for obj in detected_objects]
                    response = {
                        "type": "object_list",
                        "objects": object_names,
                        "timestamp": frame_data.get("timestamp"),
                    }
                    # 생성된 객체 목록을 클라이언트에 전송합니다.
                    await websocket.send_text(json.dumps(response))

                # ─── 2. [기존 기능] 실시간 위협 탐지 처리 ───
                else:
                    vibration_pattern = None
                    highest_threat_level = 0
                    
                    if detected_objects:
                        threats = [(obj, calculate_threat_level(obj)) for obj in detected_objects]
                        highest_threat_obj, highest_threat_level = max(threats, key=lambda item: item[1])

                        # 위험도 레벨에 따라 진동 패턴을 결정합니다.
                        if highest_threat_level >= 2:
                            if highest_threat_level == 5: pattern_type, intensity, duration_ms = "danger", 10, 1500
                            elif highest_threat_level == 4: pattern_type, intensity, duration_ms = "warning", 8, 800
                            elif highest_threat_level == 3: pattern_type, intensity, duration_ms = "warning", 5, 400
                            else: pattern_type, intensity, duration_ms = "info", 3, 200
                            
                            vibration_pattern = VibrationPattern(
                                user_id=user_id, pattern_type=pattern_type, intensity=intensity,
                                duration_ms=duration_ms, reason=f"'{highest_threat_obj.name}' detected"
                            )
                            
                            # 5초에 한 번만 위험 로그를 DB에 저장합니다.
                            log_key = (user_id_str, highest_threat_obj.name)
                            current_time = time.time()
                            if current_time - last_threat_log_time.get(log_key, 0) > 5:
                                pool = websocket.app.state.db_pool
                                await save_threat_to_log(pool, user_id, highest_threat_obj, highest_threat_level)
                                last_threat_log_time[log_key] = current_time

                    # 기존의 실시간 위협 감지 응답을 생성합니다.
                    response = {
                        "type": "threat_detection",
                        "objects": [obj.model_dump() for obj in detected_objects],
                        "highest_threat_level": highest_threat_level,
                        "vibration": vibration_pattern.model_dump() if vibration_pattern else None
                    }
                    
                    # 최신 결과를 캐시에 저장합니다.
                    latest_detection_results[user_id_str] = response
                    await websocket.send_text(json.dumps(jsonable_encoder(response)))

            except Exception as e:
                logger.exception(f"Error during object detection for {user_id_str}")
                await websocket.send_text(json.dumps({"status": "error", "message": str(e)}))

    except WebSocketDisconnect:
        manager.disconnect(user_id_str)
    except Exception as e:
        logger.exception(f"An unexpected error in stream for {user_id_str}")
        manager.disconnect(user_id_str)
