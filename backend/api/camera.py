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
        self.user_modes: dict[str, str] = {}  # Track camera mode for each user

    async def connect(self, websocket: WebSocket, user_id: str, mode: str = "realtime"):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_modes[user_id] = mode
        logger.info(f"User {user_id} connected to camera stream in {mode} mode.")

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

        if user_id in self.user_modes:
            del self.user_modes[user_id]
            
        # 사용자 연결 종료 시, 해당 사용자의 로그 기록 삭제
        keys_to_del = [key for key in last_threat_log_time if key[0] == user_id]
        for key in keys_to_del:
            del last_threat_log_time[key]
        logger.info(f"User {user_id} disconnected from camera stream.")

        
    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_text(message)
    
    def set_user_mode(self, user_id: str, mode: str):
        """Set camera mode for user"""
        self.user_modes[user_id] = mode
        logger.info(f"User {user_id} camera mode set to {mode}")
    
    def get_user_mode(self, user_id: str) -> str:
        """Get camera mode for user"""
        return self.user_modes.get(user_id, "realtime")

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

                           
                    objects_list = [obj.model_dump() for obj in detected_objects]
                    
                    # === 새로운 기능: 측정 모드일 때 보폭 측정 처리 ===
                    measurement_result = None
                    user_mode = manager.get_user_mode(user_id_str)
                    
                    if user_mode == 'measurement':
                        # 측정 세션이 활성화되어 있을 때만 프레임 처리
                        if _check_measurement_session(user_id_str):
                            try:
                                # 통합 FastDepth 프로세서를 통한 직접 이미지 처리
                                fastdepth_processor = get_fastdepth_processor()
                                step_result = await fastdepth_processor.process_frame_for_measurement(cv_image, user_id_str)
                                
                                if step_result:
                                    measurement_result = {
                                        'success': True,
                                        'step_length_cm': step_result.step_length_cm,
                                        'confidence': step_result.confidence,
                                        'tracking_quality': step_result.tracking_quality.value,
                                        'accuracy_level': step_result.accuracy_level.value,
                                        'processing_status': 'active'
                                    }
                                    logger.debug(f'측정 프레임 처리 완료: {user_id_str} - {step_result.step_length_cm}cm')
                                else:
                                    measurement_result = {
                                        'success': False,
                                        'message': '측정 세션이 비활성화 상태입니다.',
                                        'processing_status': 'inactive'
                                    }
                                    
                            except Exception as measurement_error:
                                logger.error(f'측정 프레임 처리 오류 (user: {user_id_str}): {measurement_error}')
                                measurement_result = {
                                    'success': False,
                                    'message': f'측정 처리 오류: {str(measurement_error)}',
                                    'processing_status': 'error'
                                }
                        else:
                            # 측정 세션이 비활성화된 경우
                            measurement_result = {
                                'success': False,
                                'message': '측정 세션이 시작되지 않았습니다.',
                                'processing_status': 'no_session'
                            }
                    
                    # 향상된 응답 (기존 객체 탐지 + 새로운 측정 데이터)
                    response = {
                        "type": "threat_detection",
                        "status": "processed",
                        "timestamp": frame_data.get("timestamp"),
                        "user_id": user_id_str,
                        "mode": user_mode,  # 현재 카메라 모드 포함
                        # 기존 객체 탐지 데이터
                        "objects": objects_list,
                        "highest_threat_level": highest_threat_level, # 추가된 부분
                        "vibration": vibration_pattern.model_dump() if vibration_pattern else None,
                        # 새로운 측정 데이터
                        "measurement": measurement_result
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
