"""보폭 측정 시스템 공통 베이스 클래스 및 유틸리티
시각장애인 특화 신뢰도/평균 보폭 조정 로직 통합
"""

import logging
from typing import Dict, Optional, Tuple, Any, TYPE_CHECKING
from collections import deque
from dataclasses import dataclass
import math

if TYPE_CHECKING:
    from models.step_models import StepCalculationResult

logger = logging.getLogger(__name__)

@dataclass
class StepMeasurementConfig:
    """보폭 측정 시스템 공통 설정 (시각장애인 특화)"""
    # 신뢰도 조정 계수
    base_confidence_threshold: float = 0.4  # 시각장애인을 위해 낮춘 기본 임계값
    stability_weight: float = 0.3          # 보폭 안정성 가중치
    sensor_agreement_weight: float = 0.2   # 센서 일치도 가중치
    baseline_weight: float = 0.5           # 기준 신뢰도 가중치
    
    # 시각장애인 특화 보정
    visual_impairment_confidence_boost: float = 0.1  # 시각장애인 신뢰도 보너스
    walking_pattern_bonus: float = 0.15              # 일정한 걸음 패턴 보너스
    consistency_threshold: float = 0.7               # 일관성 임계값
    
    # 평균 보폭 관리
    recent_steps_buffer_size: int = 10      # 최근 보폭 버퍼 크기
    outlier_std_multiplier: float = 2.0     # 이상치 제거를 위한 표준편차 배수
    min_confidence_for_average: float = 0.6 # 평균 계산에 포함할 최소 신뢰도
    
    # 보폭 범위 (성인 기준, 시각장애인 고려)
    min_step_length_cm: float = 30.0        # 최소 보폭 (cm)
    max_step_length_cm: float = 150.0       # 최대 보폭 (cm)
    typical_step_length_cm: float = 65.0    # 일반적인 성인 보폭 (cm)
    
    # 신뢰도 임계값 (시각장애인 특화)
    excellent_confidence: float = 0.85      # 우수 신뢰도
    good_confidence: float = 0.7            # 양호 신뢰도  
    acceptable_confidence: float = 0.5      # 허용 가능 신뢰도
    poor_confidence: float = 0.3            # 낮은 신뢰도

class StepMeasurementBase:
    """보폭 측정 시스템 공통 베이스 클래스"""
    
    def __init__(self, config: Optional[StepMeasurementConfig] = None):
        self.config = config or StepMeasurementConfig()
        self.recent_steps = deque(maxlen=self.config.recent_steps_buffer_size)  # (step_length_cm, confidence)
        
        # 시각장애인 특화 상태 추적
        self.walking_pattern_stability = 0.8  # 걸음 패턴 안정성
        self.sensor_fusion_quality = 0.7      # 센서 융합 품질
        
        # 통계
        self.measurement_stats = {
            'total_measurements': 0,
            'successful_measurements': 0,
            'average_confidence': 0.0,
            'consistency_score': 0.0
        }
        
        logger.info(f"[보폭측정베이스] 초기화 완료 - 시각장애인 특화 설정 적용")
    
    def calculate_adjusted_confidence(
        self, 
        base_confidence: float, 
        step_stability: float = 1.0, 
        sensor_agreement: float = 1.0,
        is_walking_detected: bool = False,
        consistency_with_average: float = 1.0
    ) -> float:
        """
        시각장애인 특화 신뢰도 조정 계산
        
        Args:
            base_confidence: 기본 측정 신뢰도 (0.0-1.0)
            step_stability: 보폭 안정성 점수 (0.0-1.0)
            sensor_agreement: 센서 일치도 점수 (0.0-1.0)
            is_walking_detected: 걷기 패턴 감지 여부
            consistency_with_average: 평균 보폭과의 일관성 (0.0-1.0)
            
        Returns:
            float: 조정된 신뢰도 (0.0-1.0)
        """
        try:
            # 기본 신뢰도 가중 평균
            adjusted_confidence = (
                self.config.baseline_weight * base_confidence +
                self.config.stability_weight * step_stability +
                self.config.sensor_agreement_weight * sensor_agreement
            )
            
            # 시각장애인 특화 보정
            if base_confidence >= self.config.base_confidence_threshold:
                adjusted_confidence += self.config.visual_impairment_confidence_boost
            
            # 일정한 걸음 패턴 보너스
            if is_walking_detected and step_stability >= self.config.consistency_threshold:
                adjusted_confidence += self.config.walking_pattern_bonus
                logger.debug(f"[신뢰도조정] 일정한 걸음 패턴 보너스 적용: +{self.config.walking_pattern_bonus:.3f}")
            
            # 평균 보폭과의 일관성 반영
            adjusted_confidence *= consistency_with_average
            
            # 범위 제한 (0.0-1.0)
            adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))
            
            logger.debug(f"[신뢰도조정] {base_confidence:.3f} → {adjusted_confidence:.3f} "
                        f"(안정성: {step_stability:.3f}, 센서일치: {sensor_agreement:.3f}, 일관성: {consistency_with_average:.3f})")
            
            return float(adjusted_confidence)
            
        except Exception as e:
            logger.error(f"[신뢰도조정] 계산 오류: {e}")
            return float(max(0.3, base_confidence))  # 안전한 기본값 반환
    
    def update_step_history(self, step_length_cm: float, confidence: float):
        """보폭 측정 히스토리 업데이트"""
        try:
            # 범위 검증
            if not (self.config.min_step_length_cm <= step_length_cm <= self.config.max_step_length_cm):
                logger.warning(f"[히스토리] 보폭 범위 초과: {step_length_cm:.1f}cm")
                return
            
            if not (0.0 <= confidence <= 1.0):
                logger.warning(f"[히스토리] 신뢰도 범위 초과: {confidence:.3f}")
                return
                
            self.recent_steps.append((step_length_cm, confidence))
            
            # 통계 업데이트
            self.measurement_stats['total_measurements'] += 1
            if confidence >= self.config.acceptable_confidence:
                self.measurement_stats['successful_measurements'] += 1
            
            # 평균 신뢰도 업데이트
            total = self.measurement_stats['total_measurements']
            current_avg = self.measurement_stats['average_confidence']
            self.measurement_stats['average_confidence'] = (
                (current_avg * (total - 1) + confidence) / total
            )
            
            logger.debug(f"[히스토리] 업데이트: {step_length_cm:.1f}cm (신뢰도: {confidence:.3f})")
            
        except Exception as e:
            logger.error(f"[히스토리] 업데이트 오류: {e}")
    
    def get_average_step_length(self, min_confidence: Optional[float] = None) -> float:
        """
        신뢰할 수 있는 평균 보폭 계산 (이상치 제거 포함)
        
        Args:
            min_confidence: 최소 신뢰도 임계값 (None이면 설정값 사용)
            
        Returns:
            float: 평균 보폭 (cm), 데이터 부족 시 0.0
        """
        try:
            min_conf = min_confidence or self.config.min_confidence_for_average
            
            # 신뢰도 필터링
            filtered_steps = [
                step_length for step_length, conf in self.recent_steps 
                if conf >= min_conf
            ]
            
            if len(filtered_steps) < 2:
                return 0.0
            
            # 1차 평균 및 표준편차 계산
            mean = sum(filtered_steps) / len(filtered_steps)
            variance = sum((x - mean) ** 2 for x in filtered_steps) / len(filtered_steps)
            std_dev = math.sqrt(variance)
            
            # 이상치 제거 (2-sigma 규칙)
            outlier_threshold = self.config.outlier_std_multiplier * std_dev
            filtered_steps_no_outliers = [
                x for x in filtered_steps 
                if abs(x - mean) <= outlier_threshold
            ]
            
            # 이상치 제거 후 재계산
            if len(filtered_steps_no_outliers) >= 2:
                final_average = sum(filtered_steps_no_outliers) / len(filtered_steps_no_outliers)
                logger.debug(f"[평균보폭] {len(filtered_steps)} → {len(filtered_steps_no_outliers)}개 데이터, 평균: {final_average:.1f}cm")
                return float(final_average)
            
            # 이상치 제거 후 데이터가 부족하면 원래 평균 반환
            return float(mean)
            
        except Exception as e:
            logger.error(f"[평균보폭] 계산 오류: {e}")
            return 0.0
    
    def calculate_consistency_score(self, current_step_length_cm: float) -> float:
        """
        현재 보폭과 평균 보폭 간의 일관성 점수 계산
        
        Args:
            current_step_length_cm: 현재 측정된 보폭 (cm)
            
        Returns:
            float: 일관성 점수 (0.0-1.0), 평균이 없으면 1.0
        """
        try:
            avg_step = self.get_average_step_length()
            
            if avg_step <= 0:
                return 1.0  # 비교할 평균이 없으면 최대 점수
            
            # 절대 차이를 상대적 비율로 변환
            diff_ratio = abs(current_step_length_cm - avg_step) / avg_step
            
            # 차이가 클수록 일관성 점수 감소 (지수적 감소)
            consistency_score = math.exp(-3 * diff_ratio)  # 3은 감쇠 계수
            
            logger.debug(f"[일관성] 현재: {current_step_length_cm:.1f}cm, 평균: {avg_step:.1f}cm, "
                        f"차이비율: {diff_ratio:.3f}, 일관성: {consistency_score:.3f}")
            
            return float(max(0.0, min(1.0, consistency_score)))
            
        except Exception as e:
            logger.error(f"[일관성] 계산 오류: {e}")
            return 1.0
    
    def validate_step_length(self, step_length_cm: float) -> Tuple[bool, str]:
        """
        보폭 길이 유효성 검증
        
        Args:
            step_length_cm: 검증할 보폭 (cm)
            
        Returns:
            Tuple[bool, str]: (유효성, 메시지)
        """
        try:
            if step_length_cm < self.config.min_step_length_cm:
                return False, f"보폭이 너무 짧습니다 ({step_length_cm:.1f}cm < {self.config.min_step_length_cm}cm)"
            
            if step_length_cm > self.config.max_step_length_cm:
                return False, f"보폭이 너무 깁니다 ({step_length_cm:.1f}cm > {self.config.max_step_length_cm}cm)"
            
            # 극단적인 값 경고
            if step_length_cm < 40 or step_length_cm > 120:
                return True, f"보폭이 일반적 범위를 벗어납니다 ({step_length_cm:.1f}cm)"
            
            return True, "정상 범위의 보폭입니다"
            
        except Exception as e:
            logger.error(f"[보폭검증] 오류: {e}")
            return False, f"검증 중 오류 발생: {str(e)}"
    
    # get_confidence_level_description 메서드는 사용되지 않으므로 제거됨
    
    # update_walking_pattern_stability 메서드는 사용되지 않으므로 제거됨
    
    def create_fallback_step_result(
        self, 
        reason: str = "vision_processing_failed",
        estimated_distance_cm: Optional[float] = None,
        estimated_step_count: Optional[int] = None,
        user_counted_steps: Optional[int] = None,
        standard_distance_cm: float = 1000.0  # 10m 표준 거리
    ) -> 'StepCalculationResult':
        """
        시각장애인을 위한 보폭 측정 실패 시 대체 결과 생성
        개선: 10m 표준 거리 + 사용자 음성 입력 걸음수로 정확한 보폭 계산
        
        Args:
            reason: 실패 사유
            estimated_distance_cm: 추정 거리 (cm) - 레거시 지원
            estimated_step_count: 추정 걸음 수 - 레거시 지원
            user_counted_steps: 사용자가 음성으로 입력한 실제 걸음 수
            standard_distance_cm: 표준 측정 거리 (기본값: 10m = 1000cm)
            
        Returns:
            StepCalculationResult: 대체 측정 결과
        """
        try:
            from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyLevel, StepTrackingQuality
            
            # 우선순위 1: 사용자가 직접 센 걸음수 + 10m 표준거리 (가장 정확)
            if user_counted_steps and user_counted_steps > 0:
                calculated_step_length = standard_distance_cm / user_counted_steps
                
                # 10m/걸음수 계산 결과가 합리적인 범위인지 확인
                if self.config.min_step_length_cm <= calculated_step_length <= self.config.max_step_length_cm:
                    fallback_step_length = calculated_step_length
                    fallback_confidence = 0.85  # 사용자 직접 계수 + 표준거리 = 높은 신뢰도
                    method = StepMeasurementMethod.DISTANCE_BASED
                    accuracy_level = AccuracyLevel.HIGH
                    tracking_quality = StepTrackingQuality.GOOD
                    source_info = {
                        "fallback_type": "user_counted_10m_measurement",
                        "original_failure_reason": reason,
                        "standard_distance_cm": standard_distance_cm,
                        "user_counted_steps": user_counted_steps,
                        "calculated_step_length_cm": calculated_step_length,
                        "measurement_method": "10m_standard_distance_with_user_count"
                    }
                    logger.info(f"[개선측정] 10m 표준거리 + 사용자 걸음수({user_counted_steps}) = {calculated_step_length:.1f}cm")
                else:
                    # 사용자가 센 걸음수로 계산했지만 결과가 비현실적
                    logger.warning(f"[개선측정] 사용자 걸음수({user_counted_steps})로 계산한 보폭({calculated_step_length:.1f}cm)이 비현실적")
                    # 다음 우선순위로 진행
                    user_counted_steps = None
            
            if user_counted_steps is None:
                # 우선순위 2: 레거시 거리/걸음 추정값
                if estimated_distance_cm and estimated_step_count and estimated_step_count > 0:
                    calculated_step_length = estimated_distance_cm / estimated_step_count
                    
                    # 계산 결과가 합리적인 범위면 사용
                    if self.config.min_step_length_cm <= calculated_step_length <= self.config.max_step_length_cm:
                        fallback_step_length = calculated_step_length
                        fallback_confidence = 0.6  # 추정 기반이므로 중간 신뢰도
                        method = StepMeasurementMethod.DISTANCE_BASED
                        accuracy_level = AccuracyLevel.MEDIUM
                        tracking_quality = StepTrackingQuality.FAIR
                        source_info = {
                            "fallback_type": "estimated_distance_calculation",
                            "original_failure_reason": reason,
                            "estimated_distance_cm": estimated_distance_cm,
                            "estimated_step_count": estimated_step_count,
                            "calculated_step_length_cm": calculated_step_length
                        }
                    else:
                        # 계산 결과가 비합리적이면 평균/표준 사용
                        fallback_step_length = self.get_average_step_length()
                        if fallback_step_length <= 0:
                            fallback_step_length = self.config.typical_step_length_cm
                        fallback_confidence = 0.4
                        method = StepMeasurementMethod.MANUAL_INPUT
                        accuracy_level = AccuracyLevel.LOW
                        tracking_quality = StepTrackingQuality.POOR
                        source_info = {
                            "fallback_type": "average_or_standard",
                            "original_failure_reason": reason,
                            "unreliable_calculation": calculated_step_length,
                            "used_average_step_length": self.get_average_step_length() > 0
                        }
                else:
                    # 우선순위 3: 평균 또는 표준값 사용
                    fallback_step_length = self.get_average_step_length()
                    if fallback_step_length <= 0:
                        fallback_step_length = self.config.typical_step_length_cm
                    fallback_confidence = 0.45 if self.get_average_step_length() > 0 else 0.35
                    method = StepMeasurementMethod.MANUAL_INPUT
                    accuracy_level = AccuracyLevel.LOW
                    tracking_quality = StepTrackingQuality.POOR
                    source_info = {
                        "fallback_type": "average_or_standard",
                        "original_failure_reason": reason,
                        "used_average_step_length": self.get_average_step_length() > 0
                    }
            
            # 시각장애인 특화 보정 적용
            if fallback_confidence >= self.config.acceptable_confidence:
                fallback_confidence += self.config.visual_impairment_confidence_boost
                source_info["visual_impairment_confidence_boost"] = self.config.visual_impairment_confidence_boost
            
            fallback_confidence = self.clamp_confidence(fallback_confidence)
            
            result = StepCalculationResult(
                step_length_cm=round(fallback_step_length, 1),
                confidence=round(fallback_confidence, 3),
                step_count=estimated_step_count or 1,
                tracking_quality=tracking_quality,
                accuracy_level=accuracy_level,
                measurement_method=method,
                consistency_score=0.8 if self.get_average_step_length() > 0 else 0.5,
                processing_time_ms=None,
                source_data={
                    "method": "visual_impairment_fallback",
                    "fallback_step_length_cm": fallback_step_length,
                    "typical_step_length_cm": self.config.typical_step_length_cm,
                    "average_available": self.get_average_step_length() > 0,
                    "recent_measurements_count": len(self.recent_steps),
                    **source_info
                }
            )
            
            # 히스토리에 추가 (낮은 신뢰도이지만 기록)
            self.update_step_history(result.step_length_cm, result.confidence)
            
            logger.info(f"[대체측정] 생성됨: {result.step_length_cm:.1f}cm (신뢰도: {result.confidence:.3f}, 사유: {reason})")
            return result
            
        except Exception as e:
            logger.error(f"[대체측정] 생성 오류: {e}")
            # 최소한의 안전한 결과 반환
            from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyLevel, StepTrackingQuality
            return StepCalculationResult(
                step_length_cm=65.0,  # 성인 표준
                confidence=0.3,
                step_count=1,
                tracking_quality=StepTrackingQuality.POOR,
                accuracy_level=AccuracyLevel.LOW,
                measurement_method=StepMeasurementMethod.MANUAL_INPUT,
                consistency_score=0.5,
                processing_time_ms=None,
                source_data={"method": "emergency_fallback", "error": str(e)}
            )
    
    def clamp_confidence(self, confidence: float) -> float:
        """신뢰도를 0.0-1.0 범위로 제한"""
        return max(0.0, min(1.0, confidence))

    # get_measurement_statistics 메서드는 사용되지 않으므로 제거됨
    
    def reset_statistics(self):
        """통계 초기화"""
        self.measurement_stats = {
            'total_measurements': 0,
            'successful_measurements': 0,
            'average_confidence': 0.0,
            'consistency_score': 0.0
        }
        self.recent_steps.clear()
        self.walking_pattern_stability = 0.8
        self.sensor_fusion_quality = 0.7
        logger.info("[통계] 측정 통계 초기화 완료")


class StepMeasurementUtils:
    """보폭 측정 관련 유틸리티 함수들 - 베이스 클래스 메서드와 중복 제거"""
    
    @staticmethod
    def clamp_step_length(step_length_cm: float, min_cm: float = 30.0, max_cm: float = 150.0) -> float:
        """보폭을 안전한 범위로 제한"""
        return max(min_cm, min(max_cm, step_length_cm))
    
    # calculate_3d_distance와 safe_divide 메서드는 사용되지 않으므로 제거됨

# 전역 유틸리티 함수들 (하위 호환성)
def create_measurement_base(config: Optional[StepMeasurementConfig] = None) -> StepMeasurementBase:
    """측정 베이스 인스턴스 생성"""
    return StepMeasurementBase(config)

def get_default_config() -> StepMeasurementConfig:
    """기본 설정 반환"""
    return StepMeasurementConfig()

# 시각장애인 특화 설정
def get_visual_impairment_config() -> StepMeasurementConfig:
    """시각장애인 특화 설정 반환"""
    config = StepMeasurementConfig()
    # 더 관대한 신뢰도 설정
    config.base_confidence_threshold = 0.3
    config.visual_impairment_confidence_boost = 0.15
    config.walking_pattern_bonus = 0.2
    config.acceptable_confidence = 0.4
    config.min_confidence_for_average = 0.5
    return config