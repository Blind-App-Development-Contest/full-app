"""표준화된 보폭 측정 Pydantic 모델들 - 기존 중복 데이터 구조 통합"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from enum import Enum
import numpy as np

from .common_models import TrackingQuality, MeasurementType

# ===== 열거형 및 상수 =====

class StepTrackingQuality(str, Enum):
    """보폭 추적 품질 - 통합된 품질 표현"""
    POOR = "poor"          # 낮은 품질 (0.0-0.4)
    FAIR = "fair"          # 보통 품질 (0.4-0.7)
    GOOD = "good"          # 좋은 품질 (0.7-0.9)
    EXCELLENT = "excellent" # 우수한 품질 (0.9-1.0)

class StepMeasurementMethod(str, Enum):
    """보폭 측정 방식"""
    DISTANCE_BASED = "distance_based"      # 거리/걸음수 기반 (실제 사용)
    MANUAL_INPUT = "manual_input"          # 수동 입력 (실제 사용)

class AccuracyLevel(str, Enum):
    """정확도 수준 - 기존 한국어 문자열 표준화"""
    HIGH = "높음"    # 높은 정확도
    MEDIUM = "보통"  # 보통 정확도 
    LOW = "낮음"     # 낮은 정확도

# ===== 유틸리티 클래스 =====

class StepCalculationUtils:
    """보폭 계산 유틸리티 - 모든 계산 로직 중앙화"""
    
    @staticmethod
    def calculate_step_length_cm(distance_meters: float, step_count: int) -> float:
        """거리와 걸음수로 보폭 계산 (cm)
        
        Args:
            distance_meters: 측정된 거리 (미터)
            step_count: 걸음 수
            
        Returns:
            보폭 길이 (센티미터)
        """
        if step_count == 0:
            raise ValueError("걸음 수는 0일 수 없습니다")
        return (distance_meters * 100) / step_count
    
    @staticmethod
    def is_valid_step_length(step_length_cm: float) -> bool:
        """보폭 길이 유효성 검사
        
        Args:
            step_length_cm: 보폭 길이 (센티미터)
            
        Returns:
            유효 여부
        """
        return 30 <= step_length_cm <= 150
    
    @staticmethod
    def get_confidence_from_distance(distance_meters: float) -> float:
        """측정 거리에 따른 신뢰도 계산
        
        Args:
            distance_meters: 측정 거리 (미터)
            
        Returns:
            신뢰도 (0.0-1.0)
        """
        if distance_meters >= 5.0:
            return 0.9
        elif distance_meters >= 3.0:
            return 0.7
        elif distance_meters >= 2.0:
            return 0.5
        else:
            return 0.3

class AccuracyConverter:
    """정확도 표현 방식 간 변환 유틸리티"""
    
    @staticmethod
    def confidence_to_quality(confidence: float) -> StepTrackingQuality:
        """신뢰도 점수(0.0-1.0)를 품질 열거형으로 변환"""
        if confidence >= 0.9:
            return StepTrackingQuality.EXCELLENT
        elif confidence >= 0.7:
            return StepTrackingQuality.GOOD
        elif confidence >= 0.4:
            return StepTrackingQuality.FAIR
        else:
            return StepTrackingQuality.POOR
    
    @staticmethod
    def quality_to_confidence(quality: StepTrackingQuality) -> float:
        """품질 열거형을 신뢰도 점수로 변환"""
        mapping = {
            StepTrackingQuality.EXCELLENT: 0.95,
            StepTrackingQuality.GOOD: 0.8,
            StepTrackingQuality.FAIR: 0.55,
            StepTrackingQuality.POOR: 0.2
        }
        return mapping.get(quality, 0.5)
    
    @staticmethod
    def confidence_to_korean_level(confidence: float) -> AccuracyLevel:
        """신뢰도 점수를 한국어 정확도 수준으로 변환"""
        if confidence >= 0.8:
            return AccuracyLevel.HIGH
        elif confidence >= 0.6:
            return AccuracyLevel.MEDIUM
        else:
            return AccuracyLevel.LOW
    
    @staticmethod
    def korean_level_to_confidence(level: AccuracyLevel) -> float:
        """한국어 정확도 수준을 신뢰도 점수로 변환"""
        mapping = {
            AccuracyLevel.HIGH: 0.9,
            AccuracyLevel.MEDIUM: 0.7,
            AccuracyLevel.LOW: 0.4
        }
        return mapping.get(level, 0.5)

# ===== 입력 및 요청 모델 =====

class StepCalculationInput(BaseModel):
    """간단한 보폭 계산 입력 데이터"""
    distance_meters: float = Field(..., description="측정된 거리 (미터)", gt=0)
    step_count: int = Field(..., description="걸음 수", gt=0)
    confidence: Optional[float] = Field(0.8, description="측정 신뢰도", ge=0.0, le=1.0)
    timestamp: Optional[float] = Field(None, description="측정 시간")
    
    @field_validator('timestamp')
    @classmethod
    def set_timestamp(cls, v):
        """타임스탬프가 없으면 현재 시간 설정"""
        if v is None:
            import time
            return time.time()
        return v

class StepMeasurementRequest(BaseModel):
    """통합형 음성+프레임 보폭 측정 요청 모델"""
    
    # 프레임 기반 거리 측정 (프레임 데이터로 거리 계산)
    frame_data: Optional[Any] = Field(
        None,
        description="거리 측정용 프레임 데이터 (OpenCV 이미지)"
    )
    
    # 음성 기반 걸음수 추출 (둘 중 하나는 필수)
    voice_data: Optional[bytes] = Field(
        None,
        description="걸음수 추출용 음성 데이터 (오디오 파일)"
    )
    
    # 직접 입력된 걸음수 (음성 처리 실패시 백업용)
    step_count: Optional[int] = Field(
        None,
        description="직접 입력된 걸음 수 (음성 처리 백업용)",
        gt=0,
        le=1000
    )
    
    # distance_meters는 더 이상 입력받지 않음 (프레임으로 계산)
    
    # 측정 방식 및 설정
    measurement_method: StepMeasurementMethod = Field(
        StepMeasurementMethod.DISTANCE_BASED,
        description="측정 방식"
    )
    manual_step_length_cm: Optional[float] = Field(
        None,
        description="수동 입력 보폭 (cm)",
        gt=20,
        lt=200
    )
    
    # 메타데이터
    user_id: Optional[str] = Field(None, description="사용자 ID")
    context: Optional[str] = Field(None, description="측정 컨텍스트")
    notes: Optional[str] = Field(None, description="측정 메모")
    
    @field_validator('step_count')
    @classmethod
    def validate_measurement_data(cls, v, info):
        """측정 데이터 유효성 검증"""
        # frame_data나 voice_data 또는 step_count 중 하나는 있어야 함
        if info.data:
            frame_data = info.data.get('frame_data')
            voice_data = info.data.get('voice_data')
            step_count = info.data.get('step_count')
            
            if not frame_data and not voice_data and not step_count:
                raise ValueError("frame_data, voice_data, step_count 중 적어도 하나는 필요합니다")
        
        return v

class StepUpdateRequest(BaseModel):
    """보폭 업데이트 요청 모델 - FootstepUpdateRequest 개선"""
    step_length_cm: float = Field(
        ...,
        description="새로운 보폭 길이 (cm)",
        gt=20,
        lt=200
    )
    update_reason: Optional[str] = Field(
        None,
        description="업데이트 사유"
    )
    user_id: Optional[str] = Field(None, description="사용자 ID")

# ===== 결과 모델 =====

class StepCalculationResult(BaseModel):
    """표준화된 보폭 계산 결과 - StepResult, StepLengthResult 통합"""
    
    # 핵심 측정 결과
    step_length_cm: float = Field(
        description="계산된 보폭 길이 (cm)",
        gt=0
    )
    confidence: float = Field(
        description="측정 신뢰도 (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    step_count: int = Field(
        description="측정에 사용된 걸음 수",
        ge=0
    )
    
    # 품질 지표
    tracking_quality: StepTrackingQuality = Field(
        description="추적 품질 등급"
    )
    accuracy_level: AccuracyLevel = Field(
        description="한국어 정확도 수준"
    )
    
    # 측정 메타데이터
    measurement_method: StepMeasurementMethod = Field(
        description="사용된 측정 방식"
    )
    source_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="원본 측정 데이터"
    )
    
    # 통계 정보
    consistency_score: Optional[float] = Field(
        None,
        description="보폭 일관성 점수 (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    processing_time_ms: Optional[float] = Field(
        None,
        description="처리 시간 (밀리초)",
        ge=0.0
    )
    
    # 자동 계산 필드
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="계산 시각"
    )
    
    @field_validator('tracking_quality', mode='before')
    @classmethod
    def set_tracking_quality(cls, v, info):
        """신뢰도에 따른 추적 품질 자동 설정"""
        if v is None and info.data:
            confidence = info.data.get('confidence', 0.5)
            return AccuracyConverter.confidence_to_quality(confidence)
        return v
    
    @field_validator('accuracy_level', mode='before')
    @classmethod
    def set_accuracy_level(cls, v, info):
        """신뢰도에 따른 정확도 수준 자동 설정"""
        if v is None and info.data:
            confidence = info.data.get('confidence', 0.5)
            return AccuracyConverter.confidence_to_korean_level(confidence)
        return v

class StepValidationResult(BaseModel):
    """중앙화된 보폭 측정 검증 결과"""
    
    # 검증 결과
    is_valid: bool = Field(description="검증 통과 여부")
    overall_score: float = Field(
        description="종합 검증 점수 (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    
    # 세부 검증 항목
    distance_validation: Dict[str, Any] = Field(
        default_factory=dict,
        description="거리 검증 결과"
    )
    step_count_validation: Dict[str, Any] = Field(
        default_factory=dict,
        description="걸음 수 검증 결과"
    )
    step_length_validation: Dict[str, Any] = Field(
        default_factory=dict,
        description="보폭 길이 검증 결과"
    )
    
    # 경고 및 권장사항
    warnings: List[str] = Field(
        default_factory=list,
        description="검증 경고 목록"
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="개선 권장사항"
    )
    
    # 예측 결과
    predicted_accuracy: Optional[AccuracyLevel] = Field(
        None,
        description="예상 정확도 수준"
    )
    expected_step_length_cm: Optional[float] = Field(
        None,
        description="예상 보폭 길이 (cm)",
        gt=0
    )

# ===== 응답 모델 =====

class StepMeasurementResponse(BaseModel):
    """통합 보폭 측정 응답 모델 - FootstepDepthMeasurementResponse 대체"""
    
    # 기본 응답 정보
    success: bool = Field(description="측정 성공 여부")
    message: str = Field(description="응답 메시지")
    
    # 측정 결과
    result: Optional[StepCalculationResult] = Field(
        None,
        description="보폭 계산 결과"
    )
    validation: Optional[StepValidationResult] = Field(
        None,
        description="측정 검증 결과"
    )
    
    # 입력 데이터 에코
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="입력 데이터 요약"
    )
    
    # 메타데이터
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="응답 시각"
    )
    processing_info: Dict[str, Any] = Field(
        default_factory=dict,
        description="처리 정보"
    )

class StepSettingsResponse(BaseModel):
    """보폭 설정 조회 응답 모델"""
    
    # 현재 설정
    current_step_length_cm: Optional[float] = Field(
        None,
        description="현재 설정된 보폭 (cm)"
    )
    is_step_length_set: bool = Field(
        description="보폭 설정 여부"
    )
    
    # 사용자 정보
    user_name: Optional[str] = Field(None, description="사용자 이름")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    
    # 설정 이력
    last_updated: Optional[datetime] = Field(
        None,
        description="마지막 업데이트 시각"
    )
    update_count: int = Field(
        default=0,
        description="업데이트 횟수",
        ge=0
    )
    
    # 통계 정보
    measurement_history: Optional[Dict[str, Any]] = Field(
        None,
        description="측정 이력 요약"
    )

# ===== 실시간 추적 모델 =====

class RealTimeStepData(BaseModel):
    """실시간 보폭 추적 데이터"""
    
    # 현재 측정값
    current_step_length_cm: float = Field(description="현재 보폭 (cm)")
    step_count: int = Field(description="누적 걸음 수", ge=0)
    
    # 실시간 품질 지표
    left_foot_confidence: float = Field(
        description="왼발 추적 신뢰도",
        ge=0.0,
        le=1.0
    )
    right_foot_confidence: float = Field(
        description="오른발 추적 신뢰도", 
        ge=0.0,
        le=1.0
    )
    overall_tracking_quality: StepTrackingQuality = Field(
        description="전체 추적 품질"
    )
    
    # 성능 메트릭
    fps: float = Field(description="처리 속도 (FPS)", ge=0.0)
    frame_count: int = Field(description="처리된 프레임 수", ge=0)
    elapsed_time_seconds: float = Field(
        description="경과 시간 (초)",
        ge=0.0
    )
    
    # 일관성 지표
    step_consistency: float = Field(
        description="보폭 일관성 점수",
        ge=0.0,
        le=1.0
    )
    
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="데이터 생성 시각"
    )

# ===== 변환 유틸리티 메서드 =====

class StepModelConverter:
    """기존 데이터 구조와의 변환 유틸리티"""
    
    @staticmethod
    def from_legacy_footstep_request(
        distance_meters: float,
        step_count: int,
        user_id: Optional[str] = None
    ) -> StepMeasurementRequest:
        """기존 FootstepDepthMeasurementRequest에서 변환"""
        return StepMeasurementRequest(
            distance_meters=distance_meters,
            step_count=step_count,
            measurement_method=StepMeasurementMethod.DISTANCE_BASED,
            user_id=user_id,
            manual_step_length_cm=None,
            context=None,
            notes=None
        )
    
    @staticmethod
    def from_legacy_calculation_dict(
        calc_dict: Dict[str, Any],
        method: StepMeasurementMethod = StepMeasurementMethod.DISTANCE_BASED
    ) -> StepCalculationResult:
        """기존 계산 결과 딕셔너리에서 변환"""
        return StepCalculationResult(
            step_length_cm=calc_dict.get("step_length_cm", 0.0),
            confidence=AccuracyConverter.korean_level_to_confidence(
                AccuracyLevel(calc_dict.get("accuracy_level", "보통"))
            ),
            step_count=calc_dict.get("step_count", 0),
            tracking_quality=AccuracyConverter.confidence_to_quality(0.7),  # 기본값
            accuracy_level=AccuracyLevel(calc_dict.get("accuracy_level", "보통")),
            measurement_method=method,
            source_data=calc_dict,
            consistency_score=None,
            processing_time_ms=None
        )
    
    @staticmethod
    def to_legacy_response_dict(result: StepCalculationResult) -> Dict[str, Any]:
        """기존 응답 딕셔너리 형식으로 변환"""
        return {
            "step_length_cm": result.step_length_cm,
            "distance_meters": result.source_data.get("distance_meters"),
            "distance_cm": result.source_data.get("distance_cm"),
            "step_count": result.step_count,
            "accuracy_level": result.accuracy_level.value,
            "confidence": result.confidence,
            "tracking_quality": result.tracking_quality.value
        }

# ===== 검증 헬퍼 =====

def validate_step_measurement_inputs(
    distance_meters: Optional[float] = None,
    step_count: Optional[int] = None,
    method: StepMeasurementMethod = StepMeasurementMethod.DISTANCE_BASED
) -> StepValidationResult:
    """보폭 측정 입력값 검증"""
    warnings = []
    recommendations = []
    validations = {}
    
    # 거리 검증
    if distance_meters is not None:
        distance_valid = True
        if distance_meters < 1.0:
            warnings.append("측정 거리가 짧습니다 (1m 미만)")
            recommendations.append("더 긴 거리에서 측정하면 정확도가 향상됩니다")
            distance_valid = False
        elif distance_meters > 50.0:
            warnings.append("측정 거리가 매우 깁니다")
            recommendations.append("측정 정확도를 확인해주세요")
        
        validations["distance_validation"] = {
            "valid": distance_valid,
            "value": distance_meters,
            "range_check": "passed" if 1.0 <= distance_meters <= 50.0 else "failed"
        }
    
    # 걸음 수 검증
    if step_count is not None:
        step_valid = True
        if step_count < 5:
            warnings.append("걸음 수가 적습니다")
            recommendations.append("더 많은 걸음으로 측정하면 정확도가 향상됩니다")
            step_valid = False
        
        validations["step_count_validation"] = {
            "valid": step_valid,
            "value": step_count,
            "minimum_check": "passed" if step_count >= 5 else "failed"
        }
    
    # 예상 보폭 계산 및 검증 - 중앙화된 계산 로직 사용
    expected_step_length = None
    if distance_meters and step_count:
        expected_step_length = StepCalculationUtils.calculate_step_length_cm(distance_meters, step_count)
        
        step_length_valid = StepCalculationUtils.is_valid_step_length(expected_step_length)
        if not step_length_valid:
            if expected_step_length < 30:
                warnings.append("계산될 보폭이 너무 짧습니다")
            elif expected_step_length > 150:
                warnings.append("계산될 보폭이 너무 깁니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
        
        validations["step_length_validation"] = {
            "valid": step_length_valid,
            "expected_value": expected_step_length,
            "range_check": "passed" if 30 <= expected_step_length <= 150 else "failed"
        }
    
    # 종합 점수 계산
    valid_count = sum(1 for v in validations.values() if v.get("valid", True))
    total_count = len(validations) if validations else 1
    overall_score = valid_count / total_count
    
    return StepValidationResult(
        is_valid=len(warnings) == 0,
        overall_score=overall_score,
        distance_validation=validations.get("distance_validation", {}),
        step_count_validation=validations.get("step_count_validation", {}),
        step_length_validation=validations.get("step_length_validation", {}),
        warnings=warnings,
        recommendations=recommendations,
        predicted_accuracy=AccuracyConverter.confidence_to_korean_level(overall_score),
        expected_step_length_cm=expected_step_length
    )