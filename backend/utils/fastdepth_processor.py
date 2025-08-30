"""새로운 IMU 통합 시스템용 간소화된 FastDepth 프로세서

이 모듈은 IMU 융합 프로세서와 함께 사용되며 보조적인 역할을 합니다:
- 기본적인 이미지 전처리
- 레거시 호환성 유지
- 새로운 통합 시스템으로의 데이터 전달
"""

import time
import logging
import numpy as np
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
        """기본 MediaPipe 전용 처리 (IMU 없음)"""
        try:
            from utils.mediapipe_pose_processor import get_mediapipe_pose_processor
            
            # MediaPipe 프로세서 가져오기
            mediapipe_processor = get_mediapipe_pose_processor(enable_imu_fusion=False)
            
            # 발 키포인트 감지
            keypoints = mediapipe_processor.extract_foot_keypoints(cv_image)
            
            if not keypoints:
                logger.warning("[FastDepth] MediaPipe 발 키포인트 감지 실패")
                return None
            
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