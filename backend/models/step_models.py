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
    DISTANCE_BASED = "distance_based"      # 거리/걸음수 기반 (FastDepth)
    KALMAN_FILTER = "kalman_filter"        # 칼만 필터 실시간 추적
    MANUAL_INPUT = "manual_input"          # 수동 입력
    HYBRID = "hybrid"                      # 복합 방식

class AccuracyLevel(str, Enum):
    """정확도 수준 - 기존 한국어 문자열 표준화"""
    HIGH = "높음"    # 높은 정확도
    MEDIUM = "보통"  # 보통 정확도 
    LOW = "낮음"     # 낮은 정확도

# ===== 유틸리티 클래스 =====

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

# ===== 요청 모델 =====

class StepMeasurementRequest(BaseModel):
    """통합 보폭 측정 요청 모델 - FootstepDepthMeasurementRequest 대체"""
    
    # 기본 측정 데이터
    distance_meters: Optional[float] = Field(
        None,
        description="측정된 거리 (미터)",
        gt=0.1,  # 최소 10cm
        le=100.0,  # 최대 100미터
        example=3.0
    )
    step_count: Optional[int] = Field(
        None,
        description="걸음 수",
        gt=0,
        le=1000,
        example=45
    )
    
    # 측정 방식 및 설정
    measurement_method: StepMeasurementMethod = Field(
        StepMeasurementMethod.DISTANCE_BASED,
        description="측정 방식"
    )
    manual_step_length_cm: Optional[float] = Field(
        None,
        description="수동 입력 보폭 (cm)",
        gt=20,
        lt=200,
        example=65.5
    )
    
    # 메타데이터
    user_id: Optional[str] = Field(None, description="사용자 ID")
    context: Optional[str] = Field(None, description="측정 컨텍스트")
    notes: Optional[str] = Field(None, description="측정 메모")
    
    @field_validator('distance_meters', 'step_count')
    @classmethod
    def validate_measurement_data(cls, v, info):
        """측정 데이터 유효성 검증"""
        # Pydantic v2에서는 info.data로 다른 필드 접근
        if info.data:
            method = info.data.get('measurement_method')
            field_name = info.field_name
            
            if method == StepMeasurementMethod.DISTANCE_BASED:
                if field_name == 'distance_meters' and v is None:
                    raise ValueError("거리 기반 측정에는 distance_meters가 필요합니다")
                if field_name == 'step_count' and v is None:
                    raise ValueError("거리 기반 측정에는 step_count가 필요합니다")
        
        return v

class StepUpdateRequest(BaseModel):
    """보폭 업데이트 요청 모델 - FootstepUpdateRequest 개선"""
    step_length_cm: float = Field(
        ...,
        description="새로운 보폭 길이 (cm)",
        gt=20,
        lt=200,
        example=65.5
    )
    update_reason: Optional[str] = Field(
        None,
        description="업데이트 사유",
        example="수동 조정"
    )
    user_id: Optional[str] = Field(None, description="사용자 ID")

# ===== 결과 모델 =====

class StepCalculationResult(BaseModel):
    """표준화된 보폭 계산 결과 - StepResult, StepLengthResult 통합"""
    
    # 핵심 측정 결과
    step_length_cm: float = Field(
        description="계산된 보폭 길이 (cm)",
        gt=0,
        example=65.5
    )
    confidence: float = Field(
        description="측정 신뢰도 (0.0-1.0)",
        ge=0.0,
        le=1.0,
        example=0.85
    )
    step_count: int = Field(
        description="측정에 사용된 걸음 수",
        ge=0,
        example=45
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
            user_id=user_id
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
            source_data=calc_dict
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
    
    # 예상 보폭 계산 및 검증 - UnifiedStepCalculator 사용
    expected_step_length = None
    if distance_meters and step_count:
        from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
        
        calculator = get_unified_step_calculator()
        input_data = StepCalculationInput(
            distance_meters=distance_meters,
            step_count=step_count,
            preferred_method=StepMeasurementMethod.DISTANCE_BASED,
            force_fallback=True  # 검증용 계산이므로 단순 계산 사용
        )
        
        result = calculator.calculate_step_length(input_data)
        expected_step_length = result.step_length_cm
        
        step_length_valid = True
        if expected_step_length < 30:
            warnings.append("계산될 보폭이 너무 짧습니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
            step_length_valid = False
        elif expected_step_length > 150:
            warnings.append("계산될 보폭이 너무 깁니다") 
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
            step_length_valid = False
        
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