"""새로운 IMU 통합 시스템용 간소화된 FastDepth 프로세서

이 모듈은 IMU 융합 프로세서와 함께 사용되며 보조적인 역할을 합니다:
- 기본적인 이미지 전처리
- 레거시 호환성 유지
- 새로운 통합 시스템으로의 데이터 전달
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
    """IMU 통합 시스템용 간소화된 FastDepth 프로세서 (변수명/구조 통일, 신뢰도/평균 보폭 개선)"""
    def __init__(self):
        # 시각장애인 특화 설정으로 베이스 클래스 초기화
        super().__init__(get_visual_impairment_config())
        
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        # 베이스 클래스에서 recent_steps를 관리하므로 제거
        logger.info("[FastDepth] 간소화된 프로세서 초기화 완료 - IMU 통합 시스템 사용 (시각장애인 특화)")

    async def process_frame_for_measurement(
        self, 
        cv_image: np.ndarray, 
        user_id: str = 'current_user',
        imu_data: Optional[Dict] = None,
        enable_advanced_fusion: bool = True
    ) -> Optional[StepCalculationResult]:
        start_time = time.time()
        try:
            logger.info(f"[FastDepth] 새로운 통합 시스템으로 측정 시작: {user_id}")
            if cv_image is None or cv_image.size == 0:
                raise ValueError("유효하지 않은 이미지")
            height, width = cv_image.shape[:2]
            logger.debug(f"[FastDepth] 이미지 크기: {width}x{height}")
            if enable_advanced_fusion and imu_data:
                result = await self._use_integrated_imu_system(cv_image, imu_data, user_id)
            else:
                result = await self._use_basic_mediapipe_system(cv_image, user_id)
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
                    "processor_version": "simplified_imu_integrated",
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
                # IMU 데이터에서 추정 정보 추출 시도
                estimated_distance_cm = None
                estimated_step_count = None
                
                if imu_data:
                    estimated_distance = imu_data.get('estimated_distance')
                    estimated_distance_cm = estimated_distance * 100 if estimated_distance else None
                    estimated_step_count = imu_data.get('estimated_step_count')
                
                fallback_result = self.create_fallback_step_result(
                    reason=f"fastdepth_processing_error: {str(e)}",
                    estimated_distance_cm=estimated_distance_cm,
                    estimated_step_count=estimated_step_count
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
    
    async def _use_integrated_imu_system(self, cv_image: np.ndarray, imu_data: Dict, user_id: str) -> Optional[StepCalculationResult]:
        """IMU 통합 시스템을 사용한 고급 처리"""
        try:
            from utils.imu_fusion_processor import get_imu_fusion_processor, IMUData
            
            # IMU 데이터 변환
            imu_sensor_data = IMUData(
                accelerometer=tuple(imu_data.get('accelerometer', [0.0, 0.0, 9.81])),
                gyroscope=tuple(imu_data.get('gyroscope', [0.0, 0.0, 0.0])),
                magnetometer=tuple(imu_data.get('magnetometer', [0.0, 0.0, 0.0])) if imu_data.get('magnetometer') else None,
                timestamp=imu_data.get('timestamp', time.time()),
                device_orientation=imu_data.get('device_orientation', 'portrait')
            )
            
            # IMU 융합 프로세서 가져오기
            imu_processor = get_imu_fusion_processor()
            
            # 완전한 측정 사이클 실행
            integrated_result = imu_processor.process_complete_measurement_cycle(cv_image, imu_sensor_data)
            
            if integrated_result['success']:
                # 융합된 발 위치 데이터에서 보폭 계산
                fusion_results = integrated_result.get('fusion_results', {})
                
                left_pos = fusion_results.get('left_foot')
                right_pos = fusion_results.get('right_foot')
                
                if left_pos and right_pos:
                    # 두 발 사이의 거리 계산 (보폭)
                    distance = self._calculate_foot_distance(left_pos, right_pos)
                    step_length_cm = distance * 100  # 미터를 센티미터로 변환
                    
                    # 신뢰도 계산 (두 발의 융합 신뢰도 평균)
                    confidence = (self._extract_confidence(left_pos) + self._extract_confidence(right_pos)) / 2
                    
                    # 걸음 상태 정보 반영
                    walking_state = integrated_result.get('step_analysis', {}).get('walking_state', {})
                    if walking_state.get('is_walking', False):
                        confidence *= 1.1  # 걷고 있는 상태면 신뢰도 증가
                    
                    return StepCalculationResult(
                        step_length_cm=round(step_length_cm, 1),
                        confidence=min(0.95, max(self.config.acceptable_confidence, confidence)),
                        step_count=1,
                        tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                        accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                        measurement_method=StepMeasurementMethod.IMU_SENSOR,
                        timestamp=datetime.now(),
                        source_data={
                            "method": "imu_integrated_system",
                            "processing_time_ms": integrated_result.get('processing_time_ms', 0.0),
                            "camera_stable": integrated_result.get('imu_data', {}).get('camera_stable', False),
                            "walking_detected": walking_state.get('is_walking', False),
                            "step_frequency": walking_state.get('step_frequency', 0),
                            "fusion_quality": "high"
                        },
                        consistency_score=None,
                        processing_time_ms=integrated_result.get('processing_time_ms', 0.0)
                    )
                
                elif left_pos or right_pos:
                    # 한 발만 감지된 경우 추정
                    detected_foot = left_pos or right_pos
                    estimated_step_cm = self.config.typical_step_length_cm  # 기본 추정값
                    confidence = self._extract_confidence(detected_foot) * 0.7  # 단일 발이므로 신뢰도 감소
                    
                    return StepCalculationResult(
                        step_length_cm=estimated_step_cm,
                        confidence=confidence,
                        step_count=1,
                        tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                        accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                        measurement_method=StepMeasurementMethod.IMU_SENSOR,
                        timestamp=datetime.now(),
                        source_data={
                            "method": "imu_integrated_single_foot",
                            "fusion_quality": "medium"
                        },
                        consistency_score=None,
                        processing_time_ms=integrated_result.get('processing_time_ms', 0.0)
                    )
            
            logger.warning("[FastDepth] IMU 통합 시스템 결과 없음 - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason="imu_integration_failed",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] IMU 통합 시스템 오류: {e} - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason=f"imu_system_error: {str(e)}",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
    
    async def _use_basic_mediapipe_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """기본 MediaPipe 전용 처리 (발 특화 감지 및 IMU 백업 포함)"""
        try:
            from utils.mediapipe_pose_processor import get_mediapipe_pose_processor
            
            # MediaPipe 프로세서 가져오기
            mediapipe_processor = get_mediapipe_pose_processor(enable_imu_fusion=False)
            
            # 1단계: 강화된 발 키포인트 감지 시도
            keypoints = mediapipe_processor.extract_foot_keypoints_enhanced(cv_image)
            
            if not keypoints:
                logger.warning("[FastDepth] 모든 MediaPipe 발 키포인트 감지 방법 실패")
                
                # 2단계: IMU 백업 시스템 사용 (가상 IMU 데이터로 추정)
                logger.info("[FastDepth] IMU 백업 시스템으로 전환")
                return await self._use_imu_backup_system(cv_image, user_id)
            
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
                        "method": "basic_mediapipe",
                        "keypoint_types": f"{left.keypoint_type}-{right.keypoint_type}",
                        "fusion_quality": "basic"
                    },
                    consistency_score=None,
                    processing_time_ms=0.0
                )
            
            # 시각장애인을 위한 fallback 실행
            return self.create_fallback_step_result(
                reason="basic_mediapipe_no_valid_keypoints",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] 기본 MediaPipe 처리 오류: {e} - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason=f"basic_mediapipe_error: {str(e)}",
                estimated_distance_cm=None,
                estimated_step_count=None
            )
    
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
    
    async def _use_imu_backup_system(self, cv_image: np.ndarray, user_id: str) -> Optional[StepCalculationResult]:
        """IMU 기반 백업 측정 시스템 - MediaPipe 실패 시 사용"""
        try:
            logger.info("[FastDepth] IMU 백업 시스템 시작")
            
            # 이미지 크기 기반 대략적 스케일 추정
            height, width = cv_image.shape[:2]
            
            # 일반적인 보폭 추정 (성인 기준)
            # 카메라 높이와 각도를 고려한 추정
            estimated_step_length_cm = self._estimate_step_from_image_properties(width, height)
            
            # IMU 센서가 없으므로 가속도 패턴 분석 시뮬레이션
            # 실제 앱에서는 Flutter에서 전달되는 IMU 데이터를 사용
            confidence = self._calculate_imu_confidence(cv_image)
            
            logger.info(f"[FastDepth] IMU 백업 추정 보폭: {estimated_step_length_cm}cm, 신뢰도: {confidence:.3f}")
            
            return StepCalculationResult(
                step_length_cm=round(estimated_step_length_cm, 1),
                confidence=confidence,
                step_count=1,
                tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                measurement_method=StepMeasurementMethod.IMU_SENSOR,
                timestamp=datetime.now(),
                source_data={
                    "method": "imu_backup_system",
                    "estimation_basis": "image_properties",
                    "image_size": f"{width}x{height}",
                    "fallback_reason": "mediapipe_failed"
                },
                consistency_score=None,
                processing_time_ms=0.0
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] IMU 백업 시스템 오류: {e} - fallback 실행")
            # 시각장애인을 위한 무조건 fallback 실행
            return self.create_fallback_step_result(
                reason=f"imu_backup_error: {str(e)}",
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
    
    def _calculate_imu_confidence(self, cv_image: np.ndarray) -> float:
        """IMU 백업 시스템의 신뢰도 계산"""
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
            logger.warning(f"[FastDepth] IMU 신뢰도 계산 오류: {e}")
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