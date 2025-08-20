from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from .common_models import ExecutionStatus
class CommandExecutionResponse(BaseModel):
    """명령 실행 응답 모델"""
    status: ExecutionStatus = Field(
        description="실행 상태",
        example=ExecutionStatus.SUCCESS
    )
    message: str = Field(
        description="실행 결과 메시지",
        example="카메라 모드가 활성화되었습니다."
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="실행 결과 데이터",
        example={"mode": "camera", "preview_enabled": True}
    )
    actions: List[str] = Field(
        default_factory=list,
        description="수행된 액션 목록",
        example=["camera_module_init", "preview_start"]
    )
    timestamp: datetime = Field(
        description="실행 시각",
        example="2024-01-15T10:30:00"
    )

class FullCommandRequest(BaseModel):
    """전체 명령 처리 요청 (인식 + 실행)"""
    command_text: str = Field(
        description="음성으로 인식된 텍스트 명령",
        example="카메라 모드"
    )
    execute_immediately: bool = Field(
        default=True,
        description="즉시 실행 여부",
        example=True
    )
    user_id: Optional[str] = Field(
        default=None,
        description="사용자 ID (선택사항)",
        example="user123"
    )

class FullCommandResponse(BaseModel):
    """전체 명령 처리 응답"""
    # 인식 결과
    intent: str = Field(description="인식된 의도")
    entities: Dict[str, Any] = Field(description="추출된 엔티티")
    confidence: float = Field(description="인식 신뢰도")
    
    # 실행 결과
    execution: CommandExecutionResponse = Field(description="실행 결과")
