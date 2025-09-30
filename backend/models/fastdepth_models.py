"""FastDepth 관련 Pydantic 모델들"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class FrameProcessRequest(BaseModel):
    """프레임 처리 요청"""
    user_id: Optional[str] = Field(None, description="사용자 ID")

class FrameProcessResponse(BaseModel):
    """프레임 처리 응답"""
    success: bool = Field(description="처리 성공 여부")
    message: str = Field(description="처리 결과 메시지")
    measurement_active: bool = Field(description="측정 활성 상태")
    current_result: Optional[Dict[str, Any]] = Field(None, description="현재 측정 결과")
    timestamp: datetime = Field(default_factory=datetime.now, description="처리 시각")

class SpeechCommandRequest(BaseModel):
    """음성 명령 요청 - 통합된 요청 모델"""
    command_text: str = Field(..., description="음성 명령 텍스트")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    context: Optional[str] = Field(None, description="명령 컨텍스트")
    execute_immediately: bool = Field(default=True, description="즉시 실행 여부")


