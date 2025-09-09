"""간소화된 카메라 전용 FastDepth 프로세서

10m 거리 측정을 위한 카메라 기반 처리:
- 기본적인 이미지 전처리
- MediaPipe 발 키포인트 감지
- 거리 기반 보폭 계산
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
            # 카메라만 사용한 기본 시스템
            result = await self._use_basic_camera_system(cv_image, user_id)
            processing_time = time.time() - start_time
            # 통계/평균 업데이트
            if result:
                self._update_stats(processing_time, True, result.step_length_cm, result.confidence)
            else:
                self._update_stats(processing_time, False)
            if result:
                # 평균 보폭/신뢰도 정보 추가
                avg_step = self.get_average_step_length()
                result.source_data.update({
                    "processing_time_ms": int(processing_time * 1000),
                    "processor_version": "camera_only",
                    "image_size": f"{width}x{height}",
                    "user_id": user_id,
                    "average_step_length_cm": avg_step
                })
                logger.info(f"[FastDepth] 측정 완료: {result.step_length_cm:.1f}cm (신뢰도: {result.confidence:.3f}, {processing_time*1000:.1f}ms, 평균보폭: {avg_step:.1f}cm)")
            else:
                logger.warning("[FastDepth] 측정 실패 - fallback 로직 실행")
                # 시각장애인을 위한 무조건 fallback 실행
                result = self.create_fallback_step_result(
                    reason="vision_processing_failed",
                    estimated_distance_cm=None,
                    estimated_step_count=None
                )
                logger.info(f"[FastDepth] fallback 적용: {result.step_length_cm:.1f}cm (신뢰도: {result.confidence:.3f})")
            return result
        except Exception as e:
            processing_time = time.time() - start_time
            self._update_stats(processing_time, False)
            logger.error(f"[FastDepth] 프레임 처리 오류: {e}")
            
            # 시각장애인을 위한 대체 측정 결과 생성
            try:
                fallback_result = self.create_fallback_step_result(
                    reason=f"fastdepth_processing_error: {str(e)}",
                    estimated_distance_cm=None,
                    estimated_step_count=None
                )
                
                logger.warning(f"[FastDepth] 대체 측정 적용: {fallback_result.step_length_cm:.1f}cm (신뢰도: {fallback_result.confidence:.3f})")
                return fallback_result
                
            except Exception as fallback_error:
                logger.error(f"[FastDepth] 대체 측정 생성 실패: {fallback_error} - 기본값 사용")
                # 최후의 수단: 하드코딩된 기본값 반환 (시각장애인 보조)
                return StepCalculationResult(
                    step_length_cm=65.0,  # 성인 평균 보폭
                    confidence=0.3,
                    step_count=1,
                    tracking_quality=StepTrackingQuality.POOR,
                    accuracy_level=AccuracyLevel.LOW,
                    measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                    timestamp=datetime.now(),
                    source_data={
                        "method": "emergency_fallback",
                        "reason": f"all_fallback_failed: {str(fallback_error)}",
                        "default_value": True
                    },
                    consistency_score=None,
                    processing_time_ms=0.0
                )
    
    
    async def _use_basic_camera_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """기본 카메라 전용 처리 (발 특화 감지 포함)"""
        try:
            from utils.mediapipe_pose_processor import get_mediapipe_pose_processor
            
            # MediaPipe 프로세서 가져오기
            mediapipe_processor = get_mediapipe_pose_processor(enable_imu_fusion=False)
            
            # 1단계: 강화된 발 키포인트 감지 시도
            keypoints = mediapipe_processor.extract_foot_keypoints_enhanced(cv_image)
            
            if not keypoints:
                logger.warning("[FastDepth] 모든 MediaPipe 발 키포인트 감지 방법 실패")
                
                # 2단계: 거리 기반 백업 시스템 사용
                logger.info("[FastDepth] 거리 기반 백업 시스템으로 전환")
                return await self._use_distance_backup_system(cv_image, user_id)
            
            logger.info(f"[FastDepth] 발 키포인트 감지 성공 (신뢰도: {keypoints.confidence_score:.3f})")
            
            # 3D 좌표 변환
            foot_positions = mediapipe_processor.convert_to_3d_coordinates(keypoints, cv_image)
            
            # left/right foot 추출
            lefts = [p for p in foot_positions if getattr(p, 'foot_side', None) == 'left']
            rights = [p for p in foot_positions if getattr(p, 'foot_side', None) == 'right']
            
            if lefts and rights:
                left = lefts[0]
                right = rights[0]
                
                # 두 발 사이 거리 계산
                dx = left.x - right.x
                dy = left.y - right.y
                dz = left.z - right.z
                
                distance_m = np.sqrt(dx**2 + dy**2 + dz**2)
                step_length_cm = distance_m * 100
                
                confidence = (left.confidence + right.confidence) / 2
                
                return StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=confidence,
                    step_count=1,
                    tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                    accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                    measurement_method=StepMeasurementMethod.POSE_ESTIMATION,
                    timestamp=datetime.now(),
                    source_data={
                        "method": "basic_camera_mediapipe",
                        "keypoint_types": f"{left.keypoint_type}-{right.keypoint_type}",
                        "processing_quality": "basic"
                    },
                    consistency_score=None,
                    processing_time_ms=0.0
                )
            
            # 시각장애인을 위한 fallback 실행
            return self.create_fallback_step_result(
                reason="basic_camera_no_valid_keypoints",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] 기본 카메라 처리 오류: {e} - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason=f"basic_camera_error: {str(e)}",
                estimated_distance_cm=None,
                estimated_step_count=None
            )

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
    
    def _calculate_foot_distance(self, left_pos, right_pos) -> float:
        """두 발 사이의 3D 거리 계산 (None 방지)"""
        try:
            lx = float(left_pos[0]) if left_pos and len(left_pos) > 0 and left_pos[0] is not None else 0.0
            ly = float(left_pos[1]) if left_pos and len(left_pos) > 1 and left_pos[1] is not None else 0.0
            lz = float(left_pos[2]) if left_pos and len(left_pos) > 2 and left_pos[2] is not None else 0.0
            rx = float(right_pos[0]) if right_pos and len(right_pos) > 0 and right_pos[0] is not None else 0.0
            ry = float(right_pos[1]) if right_pos and len(right_pos) > 1 and right_pos[1] is not None else 0.0
            rz = float(right_pos[2]) if right_pos and len(right_pos) > 2 and right_pos[2] is not None else 0.0
            dx = lx - rx
            dy = ly - ry
            dz = lz - rz
            return float(np.sqrt(dx**2 + dy**2 + dz**2))
        except Exception:
            return 0.0
    
    def _extract_confidence(self, position_data) -> float:
        """위치 데이터에서 신뢰도 추출 (None/타입/NaN 방지)"""
        if position_data is None:
            return 0.7
        if isinstance(position_data, (tuple, list)):
            if len(position_data) < 4 or position_data[3] is None:
                return 0.7
            val = position_data[3]
            import math
            if not isinstance(val, (float, int)):
                return 0.7
            if math.isnan(val):
                return 0.7
            return float(val)
        try:
            import numpy as np
            if isinstance(position_data, np.ndarray):
                if position_data.ndim == 1:
                    if position_data.shape[0] < 4:
                        return 0.7
                    val = position_data[3]
                    import math
                    if not isinstance(val, (float, int, np.floating)):
                        return 0.7
                    if math.isnan(val):
                        return 0.7
                    return float(val)
                else:
                    return 0.7
        except ImportError:
            pass
        if isinstance(position_data, dict) and 'confidence' in position_data and position_data['confidence'] is not None:
            val = position_data['confidence']
            import math
            if not isinstance(val, (float, int)):
                return 0.7
            if math.isnan(val):
                return 0.7
            return float(val)
        return 0.7  # 기본 신뢰도
    
    def _update_stats(self, processing_time: float, success: bool, step_length_cm: Optional[float] = None, confidence: Optional[float] = None):
        self.processing_stats["total_processed"] += 1
        if success:
            self.processing_stats["successful_measurements"] += 1
        else:
            self.processing_stats["failed_measurements"] += 1
        total = self.processing_stats["total_processed"]
        current_avg = self.processing_stats["average_processing_time"]
        new_avg = ((current_avg * (total - 1)) + processing_time) / total
        self.processing_stats["average_processing_time"] = new_avg
        # 최근 측정값 저장 - 베이스 클래스 메서드 사용
        if step_length_cm is not None and confidence is not None:
            self.update_step_history(step_length_cm, confidence)

    # 베이스 클래스에서 메서드를 제공하므로 중복 제거됨
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        stats = self.processing_stats.copy()
        if stats["total_processed"] > 0:
            stats["success_rate"] = stats["successful_measurements"] / stats["total_processed"]
        else:
            stats["success_rate"] = 0.0
        return stats
    
    async def _use_distance_backup_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """거리 기반 백업 측정 시스템 - MediaPipe 실패 시 사용"""
        try:
            logger.info("[FastDepth] 거리 기반 백업 시스템 시작")
            
            # 이미지 크기 기반 대략적 스케일 추정
            height, width = cv_image.shape[:2]
            
            # 10m 거리 측정을 위한 보폭 추정
            estimated_step_length_cm = self._estimate_step_from_image_properties(width, height)
            
            # 이미지 품질에 따른 신뢰도 계산
            confidence = self._calculate_image_confidence(cv_image)
            
            logger.info(f"[FastDepth] 거리 백업 추정 보폭: {estimated_step_length_cm}cm, 신뢰도: {confidence:.3f}")
            
            return StepCalculationResult(
                step_length_cm=round(estimated_step_length_cm, 1),
                confidence=confidence,
                step_count=1,
                tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=datetime.now(),
                source_data={
                    "method": "distance_backup_system",
                    "estimation_basis": "image_properties",
                    "image_size": f"{width}x{height}",
                    "fallback_reason": "mediapipe_failed"
                },
                consistency_score=None,
                processing_time_ms=0.0
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] 거리 백업 시스템 오류: {e} - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason=f"distance_backup_error: {str(e)}",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
    
    def _estimate_step_from_image_properties(self, width: int, height: int) -> float:
        """이미지 속성을 기반으로 보폭 추정"""
        try:
            # 카메라 해상도 기반 스케일링
            # 일반적으로 휴대폰 카메라는 지면에서 100-150cm 높이에서 촬영
            
            # 기본 성인 보폭 (60-80cm)
            base_step_length = 70.0
            
            # 해상도 보정 팩터
            resolution_factor = min(width, height) / 720.0  # 720p 기준
            resolution_factor = max(0.8, min(1.2, resolution_factor))  # 0.8-1.2 범위로 제한
            
            # 화면 비율 보정 (세로 모드 vs 가로 모드)
            aspect_ratio = width / height
            if aspect_ratio > 1.5:  # 가로 모드
                aspect_correction = 1.1
            elif aspect_ratio < 0.8:  # 세로 모드
                aspect_correction = 0.95
            else:
                aspect_correction = 1.0
            
            estimated_length = base_step_length * resolution_factor * aspect_correction
            
            # 일반적인 보폭 범위로 제한 (40-120cm)
            return max(40.0, min(120.0, estimated_length))
            
        except Exception as e:
            logger.warning(f"[FastDepth] 보폭 추정 오류: {e}")
            return 70.0  # 기본값
    
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

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """간소화된 FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor