# api/camera.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from uuid import UUID
import json
import base64
import logging
import cv2
import numpy as np

# api.objects 모듈에서 객체 탐지 함수와 모델을 임포트
from .objects import detect_objects_yolo, DetectedObject

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/camera", tags=["camera"])

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
        logger.info(f"User {user_id} disconnected from camera stream.")

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_text(message)

manager = ConnectionManager()

def _base64_to_image(base64_str: str) -> np.ndarray:
    """Base64 문자열을 OpenCV 이미지(np.ndarray)로 디코딩"""
    # 데이터 URL 형식( e.g., "data:image/jpeg;base64,..." ) 제거
    if "," in base64_str:
        base64_str = base64_str.split(',')[1]
    
    img_bytes = base64.b64decode(base64_str)
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    image = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    return image

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
            # 클라이언트로부터 데이터 수신 (JSON 형식)
            data = await websocket.receive_text()
            try:
                frame_data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON from user {user_id_str}")
                continue

            # Base64 인코딩된 프레임 데이터 확인
            if "frame" in frame_data and isinstance(frame_data["frame"], str):
                # Base64 -> OpenCV 이미지로 변환
                cv_image = _base64_to_image(frame_data["frame"])

                if cv_image is None:
                    logger.warning(f"Could not decode image from user {user_id_str}")
                    continue
                
                # 객체 탐지 수행
                try:
                    detected_objects = detect_objects_yolo(cv_image)
                    
                    # Pydantic 모델을 JSON으로 직렬화 가능한 dict 리스트로 변환
                    objects_list = [obj.model_dump() for obj in detected_objects]
                    
                    # 클라이언트에 결과 전송
                    response = {
                        "status": "processed",
                        "timestamp": frame_data.get("timestamp"),
                        "user_id": user_id_str,
                        "objects": objects_list
                    }
                    await websocket.send_text(json.dumps(response))

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
