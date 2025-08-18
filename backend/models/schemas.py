from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class SpeechRecognitionRequest(BaseModel):
    """음성 인식 요청 모델"""
    command_text: str = Field(
        ..., 
        description="음성으로 인식된 텍스트 명령",
        min_length=1,
        example="카메라 모드"
    )

class SpeechRecognitionResponse(BaseModel):
    """음성 인식 응답 모델"""
    intent: str = Field(
        ..., 
        description="인식된 명령의 의도",
        example="CAMERA"
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict, 
        description="추출된 엔티티 정보",
        example={"poi_name": "병원", "search_radius": 1000}
    )
    confidence: float = Field(
        default=1.0, 
        description="분석 신뢰도 (0.0 ~ 1.0)",
        ge=0.0,
        le=1.0,
        example=0.9
    )

class STTResponse(BaseModel):
    """STT 변환 응답 모델"""
    text: str = Field(
        description="변환된 텍스트",
        example="카메라 모드"
    )
    success: bool = Field(
        description="변환 성공 여부",
        example=True
    )
    message: str = Field(
        description="변환 결과 메시지",
        example="STT 성공"
    )
    file_size_bytes: int = Field(
        description="업로드된 파일 크기 (바이트)",
        example=1024
    )

class CommandTestResult(BaseModel):
    """명령어 테스트 결과 모델"""
    command: str = Field(description="테스트 명령어")
    intent: str = Field(description="인식된 의도")
    entities: Dict[str, Any] = Field(description="추출된 엔티티")
    confidence: float = Field(description="신뢰도")

class CommandTestResponse(BaseModel):
    """명령어 테스트 응답 모델"""
    test_results: list[CommandTestResult] = Field(
        description="테스트 결과 목록"
    )