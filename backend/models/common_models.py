"""통합 공통 모델들 - 애플리케이션 전체에서 사용되는 표준 데이터 구조"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import time

# ===== 공통 열거형 =====

class ExecutionStatus(str, Enum):
    """명령 실행 상태"""
    SUCCESS = "success"
    FAILED = "failed" 
    PENDING = "pending"
    NOT_SUPPORTED = "not_supported"

class TrackingQuality(str, Enum):
    """추적 품질 등급"""
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"
    EXCELLENT = "excellent"

class MeasurementType(str, Enum):
    """측정 방식"""
    KALMAN_FILTER = "kalman_filter"
    SIMPLE_DISTANCE = "simple_distance"

class AppMode(str, Enum):
    """앱 모드"""
    SETUP = "setup"
    STANDBY = "standby"
    NORMAL = "normal"
    SETTINGS = "settings"
    EMERGENCY_CALL = "emergency_call"
    SCENE_DESCRIPTION = "scene_description"
    MEASUREMENT = "measurement"
    CAMERA = "camera"
    NAVIGATION = "navigation"

class MeasurementStatus(str, Enum):
    """측정 상태 - 새로 추가"""
    INACTIVE = "inactive"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

# ===== 기본 응답 모델 =====

class BaseResponse(BaseModel):
    """기본 응답 구조"""
    success: bool = Field(description="요청 성공 여부")
    message: str = Field(description="응답 메시지")
    timestamp: datetime = Field(default_factory=datetime.now, description="응답 시각")

class BaseRequestWithUser(BaseModel):
    """사용자 ID가 포함된 기본 요청"""
    user_id: Optional[str] = Field(None, description="사용자 ID (선택사항)")

# ===== 사용자 설정 모델 =====

class UserSettings(BaseModel):
    """사용자 설정 모델 - 표준화된 사용자 정보"""
    user_name: Optional[str] = Field(None, description="사용자 이름")
    step_length_cm: Optional[float] = Field(None, description="보폭 길이 (cm)")
    voice_gender: str = Field("F", description="음성 종류 (F/M)")
    voice_speed: float = Field(1.0, ge=0.5, le=2.0, description="음성 속도 (0.5~2.0)")
    caregiver_name: Optional[str] = Field(None, description="보호자 이름")
    caregiver_phone: Optional[str] = Field(None, description="보호자 전화번호")

# ===== 실행 관련 모델 =====

class CommandExecutionResponse(BaseModel):
    """명령 실행 응답 모델 - 표준화된 실행 결과"""
    status: ExecutionStatus = Field(description="실행 상태")
    message: str = Field(description="실행 결과 메시지")
    data: Dict[str, Any] = Field(default_factory=dict, description="실행 결과 데이터")
    actions: List[str] = Field(default_factory=list, description="수행된 액션 목록")
    timestamp: datetime = Field(default_factory=datetime.now, description="실행 시각")

# ===== 측정 관련 모델 =====

class StepResult(BaseModel):
    """보폭 측정 결과"""
    step_length_cm: float = Field(description="측정된 보폭 길이 (cm)")
    confidence: float = Field(ge=0.0, le=1.0, description="측정 신뢰도")
    step_count: int = Field(ge=0, description="총 걸음 수")
    tracking_quality: TrackingQuality = Field(description="추적 품질")
    measurement_type: MeasurementType = Field(description="측정 방식")
    fps: float = Field(ge=0.0, description="처리 속도 (FPS)")
    frame_count: int = Field(ge=0, description="처리된 프레임 수")
    measurement_duration: float = Field(ge=0.0, description="측정 소요 시간 (초)")

class MeasurementProgress(BaseModel):
    """측정 진행 상황"""
    frame_count: int = Field(ge=0, description="처리된 프레임 수")
    elapsed_time: float = Field(ge=0.0, description="경과 시간 (초)")
    fps: float = Field(ge=0.0, description="현재 처리 속도 (FPS)")
    step_count: int = Field(ge=0, description="감지된 스텝 수")
    current_step_length_cm: Optional[float] = Field(None, description="현재 측정된 보폭 (cm)")

class RealTimeMeasurementStatus(BaseModel):
    """실시간 측정 상태 응답 - CommandExecutor와 realtime router가 공유"""
    measurement_active: bool = Field(description="측정 활성화 여부")
    measurement_status: MeasurementStatus = Field(description="측정 상태")
    measurement_type: Optional[MeasurementType] = Field(None, description="측정 방식")
    progress: MeasurementProgress = Field(description="측정 진행 상황")
    current_result: Optional[Dict[str, Any]] = Field(None, description="현재 측정 결과")
    
    # 세션 정보
    session_id: Optional[str] = Field(None, description="측정 세션 ID")
    start_time: Optional[datetime] = Field(None, description="측정 시작 시각")

# 기존 호환성을 위한 별칭
MeasurementStatusResponse = RealTimeMeasurementStatus

# ===== 시스템 상태 모델 =====

class SystemStatusResponse(BaseModel):
    """시스템 전체 상태 응답 - 표준화된 시스템 정보"""
    current_mode: AppMode = Field(description="현재 앱 모드")
    setup_complete: bool = Field(description="초기 설정 완료 여부")
    is_listening: bool = Field(default=True, description="음성 인식 활성 상태")
    measurement_status: RealTimeMeasurementStatus = Field(description="측정 시스템 상태")
    user_settings: UserSettings = Field(description="사용자 설정")
    last_execution: Optional[CommandExecutionResponse] = Field(None, description="마지막 실행 기록")
    total_commands: int = Field(ge=0, description="총 실행된 명령 수")
    
# ===== 음성 인식 관련 모델 =====

class SpeechRecognitionResult(BaseModel):
    """음성 인식 결과"""
    intent: str = Field(description="인식된 의도")
    entities: Dict[str, Any] = Field(default_factory=dict, description="추출된 엔티티")
    confidence: float = Field(description="인식 신뢰도", ge=0.0, le=1.0)
    command_text: str = Field(description="원본 명령 텍스트")

class UnifiedCommandResponse(BaseModel):
    """통합 명령 응답 - speech router의 /commands 엔드포인트 응답"""
    # 인식 결과
    intent: str = Field(description="인식된 의도")
    entities: Dict[str, Any] = Field(default_factory=dict, description="추출된 엔티티")
    confidence: float = Field(description="인식 신뢰도")
    
    # 실행 결과
    execution: CommandExecutionResponse = Field(description="명령 실행 결과")
    
    # 측정 상태 (필요시)
    measurement_status: Optional[RealTimeMeasurementStatus] = Field(None, description="현재 측정 상태")


# ===== 이력 관리 모델 =====

class ExecutionHistoryEntry(BaseModel):
    """실행 이력 항목"""
    command_text: str = Field(description="실행된 명령")
    intent: str = Field(description="인식된 의도")
    execution_result: CommandExecutionResponse = Field(description="실행 결과")
    user_id: Optional[str] = Field(None, description="사용자 ID")

class ExecutionHistoryResponse(BaseModel):
    """실행 기록 응답"""
    history: List[ExecutionHistoryEntry] = Field(description="실행 기록 목록")
    total_count: int = Field(ge=0, description="전체 기록 수")
    page: int = Field(ge=1, description="현재 페이지")
    page_size: int = Field(ge=1, description="페이지 크기")

# ===== 변환 유틸리티 =====

class SchemaConverter:
    """기존 스키마와의 변환 유틸리티"""
    
    
    @staticmethod
    def command_execution_result_to_response(result, measurement_status=None) -> CommandExecutionResponse:
        """CommandExecutionResult를 표준 응답으로 변환"""
        return CommandExecutionResponse(
            status=result.status,
            message=result.message,
            data=result.data,
            actions=result.actions,
            timestamp=result.timestamp
        )
    
    @staticmethod
    def create_measurement_status_from_executor(executor) -> RealTimeMeasurementStatus:
        """CommandExecutor에서 측정 상태 생성"""
        progress = executor.get_measurement_progress()
        
        # 진행 상황 구성
        measurement_progress = MeasurementProgress(
            frame_count=progress.get("frame_count", 0),
            elapsed_time=progress.get("duration", 0.0),
            fps=progress.get("tracker_status", {}).get("performance", {}).get("fps", 0.0),
            step_count=progress.get("tracker_status", {}).get("current_step", {}).get("step_count", 0),
            current_step_length_cm=progress.get("tracker_status", {}).get("current_step", {}).get("step_length_cm")
        )
        
        # 현재 결과 구성 - 딕셔너리 형태로 변환
        current_result = None
        if progress.get("tracker_status", {}).get("current_step"):
            step_data = progress["tracker_status"]["current_step"]
            current_result = {
                "step_length_cm": step_data.get("step_length_cm", 0.0),
                "confidence": step_data.get("confidence", 0.0),
                "step_count": step_data.get("step_count", 0),
                "tracking_quality": step_data.get("tracking_quality", "poor"),
                "measurement_type": MeasurementType.KALMAN_FILTER.value,
                "fps": progress.get("tracker_status", {}).get("performance", {}).get("fps", 0.0),
                "frame_count": progress.get("frame_count", 0),
                "measurement_duration": progress.get("duration", 0.0)
            }
        
        return RealTimeMeasurementStatus(
            measurement_active=progress.get("active", False),
            measurement_status=MeasurementStatus.ACTIVE if progress.get("active") else MeasurementStatus.INACTIVE,
            measurement_type=MeasurementType.KALMAN_FILTER if progress.get("active") else None,
            progress=measurement_progress,
            current_result=current_result,
            session_id=None,  # 세션 ID 추가
            start_time=datetime.fromtimestamp(progress.get("start_time", 0)) if progress.get("start_time") else None
        )

    @staticmethod
    def to_unified_command_response(
        recognition_result,
        execution_result,
        measurement_status=None,
        user_id=None,
        advanced_features_enabled=True
    ) -> UnifiedCommandResponse:
        """통합 명령 응답 생성"""
        return UnifiedCommandResponse(
            intent=recognition_result.intent,
            entities=recognition_result.entities,
            confidence=recognition_result.confidence,
            execution=execution_result,
            measurement_status=measurement_status
        )
