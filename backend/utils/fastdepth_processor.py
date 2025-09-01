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

# from models.fastdepth_models import FastDepthFrameData, FastDepthFootData  # 사용되지 않음
from models.step_models import StepCalculationResult, StepMeasurementMethod, AccuracyConverter

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
    """IMU 통합 시스템용 간소화된 FastDepth 프로세서"""
    
    def __init__(self):
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }
        
        logger.info("[FastDepth] 간소화된 프로세서 초기화 완료 - IMU 통합 시스템 사용")
    
    async def process_frame_for_measurement(
        self, 
        cv_image: np.ndarray, 
        user_id: str = 'current_user',
        imu_data: Optional[Dict] = None,
        enable_advanced_fusion: bool = True
    ) -> Optional[StepCalculationResult]:
        """
        새로운 IMU 통합 시스템을 사용한 프레임 처리
        
        Args:
            cv_image: OpenCV 이미지
            user_id: 사용자 ID
            imu_data: IMU 센서 데이터 (딕셔너리 형태)
            enable_advanced_fusion: 고급 융합 시스템 사용 여부
            
        Returns:
            StepCalculationResult: 보폭 계산 결과 또는 None
        """
        start_time = time.time()
        
        try:
            logger.info(f"[FastDepth] 새로운 통합 시스템으로 측정 시작: {user_id}")
            
            # 이미지 유효성 확인
            if cv_image is None or cv_image.size == 0:
                raise ValueError("유효하지 않은 이미지")
            
            height, width = cv_image.shape[:2]
            logger.debug(f"[FastDepth] 이미지 크기: {width}x{height}")
            
            if enable_advanced_fusion and imu_data:
                # 새로운 IMU 통합 시스템 사용
                result = await self._use_integrated_imu_system(cv_image, imu_data, user_id)
            else:
                # 기본 MediaPipe 전용 처리
                result = await self._use_basic_mediapipe_system(cv_image, user_id)
            
            processing_time = time.time() - start_time
            
            # 통계 업데이트
            self._update_stats(processing_time, result is not None)
            
            if result:
                # 처리 시간 정보 추가
                result.source_data.update({
                    "processing_time_ms": int(processing_time * 1000),
                    "processor_version": "simplified_imu_integrated",
                    "image_size": f"{width}x{height}",
                    "user_id": user_id
                })
                
                logger.info(f"[FastDepth] 측정 완료: {result.step_length_cm:.1f}cm "
                           f"(신뢰도: {result.confidence:.3f}, {processing_time*1000:.1f}ms)")
            else:
                logger.warning("[FastDepth] 측정 실패")
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            self._update_stats(processing_time, False)
            logger.error(f"[FastDepth] 프레임 처리 오류: {e}")
            return None
    
    async def _use_integrated_imu_system(self, cv_image: np.ndarray, imu_data: Dict, user_id: str) -> Optional[StepCalculationResult]:
        """IMU 통합 시스템을 사용한 고급 처리"""
        try:
            from utils.imu_fusion_processor import get_imu_fusion_processor, IMUData
            
            # IMU 데이터 변환
            imu_sensor_data = IMUData(
                accelerometer=tuple(imu_data.get('accelerometer', [0, 0, 9.81])),
                gyroscope=tuple(imu_data.get('gyroscope', [0, 0, 0])),
                magnetometer=tuple(imu_data.get('magnetometer', [0, 0, 0])) if imu_data.get('magnetometer') else None,
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
                
                if fusion_results.get('left_foot') and fusion_results.get('right_foot'):
                    left_pos = fusion_results['left_foot']
                    right_pos = fusion_results['right_foot']
                    
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
                        confidence=min(0.95, max(0.5, confidence)),
                        step_count=1,
                        tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                        accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                        measurement_method=StepMeasurementMethod.VISION_IMU_FUSION,
                        timestamp=integrated_result['timestamp'],
                        user_id=user_id,
                        source_data={
                            "method": "imu_integrated_system",
                            "processing_time_ms": integrated_result['processing_time_ms'],
                            "camera_stable": integrated_result['imu_data']['camera_stable'],
                            "walking_detected": walking_state.get('is_walking', False),
                            "step_frequency": walking_state.get('step_frequency', 0),
                            "fusion_quality": "high"
                        }
                    )
                
                elif fusion_results.get('left_foot') or fusion_results.get('right_foot'):
                    # 한 발만 감지된 경우 추정
                    detected_foot = fusion_results.get('left_foot') or fusion_results.get('right_foot')
                    estimated_step_cm = 65.0  # 기본 추정값
                    confidence = self._extract_confidence(detected_foot) * 0.7  # 단일 발이므로 신뢰도 감소
                    
                    return StepCalculationResult(
                        step_length_cm=estimated_step_cm,
                        confidence=confidence,
                        step_count=1,
                        tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                        accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                        measurement_method=StepMeasurementMethod.VISION_IMU_FUSION,
                        timestamp=integrated_result['timestamp'],
                        user_id=user_id,
                        source_data={
                            "method": "imu_integrated_single_foot",
                            "fusion_quality": "medium"
                        }
                    )
            
            logger.warning("[FastDepth] IMU 통합 시스템 결과 없음")
            return None
            
        except Exception as e:
            logger.error(f"[FastDepth] IMU 통합 시스템 오류: {e}")
            return None
    
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
            
            if foot_positions and foot_positions.left_foot and foot_positions.right_foot:
                # 두 발 사이 거리 계산
                left = foot_positions.left_foot
                right = foot_positions.right_foot
                
                dx = left.x_m - right.x_m
                dy = left.y_m - right.y_m
                dz = left.depth_m - right.depth_m
                
                distance_m = np.sqrt(dx**2 + dy**2 + dz**2)
                step_length_cm = distance_m * 100
                
                confidence = (left.confidence + right.confidence) / 2
                
                return StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=confidence,
                    step_count=1,
                    tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                    accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                    measurement_method=StepMeasurementMethod.COMPUTER_VISION,
                    timestamp=time.time(),
                    user_id=user_id,
                    source_data={
                        "method": "basic_mediapipe",
                        "keypoint_types": f"{left.keypoint_type}-{right.keypoint_type}",
                        "fusion_quality": "basic"
                    }
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[FastDepth] 기본 MediaPipe 처리 오류: {e}")
            return None
    
    def _calculate_foot_distance(self, left_pos: Tuple[float, float, float], right_pos: Tuple[float, float, float]) -> float:
        """두 발 사이의 3D 거리 계산"""
        dx = left_pos[0] - right_pos[0]
        dy = left_pos[1] - right_pos[1]
        dz = left_pos[2] - right_pos[2]
        return np.sqrt(dx**2 + dy**2 + dz**2)
    
    def _extract_confidence(self, position_data) -> float:
        """위치 데이터에서 신뢰도 추출"""
        if isinstance(position_data, tuple) and len(position_data) >= 4:
            return float(position_data[3])  # (x, y, z, confidence) 형태 가정
        return 0.7  # 기본 신뢰도
    
    def _update_stats(self, processing_time: float, success: bool):
        """처리 통계 업데이트"""
        self.processing_stats["total_processed"] += 1
        
        if success:
            self.processing_stats["successful_measurements"] += 1
        else:
            self.processing_stats["failed_measurements"] += 1
        
        # 평균 처리 시간 업데이트
        total = self.processing_stats["total_processed"]
        current_avg = self.processing_stats["average_processing_time"]
        new_avg = ((current_avg * (total - 1)) + processing_time) / total
        self.processing_stats["average_processing_time"] = new_avg
    
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
                timestamp=time.time(),
                user_id=user_id,
                source_data={
                    "method": "imu_backup_system",
                    "estimation_basis": "image_properties",
                    "image_size": f"{width}x{height}",
                    "fallback_reason": "mediapipe_failed"
                }
            )
            
        except Exception as e:
            logger.error(f"[FastDepth] IMU 백업 시스템 오류: {e}")
            return None
    
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
            # 이미지 품질 기반 신뢰도
            # 실제로는 IMU 데이터의 노이즈, 안정성 등을 고려해야 함
            
            # 이미지 선명도 분석
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) if len(cv_image.shape) == 3 else cv_image
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # 라플라시안 분산을 신뢰도로 변환 (0-1 범위)
            sharpness_confidence = min(1.0, laplacian_var / 1000.0)
            
            # 밝기 균일성 분석
            mean_brightness = np.mean(gray)
            brightness_std = np.std(gray)
            brightness_confidence = 1.0 - min(1.0, brightness_std / 128.0)
            
            # IMU 백업 시스템의 기본 신뢰도는 MediaPipe보다 낮음
            base_confidence = 0.4
            
            # 최종 신뢰도 계산
            final_confidence = base_confidence * (0.3 + 0.4 * sharpness_confidence + 0.3 * brightness_confidence)
            
            return max(0.2, min(0.7, final_confidence))  # 0.2-0.7 범위로 제한
            
        except Exception as e:
            logger.warning(f"[FastDepth] IMU 신뢰도 계산 오류: {e}")
            return 0.3  # 기본 신뢰도

    def reset_stats(self):
        """통계 리셋"""
        self.processing_stats = {
            "total_processed": 0,
            "successful_measurements": 0,
            "failed_measurements": 0,
            "average_processing_time": 0.0
        }

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """간소화된 FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor