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
    """보폭 측정 설정"""
    min_step_length_cm: float = 30.0
    max_step_length_cm: float = 150.0
    default_confidence: float = 0.7
    visual_impaired_average_stride_cm: float = 62.0

class StepMeasurementBase:
    """보폭 측정 베이스 클래스"""

    def __init__(self, config: Optional[StepMeasurementConfig] = None):
        self.config = config or StepMeasurementConfig()
        self.measurement_stats = {
            'total_measurements': 0,
            'successful_measurements': 0,
            'average_confidence': 0.0,
            'consistency_score': 0.0
        }
        self.recent_steps = deque(maxlen=10)
        self.walking_pattern_stability = 0.8
        self.sensor_fusion_quality = 0.7

    async def _calculate_distance_based_stride(self, cv_image, user_id: str) -> Optional['StepCalculationResult']:
        """
        시각장애인 최적화된 거리 기반 보폭 계산
        10m 거리 측정을 위한 간소화된 카메라 기반 처리
        """
        try:
            import numpy as np
            from datetime import datetime
            from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyLevel, StepTrackingQuality

            logger.info("[거리기반측정] 시각장애인 최적화 보폭 계산 시작")

            # 10m 표준 거리 가정 (1000cm)
            standard_distance_cm = 1000.0

            # 이미지 품질 기반 걸음 수 추정
            height, width = cv_image.shape[:2]

            # 시각장애인 평균 보폭 특성 (62cm) 기반으로 걸음 수 추정
            visual_impaired_average_stride_cm = self.config.visual_impaired_average_stride_cm
            estimated_steps_for_10m = standard_distance_cm / visual_impaired_average_stride_cm  # 약 16.1걸음

            # 이미지 품질을 통한 실제 걸음 수 보정
            image_quality_factor = self._assess_image_quality_for_distance(cv_image)

            # 걸음 수 보정 (1.0 = 표준, 0.8-1.2 범위)
            step_count_adjustment = 0.9 + (image_quality_factor * 0.2)  # 0.9-1.1 범위
            adjusted_estimated_steps = estimated_steps_for_10m * step_count_adjustment

            # 보정된 걸음 수로 실제 보폭 계산
            calculated_stride_cm = standard_distance_cm / adjusted_estimated_steps

            # 신뢰도 계산 (이미지 품질 + 계산 일관성 기반)
            stride_reasonableness = self._assess_stride_reasonableness(calculated_stride_cm)
            confidence = (image_quality_factor * 0.6) + (stride_reasonableness * 0.4)

            # 시각장애인 특화 신뢰도 조정
            confidence = self.calculate_adjusted_confidence(
                base_confidence=confidence,
                step_stability=0.8,  # 기본 안정성
                sensor_agreement=0.7,  # 단일 센서이므로 중간값
                is_walking_detected=True,  # 측정 중이므로 True 가정
                consistency_with_average=self.calculate_consistency_score(calculated_stride_cm)
            )

            logger.info(f"[거리기반측정] 10m 기준 계산: {adjusted_estimated_steps:.1f}걸음 → {calculated_stride_cm:.1f}cm")

            result = StepCalculationResult(
                step_length_cm=round(calculated_stride_cm, 1),
                confidence=round(confidence, 3),
                step_count=max(1, int(adjusted_estimated_steps)),
                tracking_quality=StepTrackingQuality.GOOD if confidence >= 0.7 else StepTrackingQuality.FAIR,
                accuracy_level=AccuracyLevel.HIGH if confidence >= 0.8 else AccuracyLevel.MEDIUM,
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=datetime.now(),
                consistency_score=self.calculate_consistency_score(calculated_stride_cm),
                processing_time_ms=None,
                source_data={
                    "method": "visual_impairment_optimized_distance_calculation",
                    "standard_distance_cm": standard_distance_cm,
                    "estimated_steps": adjusted_estimated_steps,
                    "image_quality_factor": image_quality_factor,
                    "stride_reasonableness": stride_reasonableness,
                    "visual_impaired_baseline_cm": visual_impaired_average_stride_cm,
                    "user_id": user_id
                }
            )

            # 히스토리 업데이트
            self.update_step_history(result.step_length_cm, result.confidence)

            return result

        except Exception as e:
            logger.error(f"[거리기반측정] 계산 오류: {e}")
            return None

    def _assess_image_quality_for_distance(self, cv_image) -> float:
        """이미지 품질을 평가하여 거리 측정 신뢰도 계산"""
        try:
            import cv2
            import numpy as np

            # 그레이스케일 변환
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image

            # 선명도 평가 (Laplacian variance)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(1.0, laplacian_var / 1500.0)  # 정규화

            # 밝기 일관성 평가
            mean_brightness = np.mean(gray)
            brightness_std = np.std(gray)
            brightness_score = 1.0 - min(1.0, brightness_std / 100.0)  # 표준편차가 낮을수록 좋음

            # 대비 평가
            contrast_score = min(1.0, brightness_std / 50.0)

            # 종합 품질 점수
            quality_score = (sharpness_score * 0.4) + (brightness_score * 0.3) + (contrast_score * 0.3)

            logger.debug(f"[이미지품질] 선명도: {sharpness_score:.3f}, 밝기일관성: {brightness_score:.3f}, 대비: {contrast_score:.3f} → {quality_score:.3f}")

            return max(0.2, min(1.0, quality_score))  # 0.2-1.0 범위 보장

        except Exception as e:
            logger.warning(f"[이미지품질] 평가 오류: {e}")
            return 0.5  # 기본값

    def _assess_stride_reasonableness(self, stride_cm: float) -> float:
        """계산된 보폭의 합리성 평가"""
        try:
            # 시각장애인 보폭 범위 (50-80cm가 일반적)
            ideal_min, ideal_max = 50.0, 80.0

            if ideal_min <= stride_cm <= ideal_max:
                return 1.0  # 이상적 범위
            elif self.config.min_step_length_cm <= stride_cm <= self.config.max_step_length_cm:
                # 허용 가능 범위이지만 이상적이지 않음
                if stride_cm < ideal_min:
                    return 0.7 + (stride_cm - self.config.min_step_length_cm) / (ideal_min - self.config.min_step_length_cm) * 0.3
                else:  # stride_cm > ideal_max
                    return 0.7 + (self.config.max_step_length_cm - stride_cm) / (self.config.max_step_length_cm - ideal_max) * 0.3
            else:
                return 0.3  # 허용 범위를 벗어남

        except Exception as e:
            logger.warning(f"[보폭합리성] 평가 오류: {e}")
            return 0.5

    def calculate_adjusted_confidence(self, base_confidence: float, step_stability: float,
                                    sensor_agreement: float, is_walking_detected: bool,
                                    consistency_with_average: float) -> float:
        """시각장애인 특화 신뢰도 조정"""
        try:
            # 기본 신뢰도에서 시작
            adjusted_confidence = base_confidence

            # 걸음 안정성 반영
            adjusted_confidence *= (0.7 + step_stability * 0.3)

            # 센서 일치도 반영
            adjusted_confidence *= (0.8 + sensor_agreement * 0.2)

            # 보행 감지 여부 반영
            if not is_walking_detected:
                adjusted_confidence *= 0.5

            # 평균과의 일관성 반영
            adjusted_confidence *= (0.9 + consistency_with_average * 0.1)

            return max(0.1, min(1.0, adjusted_confidence))

        except Exception as e:
            logger.warning(f"[신뢰도조정] 오류: {e}")
            return base_confidence

    def calculate_consistency_score(self, current_stride_cm: float) -> float:
        """현재 보폭과 히스토리의 일관성 점수"""
        try:
            if len(self.recent_steps) < 2:
                return 0.8  # 기본값

            # 최근 보폭들과의 표준편차 계산
            recent_strides = [step for step in self.recent_steps]
            import numpy as np
            std_dev = np.std(recent_strides + [current_stride_cm])

            # 표준편차가 낮을수록 일관성이 높음
            consistency = max(0.0, 1.0 - (std_dev / 20.0))  # 20cm 표준편차 기준

            return min(1.0, consistency)

        except Exception as e:
            logger.warning(f"[일관성점수] 계산 오류: {e}")
            return 0.5

    def update_step_history(self, step_length_cm: float, confidence: float):
        """보폭 히스토리 업데이트"""
        try:
            self.recent_steps.append(step_length_cm)

            # 통계 업데이트
            self.measurement_stats['total_measurements'] += 1
            if confidence > 0.6:
                self.measurement_stats['successful_measurements'] += 1

            # 평균 신뢰도 업데이트
            total = self.measurement_stats['total_measurements']
            current_avg = self.measurement_stats['average_confidence']
            self.measurement_stats['average_confidence'] = (current_avg * (total - 1) + confidence) / total

            logger.debug(f"[히스토리] 보폭: {step_length_cm}cm, 신뢰도: {confidence:.3f}, 총 측정: {total}")

        except Exception as e:
            logger.warning(f"[히스토리업데이트] 오류: {e}")

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
    """보폭 측정 관련 유틸리티 함수들"""

    @staticmethod
    def clamp_step_length(step_length_cm: float, min_cm: float = 30.0, max_cm: float = 150.0) -> float:
        """보폭을 안전한 범위로 제한"""
        return max(min_cm, min(max_cm, step_length_cm))

# 전역 유틸리티 함수들 (하위 호환성)
def create_measurement_base(config: Optional[StepMeasurementConfig] = None) -> StepMeasurementBase:
    """측정 베이스 인스턴스 생성"""
    return StepMeasurementBase(config)

def get_default_config() -> StepMeasurementConfig:
    """기본 설정 반환"""
    return StepMeasurementConfig()