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
import torch
import torch.nn.functional as F
from utils.model_manager import get_midas_manager

# from models.fastdepth_models import FastDepthFrameData, FastDepthFootData  # 사용되지 않음
from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyConverter, StepTrackingQuality, AccuracyLevel
# step_measurement_base import 제거 - 사용되지 않음
from middleware.error_handler import ErrorLogger

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

class FastDepthProcessor:
    """MiDaS 기반 실제 거리 측정 프로세서 (시각장애인 특화)"""
    def __init__(self):
        
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        
        # MiDaS 모델 매니저 (중앙 집중식)
        self.midas_manager = get_midas_manager()
        
        # 카메라 캘리브레이션 파라미터
        self.focal_length = 525.0  # 일반적인 스마트폰 카메라
        
        logger.info("[FastDepth] MiDaS 기반 프로세서 초기화 완료 (시각장애인 특화)")

        # 사용자별 누적 거리(미터). 기본값 fallback 용도로 사용
        self._user_total_distance: Dict[str, float] = {}
        
    def _ensure_midas_model(self) -> bool:
        """MiDaS 모델 로딩 확인 (중앙 매니저 사용)"""
        try:
            return self.midas_manager.load_model()
        except Exception as e:
            logger.error(f"[FastDepth] MiDaS 모델 매니저 오류: {e}")
            return False

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
            ErrorLogger.log_service_error("FastDepthProcessor", "프레임 처리", e)
            
            # 통합된 fallback 처리
            return self._create_unified_fallback(user_id, f"processing_error: {str(e)}")
    
    
    async def _use_distance_measurement_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """프레임 기반 거리 측정 시스템 (시각장애인 최적화)"""
        try:
            logger.info("[FastDepth] 프레임 기반 거리 측정 시작")
            
            # 실제 프레임 분석으로 거리 측정
            measured_distance_meters = self._analyze_frame_for_distance(cv_image)
            
            # 음성으로 입력된 걸음수는 별도로 받아야 함
            # 여기서는 거리만 측정하고, API에서 걸음수와 결합
            logger.info(f"[FastDepth] 측정된 거리: {measured_distance_meters}m")
            
            return None  # API 레벨에서 거리+걸음수 결합하여 보폭 계산
            
        except Exception as e:
            ErrorLogger.log_service_error("FastDepthProcessor", "프레임 기반 거리 측정", e)
            return None  # 통합 fallback에서 처리
    
    def _analyze_frame_for_distance(self, cv_image: np.ndarray) -> float:
        """MiDaS 모델로 실제 거리 측정"""
        try:
            height, width = cv_image.shape[:2]
            logger.info(f"[FastDepth] MiDaS 프레임 분석 시작: {width}x{height}")
            
            # 모델 로딩 확인 (중앙 매니저 사용)
            if not self.midas_manager.is_loaded():
                if not self._ensure_midas_model():
                    logger.warning("[FastDepth] MiDaS 로딩 실패, fallback 사용")
                    return self._estimate_distance_from_frame_properties(cv_image)
            
            # MiDaS 추론
            distance_meters = self._run_midas_inference(cv_image)
            
            logger.info(f"[FastDepth] MiDaS 측정 거리: {distance_meters:.2f}m")
            return distance_meters
            
        except Exception as e:
            logger.error(f"[FastDepth] MiDaS 추론 실패: {e}, fallback 사용")
            return self._estimate_distance_from_frame_properties(cv_image)
    
    def _run_midas_inference(self, cv_image: np.ndarray) -> float:
        """MiDaS 모델로 실제 depth 추론 및 거리 계산 (중앙 매니저 사용)"""
        try:
            # 중앙 매니저에서 모델, 변환기, 디바이스 획득
            model, transform, device = self.midas_manager.get_model()
            if model is None or transform is None or device is None:
                raise RuntimeError("MiDaS 모델 또는 변환기를 가져올 수 없습니다")
            
            # BGR을 RGB로 변환
            rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            
            # MiDaS 전처리
            input_tensor = transform(rgb_image).to(device)
            input_batch = input_tensor.unsqueeze(0)
            
            # 추론
            with torch.no_grad():
                depth_map = model(input_batch)
                depth_map = torch.nn.functional.interpolate(
                    depth_map.unsqueeze(1),
                    size=cv_image.shape[:2],
                    mode="bicubic",
                    align_corners=False,
                ).squeeze()
            
            # NumPy로 변환
            depth_numpy = depth_map.cpu().numpy()
            
            # 실제 거리로 변환
            distance_meters = self._convert_depth_to_distance(depth_numpy, cv_image.shape)
            
            return distance_meters
            
        except Exception as e:
            logger.error(f"[FastDepth] MiDaS 추론 중 오류: {e}")
            raise
    
    def _convert_depth_to_distance(self, depth_map: np.ndarray, image_shape: Tuple[int, int]) -> float:
        """시각장애인 맞춤 거리 측정 - 보행 경로 중심 분석"""
        try:
            height, width = image_shape[:2]
            
            # 시각장애인 보행 특성을 고려한 ROI 설정
            # 1. 하단 중앙: 발걸음/지면 영역 (가중치 높음)
            # 2. 중앙: 보행 장애물 감지 영역
            # 3. 상단은 제외 (하늘/천장은 보행과 무관)
            
            center_x = width // 2
            
            # 하단 보행 경로 영역 (70% 가중치)
            ground_y = int(height * 0.75)  # 하단 75% 지점
            ground_roi_size = min(height, width) // 6
            
            ground_y1 = max(0, ground_y - ground_roi_size // 2)
            ground_y2 = min(height, ground_y + ground_roi_size // 2)
            ground_x1 = max(0, center_x - ground_roi_size)
            ground_x2 = min(width, center_x + ground_roi_size)
            
            ground_roi = depth_map[ground_y1:ground_y2, ground_x1:ground_x2]
            ground_depth = np.median(ground_roi) if ground_roi.size > 0 else 0
            
            # 중앙 장애물 감지 영역 (30% 가중치)
            mid_y = height // 2
            mid_roi_size = min(height, width) // 10
            
            mid_y1 = max(0, mid_y - mid_roi_size)
            mid_y2 = min(height, mid_y + mid_roi_size)
            mid_x1 = max(0, center_x - mid_roi_size)
            mid_x2 = min(width, center_x + mid_roi_size)
            
            mid_roi = depth_map[mid_y1:mid_y2, mid_x1:mid_x2]
            mid_depth = np.median(mid_roi) if mid_roi.size > 0 else 0
            
            # 가중 평균으로 최종 depth 계산
            if ground_depth > 0 and mid_depth > 0:
                weighted_depth = (ground_depth * 0.7 + mid_depth * 0.3)
            elif ground_depth > 0:
                weighted_depth = ground_depth
            elif mid_depth > 0:
                weighted_depth = mid_depth
            else:
                weighted_depth = 50.0  # 기본값
            
            # 시각장애인 보행 거리 특성 반영한 스케일링
            if weighted_depth > 0:
                # 보수적 거리 계산 (안전을 위해 약간 짧게 추정)
                distance_meters = 12.0 / (weighted_depth / 45.0 + 0.8)
                
                # 시각장애인 일반적 보행 거리 범위로 제한
                distance_meters = np.clip(distance_meters, 0.8, 15.0)  # 80cm ~ 15m
                
                # 단거리는 더 정확하게, 장거리는 보수적으로
                if distance_meters < 3.0:
                    distance_meters *= 0.95  # 5% 보수적
                elif distance_meters > 8.0:
                    distance_meters *= 0.90  # 10% 보수적
            else:
                distance_meters = 4.0  # 시각장애인 평균 보행 측정 거리
            
            logger.info(f"[FastDepth-시각장애인] Ground: {ground_depth:.1f}, Mid: {mid_depth:.1f} → {distance_meters:.2f}m")
            return float(distance_meters)
            
        except Exception as e:
            logger.error(f"[FastDepth] 시각장애인 맞춤 거리 변환 실패: {e}")
            return 4.0  # 시각장애인 안전 기본값
    
    def _estimate_distance_from_frame_properties(self, cv_image: np.ndarray) -> float:
        """시각장애인 맞춤 이미지 속성 기반 거리 추정 (MiDaS 백업용)"""
        try:
            height, width = cv_image.shape[:2]
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image
            
            # 시각장애인 보행 경로 분석을 위한 영역별 특성 계산
            
            # 1. 하단 지면 영역 분석 (보행로 인식)
            ground_region = gray[int(height * 0.6):, :]  # 하단 40%
            ground_brightness = np.mean(ground_region)
            ground_contrast = np.std(ground_region)
            
            # 2. 중앙 장애물 영역 분석
            mid_region = gray[int(height * 0.3):int(height * 0.7), :]  # 중앙 40%
            mid_brightness = np.mean(mid_region)
            mid_edges = cv2.Laplacian(mid_region, cv2.CV_64F).var()  # 에지 강도
            
            # 시각장애인 보행 특성 기반 거리 추정
            base_distance = 4.0  # 시각장애인 평균 측정 거리
            
            # 지면 밝기 기반 보정 (밝은 지면 = 가까움, 어두운 지면 = 멀음)
            brightness_factor = 1.5 - (ground_brightness / 255.0)  # 0.5 ~ 1.5
            
            # 대비 기반 보정 (높은 대비 = 명확한 거리, 낮은 대비 = 모호함)
            contrast_factor = 0.8 + (ground_contrast / 128.0) * 0.4  # 0.8 ~ 1.2
            
            # 에지 기반 보정 (많은 에지 = 복잡한 환경 = 보수적 추정)
            edge_factor = 1.1 - min(0.3, mid_edges / 1000.0)  # 0.8 ~ 1.1
            
            estimated_distance = base_distance * brightness_factor * contrast_factor * edge_factor
            
            # 시각장애인 보행 거리 범위로 제한 (보수적)
            estimated_distance = np.clip(estimated_distance, 1.5, 12.0)
            
            logger.info(f"[FastDepth-Fallback] 지면밝기:{ground_brightness:.0f}, 대비:{ground_contrast:.1f} → {estimated_distance:.2f}m")
            return float(estimated_distance)
            
        except Exception as e:
            logger.error(f"[FastDepth] 시각장애인 맞춤 거리 추정 실패: {e}")
            return 4.0  # 시각장애인 안전 기본값

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

    def _update_stats(self, processing_time: float, success: bool, step_length_cm: Optional[float] = None, confidence: Optional[float] = None):
        """처리 통계 업데이트"""
        try:
            self.processing_stats["total_processed"] += 1

            if success:
                self.processing_stats["successful_measurements"] += 1
            else:
                self.processing_stats["failed_measurements"] += 1

            # 평균 처리 시간 업데이트
            total = self.processing_stats["total_processed"]
            current_avg = self.processing_stats["average_processing_time"]
            self.processing_stats["average_processing_time"] = (current_avg * (total - 1) + processing_time) / total

        except Exception as e:
            logger.warning(f"[FastDepth] 통계 업데이트 오류: {e}")

    def reset_stats(self):
        """통계 리셋"""
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        logger.info("[FastDepth] 통계 리셋 완료")
    
    def _create_unified_fallback(self, user_id: str, reason: str) -> StepCalculationResult:
        """통합된 시각장애인 맞춤 Fallback 시스템"""
        try:
            # 시각장애인 보행 특성을 고려한 보수적 보폭
            # - 안전을 위해 일반인보다 짧게 설정
            # - 실내/실외 환경을 고려한 평균값
            visual_impaired_stride_cm = 58.0  # 일반인 70cm보다 더 보수적
            
            logger.info(f"[FastDepth] 시각장애인 맞춤 안전 Fallback 적용: {visual_impaired_stride_cm}cm")
            
            return StepCalculationResult(
                step_length_cm=visual_impaired_stride_cm,
                confidence=0.5,  # 보수적 신뢰도 (안전 우선)
                step_count=1,
                tracking_quality=StepTrackingQuality.FAIR,
                accuracy_level=AccuracyLevel.MEDIUM,
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=datetime.now(),
                source_data={
                    "method": "visual_impairment_safety_fallback",
                    "stride_basis": "conservative_visual_impaired",
                    "user_id": user_id,
                    "fallback_reason": reason,
                    "safety_priority": "high",
                    "optimized_for": "visual_impairment_safety"
                },
                consistency_score=None,
                processing_time_ms=0.0
            )
        except Exception as e:
            ErrorLogger.log_service_error("FastDepthProcessor", "통합 Fallback 생성", Exception(f"Fallback 생성 실패: {e} - 응급 기본값 사용"))
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
    
    def cleanup_memory(self):
        """메모리 정리 (캐시 및 통계 초기화)"""
        try:
            # 통계 초기화
            self.reset_stats()
            
            # GPU 메모리 정리 (사용 가능한 경우)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            logger.info("[FastDepth] 메모리 정리 완료")
            
        except Exception as e:
            logger.warning(f"[FastDepth] 메모리 정리 중 오류: {e}")

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """간소화된 FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor
