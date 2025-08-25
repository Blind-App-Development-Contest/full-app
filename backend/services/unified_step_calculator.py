"""통합 보폭 계산 서비스 - Kalman 필터 + FastDepth 기반

중복된 보폭 계산 알고리즘을 제거하고 Kalman 필터를 중심으로 통합합니다:
- services/kalman_step_filter.py의 실시간 추적
- utils/fastdepth_processor.py의 프레임 기반 계산
- api/footstep.py의 단순 계산 (응급 대안으로만)
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
from services.kalman_step_filter import RealTimeStepTracker, FootPosition
from utils.fastdepth_processor import FastDepthProcessor

logger = logging.getLogger(__name__)

@dataclass
class StepCalculationInput:
    """보폭 계산 입력 데이터"""
    # FastDepth 프레임 기반
    frame_sequence: Optional[List[Dict[str, Any]]] = None
    
    # 실시간 추적 기반
    left_foot_positions: Optional[List[FootPosition]] = None
    right_foot_positions: Optional[List[FootPosition]] = None
    
    # 단순 거리 기반 (응급 대안)
    distance_meters: Optional[float] = None
    step_count: Optional[int] = None
    
    # 설정
    preferred_method: StepMeasurementMethod = StepMeasurementMethod.KALMAN_FILTER
    force_fallback: bool = False

class UnifiedStepCalculator:
    """통합 보폭 계산기 - 중복 알고리즘 제거 및 Kalman 중심 통합"""
    
    def __init__(self):
        # 핵심 구성 요소
        self.kalman_tracker = RealTimeStepTracker()
        self.fastdepth_processor = FastDepthProcessor()
        
        # 성능 추적
        self.calculation_stats = {
            "total_calculations": 0,
            "kalman_success": 0,
            "fastdepth_success": 0,
            "fallback_used": 0,
            "average_processing_time": 0.0
        }
        
        # 설정
        self.min_frames_for_kalman = 5
        self.min_confidence_threshold = 0.3
    
    def reset_for_new_measurement(self):
        """새로운 측정을 위한 상태 완전 초기화"""
        logger.info("[UnifiedStepCalculator] 새로운 측정을 위한 상태 초기화")
        
        # Kalman tracker 완전 초기화
        self.kalman_tracker = RealTimeStepTracker()
        
        # FastDepth processor 초기화
        self.fastdepth_processor = FastDepthProcessor()
        
        # 통계는 유지하되 현재 측정 관련 데이터는 초기화
        logger.info("[UnifiedStepCalculator] 상태 초기화 완료")
        
    
    def calculate_step_length(self, input_data: StepCalculationInput) -> StepCalculationResult:
        """
        통합 보폭 계산 - 최적의 방법을 자동 선택
        
        우선순위:
        1. Kalman 필터 실시간 추적 (가장 정확)
        2. FastDepth 프레임 시퀀스 분석 (높은 정확도)  
        3. 단순 거리 계산 (응급 대안)
        
        Args:
            input_data: 계산 입력 데이터
            
        Returns:
            StepCalculationResult: 통합 계산 결과
        """
        start_time = time.time()
        self.calculation_stats["total_calculations"] += 1
        
        try:
            # 강제 대안 사용 요청
            if input_data.force_fallback:
                logger.warning("[UnifiedStepCalculator] 강제 대안 모드 사용")
                return self._calculate_simple_fallback(input_data)
            
            # 1. Kalman 필터 실시간 추적 시도
            if self._can_use_kalman_tracking(input_data):
                result = self._calculate_with_kalman_tracking(input_data)
                if self._is_result_reliable(result):
                    self.calculation_stats["kalman_success"] += 1
                    return self._finalize_result(result, start_time, "kalman_tracking")
            
            # 2. FastDepth 프레임 시퀀스 분석 시도
            if self._can_use_fastdepth_analysis(input_data):
                result = self._calculate_with_fastdepth_analysis(input_data)
                if self._is_result_reliable(result):
                    self.calculation_stats["fastdepth_success"] += 1
                    return self._finalize_result(result, start_time, "fastdepth_analysis")
            
            # 3. 단순 거리 계산 (응급 대안)
            logger.warning("[UnifiedStepCalculator] 고급 방법 실패 - 단순 계산 사용")
            self.calculation_stats["fallback_used"] += 1
            result = self._calculate_simple_fallback(input_data)
            return self._finalize_result(result, start_time, "simple_fallback")
            
        except Exception as e:
            logger.error(f"[UnifiedStepCalculator] 계산 실패: {e}")
            # 최후의 응급 계산
            return self._emergency_calculation(input_data, str(e))
    
    def _can_use_kalman_tracking(self, input_data: StepCalculationInput) -> bool:
        """Kalman 추적 사용 가능 여부 확인"""
        return (
            input_data.left_foot_positions is not None or 
            input_data.right_foot_positions is not None
        ) and not input_data.force_fallback
    
    def _can_use_fastdepth_analysis(self, input_data: StepCalculationInput) -> bool:
        """FastDepth 분석 사용 가능 여부 확인"""
        return (
            input_data.frame_sequence is not None and 
            len(input_data.frame_sequence) >= self.min_frames_for_kalman
        ) and not input_data.force_fallback
    
    def _calculate_with_kalman_tracking(self, input_data: StepCalculationInput) -> StepCalculationResult:
        """Kalman 필터 실시간 추적 계산"""
        # 왼발 데이터 처리
        if input_data.left_foot_positions:
            for pos in input_data.left_foot_positions:
                self.kalman_tracker.add_foot_measurement("left", pos)
        
        # 오른발 데이터 처리
        if input_data.right_foot_positions:
            for pos in input_data.right_foot_positions:
                self.kalman_tracker.add_foot_measurement("right", pos)
        
        # 현재 결과 가져오기
        step_result = self.kalman_tracker.get_current_step_result()
        
        # 성능 메트릭 가져오기
        performance = self.kalman_tracker.get_performance_metrics()
        
        return StepCalculationResult(
            step_length_cm=step_result.step_length_cm,
            confidence=step_result.confidence,
            step_count=step_result.step_count,
            tracking_quality=step_result.tracking_quality,
            accuracy_level=AccuracyConverter.confidence_to_korean_level(step_result.confidence),
            measurement_method=StepMeasurementMethod.KALMAN_FILTER,
            source_data={
                "method": "kalman_tracking",
                "performance_metrics": performance,
                "left_positions_count": len(input_data.left_foot_positions or []),
                "right_positions_count": len(input_data.right_foot_positions or []),
                "tracking_quality_raw": step_result.tracking_quality.value
            },
            consistency_score=performance.get("step_consistency", 0.0)
        )
    
    def _calculate_with_fastdepth_analysis(self, input_data: StepCalculationInput) -> StepCalculationResult:
        """FastDepth 프레임 시퀀스 분석 계산"""
        # FastDepth 프로세서를 통한 계산 (Kalman 방법 우선)
        result = self.fastdepth_processor.postprocess_for_step_calculation(
            input_data.frame_sequence,
            measurement_method="kalman_filter"
        )
        
        # 결과가 신뢰할 수 없으면 단순 방법으로 재시도
        if result.confidence < self.min_confidence_threshold:
            logger.warning("[UnifiedStepCalculator] FastDepth Kalman 신뢰도 낮음 - 단순 방법 재시도")
            result = self.fastdepth_processor.postprocess_for_step_calculation(
                input_data.frame_sequence,
                measurement_method="simple_distance"
            )
        
        return result
    
    def _calculate_simple_fallback(self, input_data: StepCalculationInput) -> StepCalculationResult:
        """단순 거리 기반 계산 (응급 대안)"""
        if not input_data.distance_meters or not input_data.step_count:
            raise ValueError("단순 계산을 위해서는 distance_meters와 step_count가 필요합니다")
        
        # 기본 계산
        distance_cm = input_data.distance_meters * 100
        step_length_cm = distance_cm / input_data.step_count
        
        # 신뢰도 계산 (단순 방법이므로 낮음)
        confidence = self._calculate_simple_confidence(
            input_data.distance_meters, 
            input_data.step_count, 
            step_length_cm
        )
        
        return StepCalculationResult(
            step_length_cm=round(step_length_cm, 1),
            confidence=confidence,
            step_count=input_data.step_count,
            tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
            accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
            measurement_method=StepMeasurementMethod.DISTANCE_BASED,
            source_data={
                "method": "simple_fallback",
                "distance_meters": input_data.distance_meters,
                "distance_cm": distance_cm,
                "calculation_type": "emergency_fallback"
            }
        )
    
    def _calculate_simple_confidence(
        self, 
        distance_meters: float, 
        step_count: int, 
        step_length_cm: float
    ) -> float:
        """단순 계산의 신뢰도 추정"""
        # 거리 기준 점수 (긴 거리일수록 정확)
        distance_score = min(distance_meters / 5.0, 1.0)
        
        # 걸음 수 기준 점수 (많은 걸음일수록 정확)
        step_score = min(step_count / 30.0, 1.0)
        
        # 보폭 합리성 점수 (일반적인 범위: 50-90cm)
        if 50 <= step_length_cm <= 90:
            step_length_score = 1.0
        elif 40 <= step_length_cm <= 100:
            step_length_score = 0.7
        else:
            step_length_score = 0.3
        
        # 가중 평균 (단순 방법이므로 최대 0.7로 제한)
        confidence = (distance_score * 0.4 + step_score * 0.3 + step_length_score * 0.3)
        return min(confidence * 0.7, 0.7)  # 단순 방법 제한
    
    def _is_result_reliable(self, result: StepCalculationResult) -> bool:
        """계산 결과의 신뢰성 확인"""
        return (
            result.confidence >= self.min_confidence_threshold and
            30 <= result.step_length_cm <= 150 and
            result.step_count > 0
        )
    
    def _finalize_result(
        self, 
        result: StepCalculationResult, 
        start_time: float, 
        method: str
    ) -> StepCalculationResult:
        """결과 최종화 - 처리 시간 및 메타데이터 추가"""
        processing_time = (time.time() - start_time) * 1000  # ms
        
        # 통계 업데이트
        total = self.calculation_stats["total_calculations"]
        current_avg = self.calculation_stats["average_processing_time"]
        self.calculation_stats["average_processing_time"] = (
            (current_avg * (total - 1) + processing_time) / total
        )
        
        # 결과에 처리 정보 추가
        updated_source_data = result.source_data.copy()
        updated_source_data.update({
            "unified_calculator_method": method,
            "processing_time_ms": processing_time,
            "calculation_timestamp": time.time()
        })
        
        return result.model_copy(update={
            "processing_time_ms": processing_time,
            "source_data": updated_source_data
        })
    
    def _emergency_calculation(self, input_data: StepCalculationInput, error: str) -> StepCalculationResult:
        """최후의 응급 계산"""
        logger.error(f"[UnifiedStepCalculator] 응급 계산 실행: {error}")
        
        # 기본값으로 계산
        distance = input_data.distance_meters or 2.0
        steps = input_data.step_count or 30
        step_length = (distance * 100) / steps
        
        return StepCalculationResult(
            step_length_cm=round(step_length, 1),
            confidence=0.1,  # 매우 낮은 신뢰도
            step_count=steps,
            tracking_quality=StepTrackingQuality.POOR,
            accuracy_level=AccuracyConverter.confidence_to_korean_level(0.1),
            measurement_method=StepMeasurementMethod.DISTANCE_BASED,
            source_data={
                "method": "emergency_calculation",
                "error": error,
                "warning": "모든 계산 방법 실패 - 응급 기본값 사용"
            }
        )
    

# 싱글톤 인스턴스
_unified_calculator = None

def get_unified_step_calculator() -> UnifiedStepCalculator:
    """통합 보폭 계산기 싱글톤 인스턴스 반환"""
    global _unified_calculator
    if _unified_calculator is None:
        _unified_calculator = UnifiedStepCalculator()
    return _unified_calculator