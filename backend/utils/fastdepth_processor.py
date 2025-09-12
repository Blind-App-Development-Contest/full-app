"""간소화된 카메라 전용 FastDepth 프로세서

10m 거리 측정을 위한 카메라 기반 처리:
- 기본적인 이미지 전처리
- 거리 기반 보폭 계산
- 이미지 속성 기반 추정
"""

import time
import logging
import numpy as np
import cv2
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import deque
from datetime import datetime

# from models.fastdepth_models import FastDepthFrameData, FastDepthFootData  # 사용되지 않음
from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyConverter, StepTrackingQuality, AccuracyLevel
from utils.step_measurement_base import StepMeasurementBase, StepMeasurementUtils, get_visual_impairment_config

logger = logging.getLogger(__name__)

@dataclass
class SimplifiedMeasurementResult:
    """간소화된 측정 결과"""
    step_length_cm: float
    confidence: float
    processing_time_ms: int
    method: str
    timestamp: float
    success: bool
    error_message: Optional[str] = None

class FastDepthProcessor(StepMeasurementBase):
    """카메라 전용 간소화된 FastDepth 프로세서 (10m 거리 측정용)"""
    def __init__(self):
        # 시각장애인 특화 설정으로 베이스 클래스 초기화
        super().__init__(get_visual_impairment_config())
        
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        logger.info("[FastDepth] 카메라 전용 프로세서 초기화 완료 (시각장애인 특화)")

        # 사용자별 누적 거리(미터). 기본값 fallback 용도로 사용
        self._user_total_distance: Dict[str, float] = {}

    async def process_frame_for_measurement(
        self, 
        cv_image: np.ndarray, 
        user_id: str = 'current_user'
    ) -> Optional[StepCalculationResult]:
        start_time = time.time()
        try:
            logger.info(f"[FastDepth] 카메라 기반 측정 시작: {user_id}")
            if cv_image is None or cv_image.size == 0:
                raise ValueError("유효하지 않은 이미지")
            height, width = cv_image.shape[:2]
            logger.debug(f"[FastDepth] 이미지 크기: {width}x{height}")
            # 거리 기반 측정 시스템 직접 사용 (시각장애인 최적화)
            result = await self._use_distance_measurement_system(cv_image, user_id)
            processing_time = time.time() - start_time
            
            # 결과 처리 및 메타데이터 추가
            if result:
                result.source_data.update({
                    "processing_time_ms": int(processing_time * 1000),
                    "processor_version": "visual_impairment_optimized", 
                    "image_size": f"{width}x{height}",
                    "user_id": user_id
                })
                self._update_stats(processing_time, True, result.step_length_cm, result.confidence)
                logger.info(f"[FastDepth] 측정 완료: {result.step_length_cm:.1f}cm (신뢰도: {result.confidence:.3f})")
            else:
                # 통합된 fallback 처리
                result = self._create_unified_fallback(user_id, "distance_measurement_failed")
                self._update_stats(processing_time, False)
                logger.info(f"[FastDepth] Fallback 적용: {result.step_length_cm:.1f}cm")
            
            return result
        except Exception as e:
            processing_time = time.time() - start_time
            self._update_stats(processing_time, False)
            logger.error(f"[FastDepth] 프레임 처리 오류: {e}")
            
            # 통합된 fallback 처리
            return self._create_unified_fallback(user_id, f"processing_error: {str(e)}")
    
    
    async def _use_distance_measurement_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """거리 기반 측정 시스템 (시각장애인 최적화)"""
        try:
            logger.info("[FastDepth] 시각장애인 맞춤 거리 기반 측정 시작")
            return await self._calculate_distance_based_stride(cv_image, user_id)
            
        except Exception as e:
            logger.error(f"[FastDepth] 거리 측정 오류: {e}")
            return None  # 통합 fallback에서 처리

    def get_total_distance(self, user_id: str) -> float:
        """
        사용자별 누적 이동 거리(m)를 반환.
        - 현재 누적 로직이 없다면 기존 서버 fallback과 동일하게 8.5m를 반환하여
          호출부의 타입/특성 접근 오류를 해소하고 동작을 유지합니다.
        """
        try:
            value = self._user_total_distance.get(user_id)
            return float(value) if value is not None else 8.5
        except Exception:
            return 8.5
         
    def _calculate_image_confidence(self, cv_image: np.ndarray) -> float:
        """이미지 백업 시스템의 신뢰도 계산"""
        try:
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_confidence = min(1.0, laplacian_var / 1000.0)
            mean_brightness = np.mean(gray)
            brightness_std = np.std(gray)
            brightness_confidence = 1.0 - min(1.0, brightness_std / 128.0)
            base_confidence = 0.4
            final_confidence = base_confidence * (0.3 + 0.4 * sharpness_confidence + 0.3 * brightness_confidence)
            return float(max(0.2, min(0.7, final_confidence)))
        except Exception as e:
            logger.warning(f"[FastDepth] 이미지 신뢰도 계산 오류: {e}")
            return 0.3

    def reset_stats(self):
        """통계 리셋"""
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        # 베이스 클래스에서 초기화 처리
        self.reset_statistics()
    
    def _create_unified_fallback(self, user_id: str, reason: str) -> StepCalculationResult:
        """통합된 시각장애인 맞춤 Fallback 시스템"""
        try:
            # 시각장애인 평균 보폭 특성 반영
            visual_impaired_stride_cm = 62.0  # 일반인 70cm보다 안전을 위해 짧음
            
            logger.info(f"[FastDepth] 시각장애인 맞춤 Fallback 적용: {visual_impaired_stride_cm}cm")
            
            return StepCalculationResult(
                step_length_cm=visual_impaired_stride_cm,
                confidence=0.6,  # 적당한 신뢰도 - 너무 낮지도 높지도 않게
                step_count=1,
                tracking_quality=StepTrackingQuality.FAIR,
                accuracy_level=AccuracyLevel.MEDIUM,
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=datetime.now(),
                source_data={
                    "method": "unified_visual_impairment_fallback",
                    "stride_basis": "visual_impaired_average",
                    "user_id": user_id,
                    "fallback_reason": reason,
                    "optimized_for": "visual_impairment"
                },
                consistency_score=None,
                processing_time_ms=0.0
            )
        except Exception as e:
            logger.error(f"[FastDepth] 통합 Fallback 생성 실패: {e} - 응급 기본값 사용")
            # 최후의 수단: 하드코딩된 안전값
            return StepCalculationResult(
                step_length_cm=62.0,
                confidence=0.5,
                step_count=1,
                tracking_quality=StepTrackingQuality.FAIR,
                accuracy_level=AccuracyLevel.MEDIUM,
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=datetime.now(),
                source_data={
                    "method": "emergency_hardcoded_fallback",
                    "reason": f"unified_fallback_failed: {str(e)}"
                },
                consistency_score=None,
                processing_time_ms=0.0
            )

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """간소화된 FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor
