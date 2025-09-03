from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from .common_models import ExecutionStatus, CommandExecutionResponse

class FullCommandRequest(BaseModel):
    """전체 명령 처리 요청 (인식 + 실행)"""
    command_text: str = Field(description="음성으로 인식된 텍스트 명령")
    execute_immediately: bool = Field(default=True, description="즉시 실행 여부")
    user_id: Optional[str] = Field(default=None, description="사용자 ID (선택사항)")

class FullCommandResponse(BaseModel):
    """전체 명령 처리 응답"""
    # 인식 결과
    intent: str = Field(description="인식된 의도")
    entities: Dict[str, Any] = Field(description="추출된 엔티티")
    confidence: float = Field(description="인식 신뢰도")
    
    # 실행 결과
    execution: CommandExecutionResponse = Field(description="실행 결과")
