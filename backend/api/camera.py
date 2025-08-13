# api/camera.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request
from uuid import UUID
import asyncpg
import cv2
import asyncio
import json
import base64
import logging

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/camera", tags=["camera"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_text(message)

manager = ConnectionManager()

@router.websocket("/stream/{user_id}")
async def camera_stream(websocket: WebSocket, user_id: UUID):
    """
    실시간 카메라 스트리밍 WebSocket
    클라이언트에서 카메라 프레임을 전송하면 처리 결과를 응답
    """
    user_id_str = str(user_id)
    await manager.connect(websocket, user_id_str)
    
    try:
        while True:
            # 클라이언트로부터 카메라 프레임 수신
            data = await websocket.receive_text()
            frame_data = json.loads(data)
            
            # Base64 이미지 디코딩
            if "frame" in frame_data:
                # 여기서 객체 탐지, 위험 감지 등 처리
                # 결과를 클라이언트에 전송
                response = {
                    "status": "processed",
                    "timestamp": frame_data.get("timestamp"),
                    "user_id": user_id_str
                }
                await websocket.send_text(json.dumps(response))
                
    except WebSocketDisconnect:
        manager.disconnect(user_id_str)
        logger.info(f"Camera stream disconnected for user: {user_id_str}")

# 상태 확인은 WebSocket 내에서 처리하거나, 필요시에만 별도 엔드포인트 사용
