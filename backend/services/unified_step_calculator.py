"""레거시 호환성을 위한 간소화된 Unified Step Calculator

이 파일은 새로운 IMU 통합 시스템으로 리다이렉트됩니다.
기존 API 호환성을 위해 최소한의 인터페이스만 유지합니다.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from models.step_models import (
    StepCalculationResult,
    StepMeasurementMethod,
    AccuracyConverter,
    StepTrackingQuality
)

logger = logging.getLogger(__name__)

@dataclass
class StepCalculationInput:
    """보폭 계산 입력 데이터 (레거시 호환성)"""
    # 단순 거리 기반 (주로 사용됨)
    distance_meters: Optional[float] = None
    step_count: Optional[int] = None
    
    # 설정
    preferred_method: StepMeasurementMethod = StepMeasurementMethod.DISTANCE_BASED
    force_fallback: bool = False
    
    # 레거시 호환성을 위해 유지 (사용되지 않음)
    frame_sequence: Optional[List[Dict[str, Any]]] = None
    left_foot_positions: Optional[List] = None
    right_foot_positions: Optional[List] = None

class UnifiedStepCalculator:
    """레거시 API 호환성을 위한 간소화된 계산기"""
    
    def __init__(self):
        self.processing_stats = {
            "total_calculations": 0,
            "successful_calculations": 0,
            "fallback_calculations": 0
        }
        
        logger.info("[UnifiedStepCalculator] 레거시 호환 모드로 초기화 - 새로운 IMU 시스템 사용")
    
    def calculate_step_length(self, input_data: StepCalculationInput) -> StepCalculationResult:
        """
        보폭 계산 (새로운 IMU 시스템 사용 또는 단순 계산)
        
        Args:
            input_data: 계산 입력 데이터
            
        Returns:
            StepCalculationResult: 계산 결과
        """
        start_time = time.time()
        
        try:
            self.processing_stats["total_calculations"] += 1
            
            # 거리 기반 단순 계산 (레거시 API 호환)
            if input_data.distance_meters and input_data.step_count:
                step_length_cm = (input_data.distance_meters / input_data.step_count) * 100
                
                # 신뢰도 계산
                confidence = self._calculate_confidence(
                    distance_meters=input_data.distance_meters,
                    step_count=input_data.step_count
                )
                
                result = StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=confidence,
                    step_count=input_data.step_count,
                    tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                    accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                    measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                    timestamp=time.time(),
                    user_id="unified_calculator_user",
                    source_data={
                        "method": "unified_calculator_legacy_compat",
                        "distance_meters": input_data.distance_meters,
                        "step_count": input_data.step_count,
                        "processing_time_ms": int((time.time() - start_time) * 1000)
                    }
                )
                
                self.processing_stats["successful_calculations"] += 1
                logger.debug(f"[UnifiedStepCalculator] 계산 완료: {step_length_cm:.1f}cm")
                return result
            
            # 입력 데이터 부족 시 응급 계산
            return self._emergency_calculation(input_data, "입력 데이터 부족")
            
        except Exception as e:
            logger.error(f"[UnifiedStepCalculator] 계산 오류: {e}")
            return self._emergency_calculation(input_data, str(e))
    
    def _calculate_confidence(self, distance_meters: float, step_count: int) -> float:
        """신뢰도 계산"""
        confidence = 0.5  # 기본 신뢰도
        
        # 거리가 길수록 신뢰도 증가
        if distance_meters >= 5.0:
            confidence += 0.2
        elif distance_meters >= 3.0:
            confidence += 0.1
        
        # 걸음 수가 많을수록 신뢰도 증가
        if step_count >= 20:
            confidence += 0.2
        elif step_count >= 10:
            confidence += 0.1
        
        return min(0.9, max(0.3, confidence))
    
    def _emergency_calculation(self, input_data: StepCalculationInput, error: str) -> StepCalculationResult:
        """응급 계산 (기본값 사용)"""
        self.processing_stats["fallback_calculations"] += 1
        
        logger.warning(f"[UnifiedStepCalculator] 응급 계산 실행: {error}")
        
        return StepCalculationResult(
            step_length_cm=65.0,  # 평균적인 보폭
            confidence=0.3,
            step_count=1,
            tracking_quality=StepTrackingQuality.LOW,
            accuracy_level=AccuracyConverter.confidence_to_korean_level(0.3),
            measurement_method=StepMeasurementMethod.DISTANCE_BASED,
            timestamp=time.time(),
            user_id="emergency_calculation",
            source_data={
                "method": "emergency_fallback",
                "error": error,
                "default_step_length": True
            }
        )
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        total = self.processing_stats["total_calculations"]
        if total > 0:
            success_rate = self.processing_stats["successful_calculations"] / total
            fallback_rate = self.processing_stats["fallback_calculations"] / total
        else:
            success_rate = 0.0
            fallback_rate = 0.0
        
        return {
            **self.processing_stats,
            "success_rate": round(success_rate, 3),
            "fallback_rate": round(fallback_rate, 3),
            "status": "legacy_compatibility_mode"
        }

# 싱글톤 인스턴스
_unified_calculator = None

def get_unified_step_calculator() -> UnifiedStepCalculator:
    """레거시 호환성을 위한 싱글톤 인스턴스 반환"""
    global _unified_calculator
    if _unified_calculator is None:
        _unified_calculator = UnifiedStepCalculator()
    return _unified_calculator

# 레거시 호환성을 위한 별칭
UnifiedCalculator = UnifiedStepCalculator
get_calculator = get_unified_step_calculator