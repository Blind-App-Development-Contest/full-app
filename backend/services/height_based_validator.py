"""시각장애인 전용 키 기반 보폭 검증 시스템"""

import logging
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class UserCharacteristics:
    """시각장애인 사용자 특성 정보"""
    height_cm: float
    uses_mobility_aid: bool = False  # 지팡이/안내견 사용 여부 (실내 측정 고려)
    walking_speed: str = "careful"   # careful/normal/confident (신중함 기본)
    confidence_level: str = "medium" # low/medium/high (환경 친숙도)
    familiar_environment: bool = True # 익숙한 환경 여부
    
    def __post_init__(self):
        if self.height_cm < 100 or self.height_cm > 220:
            raise ValueError(f"비정상적인 키 값: {self.height_cm}cm")

class HeightBasedValidator:
    """시각장애인 전용 키 기반 보폭 검증기"""
    
    def __init__(self, user_characteristics: UserCharacteristics):
        self.user_char = user_characteristics
        self.step_ratio_range = self._calculate_step_ratios()
        
        # 검증 통계
        self.validation_count = 0
        self.adjustment_history = []
        
        logger.info(f"HeightBasedValidator 초기화 - 키: {self.user_char.height_cm}cm, "
                   f"예상 보폭 범위: {self.get_expected_step_range()}")
    
    def _calculate_step_ratios(self) -> Tuple[float, float]:
        """사용자 특성에 따른 키-보폭 비율 계산"""
        # 기본 범위 (일반적인 키-보폭 비율)
        base_min, base_max = 0.40, 0.47
        
        # 이동 보조기구 사용 시 보폭 감소
        if self.user_char.uses_mobility_aid:
            base_min -= 0.02
            base_max -= 0.02
            logger.debug("이동 보조기구 사용으로 보폭 범위 조정")
        
        # 환경 친숙도에 따른 조정
        if self.user_char.confidence_level == "low" or not self.user_char.familiar_environment:
            # 신중한 보행으로 보폭 감소
            base_min -= 0.03
            base_max -= 0.01
            logger.debug("낮은 환경 친숙도로 보폭 범위 조정")
        elif self.user_char.confidence_level == "high" and self.user_char.familiar_environment:
            # 자신 있는 보행으로 보폭 증가 가능
            base_max += 0.02
        
        # 보행 속도 반영 (시각장애인 특화)
        if self.user_char.walking_speed == "careful":
            base_min -= 0.02  # 신중한 보행으로 보폭 감소
            base_max -= 0.01
        elif self.user_char.walking_speed == "confident":
            base_min += 0.01  # 자신 있는 보행으로 보폭 증가
            base_max += 0.02
        
        # 최소/최대 제한
        final_min = max(base_min, 0.30)  # 최소 30%
        final_max = min(base_max, 0.55)  # 최대 55%
        
        return (final_min, final_max)
    
    def get_expected_step_range(self) -> Tuple[float, float]:
        """예상 보폭 범위 (cm) 반환"""
        min_ratio, max_ratio = self.step_ratio_range
        min_step = self.user_char.height_cm * min_ratio
        max_step = self.user_char.height_cm * max_ratio
        return (round(min_step, 1), round(max_step, 1))
    
    def validate_measurement(self, measured_step_cm: float, current_confidence: float) -> Dict[str, float]:
        """
        측정값 검증 및 신뢰도 보정
        
        Args:
            measured_step_cm: 측정된 보폭 (cm)
            current_confidence: 현재 측정 신뢰도 (0.0-1.0)
            
        Returns:
            Dict with adjusted_confidence, validation_score, recommendation
        """
        self.validation_count += 1
        min_step, max_step = self.get_expected_step_range()
        
        # 유효성 점수 계산
        if min_step <= measured_step_cm <= max_step:
            # 정상 범위 내
            validation_score = 1.0
            deviation_ratio = 0.0
        else:
            # 범위 벗어남 - 편차에 따른 점수
            if measured_step_cm < min_step:
                deviation = min_step - measured_step_cm
            else:
                deviation = measured_step_cm - max_step
                
            deviation_ratio = deviation / self.user_char.height_cm
            validation_score = max(0.1, 1.0 - deviation_ratio * 3.0)  # 편차 페널티
        
        # 신뢰도 조정
        if validation_score >= 0.8:
            # 키 기준 매우 적합 - 신뢰도 증가
            adjustment_factor = 1.2
            recommendation = "키에 적합한 정상적인 보폭입니다."
        elif validation_score >= 0.6:
            # 키 기준 적합 - 신뢰도 약간 증가  
            adjustment_factor = 1.1
            recommendation = "키 기준으로 적절한 보폭입니다."
        elif validation_score >= 0.4:
            # 키 기준 의심스러움 - 신뢰도 유지
            adjustment_factor = 1.0
            recommendation = "키 대비 다소 다른 보폭입니다. 측정 환경을 확인해보세요."
        else:
            # 키 기준 부적절 - 신뢰도 감소
            adjustment_factor = 0.7
            if measured_step_cm < min_step:
                recommendation = f"키({self.user_char.height_cm}cm) 대비 보폭이 작습니다. 더 자연스럽게 걸어보세요."
            else:
                recommendation = f"키({self.user_char.height_cm}cm) 대비 보폭이 큽니다. 측정 중 뛰거나 빠르게 걷지 않았는지 확인해보세요."
        
        # 최종 신뢰도 계산
        adjusted_confidence = min(current_confidence * adjustment_factor, 1.0)
        adjusted_confidence = max(adjusted_confidence, 0.1)  # 최소 신뢰도 보장
        
        # 기록 저장
        validation_record = {
            'measured_step': measured_step_cm,
            'expected_range': (min_step, max_step),
            'validation_score': validation_score,
            'original_confidence': current_confidence,
            'adjusted_confidence': adjusted_confidence,
            'adjustment_factor': adjustment_factor
        }
        self.adjustment_history.append(validation_record)
        
        logger.info(f"키 기반 검증 완료 - 측정값: {measured_step_cm}cm, "
                   f"예상범위: {min_step}-{max_step}cm, "
                   f"신뢰도: {current_confidence:.2f} → {adjusted_confidence:.2f}")
        
        return {
            'adjusted_confidence': adjusted_confidence,
            'validation_score': validation_score,
            'recommendation': recommendation,
            'expected_min': min_step,
            'expected_max': max_step,
            'deviation_ratio': deviation_ratio
        }
    
    def get_calibration_test_distances(self) -> Dict[str, float]:
        """사용자 특성에 맞는 보정 테스트 거리 추천"""
        min_step, max_step = self.get_expected_step_range()
        avg_step = (min_step + max_step) / 2
        
        # 보폭 기반 적정 테스트 거리 계산
        short_distance = round(avg_step * 0.05, 1)  # 약 5걸음
        medium_distance = round(avg_step * 0.08, 1)  # 약 8걸음  
        long_distance = round(avg_step * 0.12, 1)   # 약 12걸음
        
        return {
            'short': max(short_distance, 2.0),    # 최소 2m
            'medium': max(medium_distance, 4.0),  # 최소 4m
            'long': max(long_distance, 6.0)       # 최소 6m
        }
    
    def suggest_measurement_tips(self) -> list[str]:
        """사용자 특성별 측정 팁 제공"""
        tips = [
            "평평하고 장애물이 없는 직선 경로를 선택하세요.",
            "평상시 걷는 속도로 자연스럽게 걸어주세요."
        ]
        
        if self.user_char.uses_mobility_aid:
            tips.append("지팡이나 안내견과 함께 평소처럼 편안하게 걸으세요.")
        
        if not self.user_char.familiar_environment:
            tips.append("처음 걷는 길이라면 한 번 천천히 걸어본 후 측정하세요.")
            
        if self.user_char.confidence_level == "low":
            tips.extend([
                "벽이나 난간을 따라 걷는 것도 좋습니다.",
                "측정 전 경로를 손으로 확인해보세요."
            ])
        
        return tips
    
    def get_validation_statistics(self) -> Dict:
        """검증 통계 반환"""
        if not self.adjustment_history:
            return {'message': '아직 검증 데이터가 없습니다.'}
        
        recent_records = self.adjustment_history[-10:]  # 최근 10개
        avg_validation_score = sum(r['validation_score'] for r in recent_records) / len(recent_records)
        avg_adjustment = sum(r['adjustment_factor'] for r in recent_records) / len(recent_records)
        
        return {
            'total_validations': len(self.adjustment_history),
            'recent_avg_validation_score': round(avg_validation_score, 2),
            'recent_avg_adjustment_factor': round(avg_adjustment, 2),
            'user_characteristics': {
                'height': self.user_char.height_cm,
                'expected_step_range': self.get_expected_step_range(),
                'uses_mobility_aid': self.user_char.uses_mobility_aid,
                'walking_speed': self.user_char.walking_speed
            }
        }

# 사용 예시 함수
def create_validator_for_user(height_cm: float, **kwargs) -> HeightBasedValidator:
    """사용자용 검증기 생성 헬퍼 함수"""
    characteristics = UserCharacteristics(
        height_cm=height_cm,
        uses_mobility_aid=kwargs.get('uses_mobility_aid', False),
        walking_speed=kwargs.get('walking_speed', 'careful'),
        confidence_level=kwargs.get('confidence_level', 'medium'),
        familiar_environment=kwargs.get('familiar_environment', True)
    )
    
    return HeightBasedValidator(characteristics)