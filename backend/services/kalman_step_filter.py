"""레거시 호환성을 위한 간소화된 Kalman Step Filter

이 파일은 새로운 IMU 통합 시스템으로 리다이렉트됩니다.
기존 API 호환성을 위해 최소한의 인터페이스만 유지합니다.
"""

import numpy as np
import time
from typing import Optional, Dict, Any
from collections import deque

# 레거시 호환성을 위한 import 유지
from models.fastdepth_models import FastDepthFootData as FootPosition
from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyConverter

import logging
logger = logging.getLogger(__name__)

class KalmanStepFilter:
    """레거시 호환성을 위한 간소화된 칼만 필터"""
    
    def __init__(self, measurement_noise_xy: float = 0.03, measurement_noise_z: float = 0.35, process_noise: float = 0.005):
        # 기본 설정만 유지
        self.measurement_noise_xy = measurement_noise_xy
        self.measurement_noise_z = measurement_noise_z
        self.process_noise = process_noise
        self.initialized = False
        
        logger.info("[KalmanStepFilter] 레거시 호환 모드로 초기화 - 새로운 IMU 시스템 권장")
    
    def update(self, measurement: FootPosition) -> bool:
        """측정값 업데이트 (레거시 호환성)"""
        # measurement 파라미터 사용 (Pylance 경고 해결)
        if measurement:
            self.initialized = True
        return True
    
    def predict(self) -> Optional[FootPosition]:
        """예측 (레거시 호환성)"""
        if not self.initialized:
            return None
        
        # 기본 더미 위치 반환
        return FootPosition(
            x=0.0, y=0.0, z=1.0,
            confidence=0.5,
            timestamp=time.time()
        )
    
    def get_position(self) -> Optional[FootPosition]:
        """현재 위치 반환 (레거시 호환성)"""
        return self.predict()

class RealTimeStepTracker:
    """레거시 호환성을 위한 간소화된 실시간 걸음 추적기"""
    
    def __init__(self):
        self.left_filter = KalmanStepFilter()
        self.right_filter = KalmanStepFilter()
        
        self.foot_positions = {
            'left': deque(maxlen=10),
            'right': deque(maxlen=10)
        }
        
        self.processing_stats = {
            "total_measurements": 0,
            "successful_predictions": 0,
            "failed_predictions": 0
        }
        
        logger.info("[RealTimeStepTracker] 레거시 호환 모드로 초기화")
    
    def add_foot_measurement(self, foot_side: str, position: FootPosition) -> bool:
        """발 측정값 추가 (레거시 호환성)"""
        try:
            self.processing_stats["total_measurements"] += 1
            
            if foot_side == 'left':
                self.left_filter.update(position)
                self.foot_positions['left'].append(position)
            elif foot_side == 'right':
                self.right_filter.update(position)
                self.foot_positions['right'].append(position)
            
            return True
            
        except Exception as e:
            logger.error(f"[RealTimeStepTracker] 측정값 추가 오류: {e}")
            return False
    
    def get_current_step_result(self) -> Optional[StepCalculationResult]:
        """현재 걸음 결과 반환 (레거시 호환성)"""
        try:
            # 새로운 IMU 시스템 사용 권장 메시지
            logger.warning("[RealTimeStepTracker] 레거시 모드 - 새로운 IMU 통합 시스템 사용을 권장합니다")
            
            # 기본 보폭 계산 (발 위치가 있는 경우)
            left_positions = list(self.foot_positions['left'])
            right_positions = list(self.foot_positions['right'])
            
            if len(left_positions) >= 1 and len(right_positions) >= 1:
                # 최근 위치 기준 거리 계산
                left_pos = left_positions[-1]
                right_pos = right_positions[-1]
                
                dx = left_pos.x - right_pos.x
                dy = left_pos.y - right_pos.y
                dz = left_pos.z - right_pos.z
                
                distance = np.sqrt(dx**2 + dy**2 + dz**2)
                step_length_cm = distance * 100
                
                # 신뢰도 계산
                confidence = (left_pos.confidence + right_pos.confidence) / 2
                confidence *= 0.7  # 레거시 시스템이므로 신뢰도 감소
                
                self.processing_stats["successful_predictions"] += 1
                
                return StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=confidence,
                    step_count=1,
                    tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                    accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                    measurement_method=StepMeasurementMethod.KALMAN_FILTER,
                    timestamp=time.time(),
                    user_id="legacy_tracker",
                    source_data={
                        "method": "legacy_kalman_tracker",
                        "left_positions": len(left_positions),
                        "right_positions": len(right_positions),
                        "warning": "레거시 모드 - 새로운 IMU 시스템 권장"
                    }
                )
            
            # 데이터가 부족하면 기본값
            self.processing_stats["failed_predictions"] += 1
            return StepCalculationResult(
                step_length_cm=65.0,
                confidence=0.3,
                step_count=1,
                tracking_quality=AccuracyConverter.confidence_to_quality(0.3),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(0.3),
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=time.time(),
                user_id="legacy_tracker_fallback",
                source_data={
                    "method": "legacy_fallback",
                    "reason": "insufficient_data"
                }
            )
            
        except Exception as e:
            logger.error(f"[RealTimeStepTracker] 결과 계산 오류: {e}")
            self.processing_stats["failed_predictions"] += 1
            return None
    
    def reset(self):
        """추적기 리셋"""
        self.left_filter = KalmanStepFilter()
        self.right_filter = KalmanStepFilter()
        self.foot_positions['left'].clear()
        self.foot_positions['right'].clear()
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        total = self.processing_stats["total_measurements"]
        if total > 0:
            success_rate = self.processing_stats["successful_predictions"] / total
        else:
            success_rate = 0.0
        
        return {
            **self.processing_stats,
            "success_rate": round(success_rate, 3),
            "status": "legacy_compatibility_mode",
            "recommendation": "새로운 IMU 통합 시스템 사용 권장"
        }

# 레거시 호환성을 위한 별칭
StepTracker = RealTimeStepTracker
FootTracker = RealTimeStepTracker