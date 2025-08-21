"""FastDepth 관련 Pydantic 모델들"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from .common_models import StepResult, MeasurementStatusResponse, SystemStatusResponse

class FastDepthFootData(BaseModel):
    """FastDepth 발 위치 데이터"""
    x: float = Field(description="X 좌표 (미터)")
    y: float = Field(description="Y 좌표 (미터)")
    z: float = Field(description="Z 좌표 (미터)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="검출 신뢰도")

class FastDepthFrameData(BaseModel):
    """FastDepth 프레임 데이터 - 통합된 프레임 구조"""
    left_foot: Optional[FastDepthFootData] = Field(None, description="왼발 위치")
    right_foot: Optional[FastDepthFootData] = Field(None, description="오른발 위치")
    timestamp: Optional[float] = Field(None, description="타임스탬프")
    frame_id: Optional[str] = Field(None, description="프레임 ID")


class FrameProcessRequest(BaseModel):
    """프레임 처리 요청"""
    frame: FastDepthFrameData = Field(..., description="처리할 프레임")
    user_id: Optional[str] = Field(None, description="사용자 ID")

class FrameProcessResponse(BaseModel):
    """프레임 처리 응답"""
    success: bool = Field(description="처리 성공 여부")
    message: str = Field(description="처리 결과 메시지")
    measurement_active: bool = Field(description="측정 활성 상태")
    current_result: Optional[StepResult] = Field(None, description="현재 측정 결과")
    timestamp: datetime = Field(default_factory=datetime.now, description="처리 시각")

class SpeechCommandRequest(BaseModel):
    """음성 명령 요청 - 통합된 요청 모델"""
    command_text: str = Field(..., description="음성 명령 텍스트")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    context: Optional[str] = Field(None, description="명령 컨텍스트")
    execute_immediately: bool = Field(default=True, description="즉시 실행 여부")

class EnhancedCommandRequest(BaseModel):
    """향상된 명령 요청 (실시간 데이터 지원)"""
    command_text: str = Field(..., description="음성 명령 텍스트")
    execute_immediately: bool = Field(default=True, description="즉시 실행 여부")
    fastdepth_frame: Optional[FastDepthFrameData] = Field(None, description="FastDepth 프레임 데이터")
    context: Optional[str] = Field(None, description="현재 컨텍스트")

