# utils/mediapipe_pose_processor.py
import cv2
import numpy as np
import mediapipe as mp
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

from models.step_models import StepCalculationResult, StepMeasurementMethod, TrackingQuality, AccuracyLevel
from utils.imu_fusion_processor import IMUFusionProcessor

logger = logging.getLogger("uvicorn.error")

@dataclass
class MediaPipeLandmark:
    """MediaPipe 랜드마크 데이터 클래스"""
    x: float  # 정규화된 좌표 (0-1)
    y: float  # 정규화된 좌표 (0-1)
    z: float  # 깊이 (상대적)
    visibility: float  # 가시성 (0-1)
    presence: float   # 존재 확률 (0-1)

@dataclass 
class FootKeypoints:
    """발 키포인트 데이터 클래스"""
    left_heel: Optional[MediaPipeLandmark] = None
    right_heel: Optional[MediaPipeLandmark] = None
    left_foot_index: Optional[MediaPipeLandmark] = None  # 발끝
    right_foot_index: Optional[MediaPipeLandmark] = None  # 발끝
    timestamp: float = 0.0
    confidence_score: float = 0.0

@dataclass
class Enhanced3DFootPosition:
    """향상된 3D 발 위치 데이터"""
    x: float
    y: float  
    z: float
    confidence: float
    keypoint_type: str  # 'heel', 'toe'
    foot_side: str     # 'left', 'right'
    timestamp: float
    imu_enhanced: bool = False
    pose_confidence: float = 0.0
    depth_confidence: float = 0.0

class MediaPipePoseProcessor:
    """
    MediaPipe Pose를 사용한 발 키포인트 감지 및 3D 위치 추정
    
    주요 기능:
    - MediaPipe Pose로 발 키포인트 감지
    - FastDepth와 데이터 융합하여 정확한 3D 좌표 생성
    - IMU 센서와의 융합으로 움직임 예측 및 안정화
    - 칼만 필터 적용으로 부드러운 추적
    """
    
    def __init__(self, enable_imu_fusion: bool = True):
        # MediaPipe Pose 초기화
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils
        
        # 최적화된 신뢰도 설정 (발 키포인트 감지를 위해 낮춤)
        self.default_detection_confidence = 0.3
        self.default_tracking_confidence = 0.3
        
        # 최적화된 Pose 모델 설정 - 발 키포인트 감지에 최적화
        self.pose = self.mp_pose.Pose(
            static_image_mode=True,   # 정적 이미지 모드로 변경 (각 프레임 독립 처리)
            model_complexity=2,       # Heavy 모델 사용 (최고 정확도)
            smooth_landmarks=False,   # 정적 모드에서는 불필요
            enable_segmentation=False,
            smooth_segmentation=False,
            min_detection_confidence=self.default_detection_confidence,  # 낮춘 감지 신뢰도
            min_tracking_confidence=self.default_tracking_confidence     # 낮춘 추적 신뢰도
        )
        
        # 발 관련 랜드마크 인덱스 (MediaPipe Pose 33개 포인트 중)
        self.FOOT_LANDMARKS = {
            'LEFT_HEEL': 29,
            'RIGHT_HEEL': 30,
            'LEFT_FOOT_INDEX': 31,  # 왼발 엄지발가락
            'RIGHT_FOOT_INDEX': 32  # 오른발 엄지발가락
        }
        
        # 3D 좌표 변환을 위한 카메라 매개변수
        self.camera_params = {
            'focal_length': 800.0,  # 초점 거리 (픽셀)
            'cx': 320.0,           # 주점 x
            'cy': 240.0,           # 주점 y
            'scale_factor': 1000.0  # mm to m 변환
        }
        
        # FastDepth 통합을 위한 깊이 프로세서
        try:
            from utils.fastdepth_processor import get_fastdepth_processor
            self.depth_processor = get_fastdepth_processor()
            self.depth_integration_enabled = True
            logger.info("[MediaPipe] FastDepth 프로세서 통합 완료")
        except Exception as e:
            logger.warning(f"[MediaPipe] FastDepth 통합 실패: {e}")
            self.depth_processor = None
            self.depth_integration_enabled = False
        
        # IMU 융합 프로세서
        self.imu_fusion_enabled = enable_imu_fusion
        if enable_imu_fusion:
            try:
                self.imu_processor = IMUFusionProcessor()
                logger.info("[MediaPipe] IMU 융합 프로세서 초기화 완료")
            except Exception as e:
                logger.warning(f"[MediaPipe] IMU 융합 초기화 실패: {e}")
                self.imu_processor = None
                self.imu_fusion_enabled = False
        
        # 성능 통계
        self.processing_stats = {
            'total_frames': 0,
            'successful_detections': 0,
            'failed_detections': 0,
            'average_processing_time': 0.0,
            'pose_confidence_avg': 0.0,
            'depth_fusion_success': 0
        }
        
        # 최근 키포인트 히스토리 (칼만 필터용)
        self.keypoint_history: List[FootKeypoints] = []
        self.max_history_size = 30
        
        logger.info("[MediaPipe] Pose 프로세서 초기화 완료")
    
    def create_pose_with_confidence(self, detection_confidence: float, tracking_confidence: float = None):
        """특정 신뢰도로 새로운 Pose 인스턴스 생성 (최적화된 설정)"""
        if tracking_confidence is None:
            tracking_confidence = detection_confidence
            
        return self.mp_pose.Pose(
            static_image_mode=True,   # 정적 이미지 모드
            model_complexity=2,       # Heavy 모델 (최고 정확도)
            smooth_landmarks=False,   # 정적 모드에서는 불필요
            enable_segmentation=False,
            smooth_segmentation=False,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence
        )
    
    def extract_foot_keypoints(self, cv_image: np.ndarray, confidence_threshold: float = None) -> Optional[FootKeypoints]:
        """
        MediaPipe Pose로 발 키포인트 추출
        
        Args:
            cv_image: OpenCV 이미지 (BGR)
            confidence_threshold: 커스텀 신뢰도 임계값 (없으면 기본값 사용)
            
        Returns:
            FootKeypoints: 발 키포인트 데이터 또는 None
        """
        start_time = time.time()
        
        try:
            # BGR을 RGB로 변환 (MediaPipe 요구사항)
            rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            height, width = cv_image.shape[:2]
            
            # 이미지 전처리 - 밝기와 대비 향상
            rgb_image = cv2.convertScaleAbs(rgb_image, alpha=1.2, beta=10)
            
            # MediaPipe에 이미지 크기 정보 명시적 제공 (경고 해결)
            rgb_image.flags.writeable = False  # 성능 최적화
            
            # 커스텀 신뢰도가 지정된 경우 임시 Pose 인스턴스 생성
            pose_instance = self.pose
            if confidence_threshold is not None:
                logger.info(f"[MediaPipe] 커스텀 신뢰도 사용: {confidence_threshold}")
                pose_instance = self.create_pose_with_confidence(confidence_threshold)
            
            # Pose 감지 수행
            results = pose_instance.process(rgb_image)
            
            if not results.pose_landmarks:
                logger.debug("[MediaPipe] Pose 감지 실패")
                self.processing_stats['failed_detections'] += 1
                return None
            
            # 발 키포인트 추출
            landmarks = results.pose_landmarks.landmark
            
            # 각 발 키포인트의 가시성과 존재 확률 검사
            foot_keypoints = FootKeypoints(timestamp=time.time())
            confidence_scores = []
            
            # 왼발 뒤꿈치
            left_heel_idx = self.FOOT_LANDMARKS['LEFT_HEEL']
            if left_heel_idx < len(landmarks):
                lh = landmarks[left_heel_idx]
                if lh.visibility > 0.2 and lh.presence > 0.2:  # 임계값 대폭 완화
                    foot_keypoints.left_heel = MediaPipeLandmark(
                        x=lh.x, y=lh.y, z=lh.z,
                        visibility=lh.visibility, presence=lh.presence
                    )
                    confidence_scores.append(lh.visibility * lh.presence)
            
            # 오른발 뒤꿈치
            right_heel_idx = self.FOOT_LANDMARKS['RIGHT_HEEL']
            if right_heel_idx < len(landmarks):
                rh = landmarks[right_heel_idx]
                if rh.visibility > 0.2 and rh.presence > 0.2:  # 임계값 대폭 완화
                    foot_keypoints.right_heel = MediaPipeLandmark(
                        x=rh.x, y=rh.y, z=rh.z,
                        visibility=rh.visibility, presence=rh.presence
                    )
                    confidence_scores.append(rh.visibility * rh.presence)
            
            # 왼발 엄지발가락
            left_toe_idx = self.FOOT_LANDMARKS['LEFT_FOOT_INDEX']
            if left_toe_idx < len(landmarks):
                lt = landmarks[left_toe_idx]
                if lt.visibility > 0.2 and lt.presence > 0.2:  # 임계값 대폭 완화
                    foot_keypoints.left_foot_index = MediaPipeLandmark(
                        x=lt.x, y=lt.y, z=lt.z,
                        visibility=lt.visibility, presence=lt.presence
                    )
                    confidence_scores.append(lt.visibility * lt.presence)
            
            # 오른발 엄지발가락
            right_toe_idx = self.FOOT_LANDMARKS['RIGHT_FOOT_INDEX']
            if right_toe_idx < len(landmarks):
                rt = landmarks[right_toe_idx]
                if rt.visibility > 0.2 and rt.presence > 0.2:  # 임계값 대폭 완화
                    foot_keypoints.right_foot_index = MediaPipeLandmark(
                        x=rt.x, y=rt.y, z=rt.z,
                        visibility=rt.visibility, presence=rt.presence
                    )
                    confidence_scores.append(rt.visibility * rt.presence)
            
            # 전체 신뢰도 계산
            if confidence_scores:
                foot_keypoints.confidence_score = sum(confidence_scores) / len(confidence_scores)
                self.processing_stats['successful_detections'] += 1
                
                # 히스토리에 추가
                self.keypoint_history.append(foot_keypoints)
                if len(self.keypoint_history) > self.max_history_size:
                    self.keypoint_history.pop(0)
                
                processing_time = time.time() - start_time
                self._update_processing_stats(processing_time, foot_keypoints.confidence_score)
                
                logger.debug(f"[MediaPipe] 키포인트 추출 성공 - 신뢰도: {foot_keypoints.confidence_score:.3f}")
                return foot_keypoints
            else:
                logger.debug("[MediaPipe] 유효한 발 키포인트 없음")
                self.processing_stats['failed_detections'] += 1
                return None
                
        except Exception as e:
            logger.error(f"[MediaPipe] 키포인트 추출 오류: {e}")
            self.processing_stats['failed_detections'] += 1
            return None
    
    def convert_to_3d_coordinates(self, 
                                  keypoints: FootKeypoints, 
                                  cv_image: np.ndarray,
                                  depth_map: Optional[np.ndarray] = None) -> List[Enhanced3DFootPosition]:
        """
        2D 키포인트를 3D 좌표로 변환 (깊이 정보 및 IMU 융합)
        
        Args:
            keypoints: MediaPipe 발 키포인트
            cv_image: 원본 이미지
            depth_map: FastDepth 깊이 맵 (선택사항)
            
        Returns:
            List[Enhanced3DFootPosition]: 3D 발 위치 리스트
        """
        height, width = cv_image.shape[:2]
        foot_positions = []
        
        # 각 키포인트를 3D로 변환
        keypoint_pairs = [
            (keypoints.left_heel, 'heel', 'left'),
            (keypoints.right_heel, 'heel', 'right'),
            (keypoints.left_foot_index, 'big_toe', 'left'),
            (keypoints.right_foot_index, 'big_toe', 'right')
        ]
        
        for landmark, keypoint_type, foot_side in keypoint_pairs:
            if landmark is None:
                continue
            
            try:
                # 픽셀 좌표로 변환
                pixel_x = int(landmark.x * width)
                pixel_y = int(landmark.y * height)
                
                # 깊이 정보 획득
                depth_value = None
                depth_confidence = 0.0
                
                if depth_map is not None and self.depth_integration_enabled:
                    # FastDepth 깊이 맵에서 깊이 값 추출
                    if 0 <= pixel_x < width and 0 <= pixel_y < height:
                        # 주변 픽셀 평균으로 노이즈 감소
                        kernel_size = 5
                        y_start = max(0, pixel_y - kernel_size//2)
                        y_end = min(height, pixel_y + kernel_size//2 + 1)
                        x_start = max(0, pixel_x - kernel_size//2)
                        x_end = min(width, pixel_x + kernel_size//2 + 1)
                        
                        depth_patch = depth_map[y_start:y_end, x_start:x_end]
                        valid_depths = depth_patch[depth_patch > 0]
                        
                        if len(valid_depths) > 0:
                            depth_value = np.median(valid_depths)
                            depth_confidence = min(1.0, len(valid_depths) / (kernel_size * kernel_size))
                            self.processing_stats['depth_fusion_success'] += 1
                
                # MediaPipe z 값을 사용하여 깊이 추정 (보조적)
                if depth_value is None:
                    # MediaPipe z는 상대적 깊이이므로 실제 거리로 변환
                    # 평균적인 사람의 키(1.7m)를 기준으로 스케일링
                    estimated_depth = 1.5 + landmark.z * 0.5  # 1.0~2.0m 범위
                    depth_value = estimated_depth
                    depth_confidence = landmark.visibility * 0.6  # MediaPipe 신뢰도 기반
                
                # 3D 좌표 계산 (카메라 좌표계)
                # 정규화된 좌표를 실제 3D 좌표로 변환
                world_x = (landmark.x - 0.5) * 2.0  # -1 ~ 1 범위
                world_y = (landmark.y - 0.5) * 2.0  # -1 ~ 1 범위
                world_z = depth_value
                
                # 카메라 매개변수를 사용한 실제 좌표 계산
                if depth_value > 0:
                    actual_x = world_x * depth_value
                    actual_y = world_y * depth_value
                    actual_z = depth_value
                else:
                    actual_x, actual_y, actual_z = world_x, world_y, 1.5
                
                # IMU 센서와 융합 (선택적)
                imu_enhanced = False
                if self.imu_fusion_enabled and self.imu_processor:
                    try:
                        # IMU 데이터로 위치 보정
                        corrected_pos = self.imu_processor.fuse_with_vision(
                            vision_x=actual_x, vision_y=actual_y, vision_z=actual_z,
                            foot_side=foot_side, timestamp=keypoints.timestamp
                        )
                        if corrected_pos:
                            actual_x, actual_y, actual_z = corrected_pos
                            imu_enhanced = True
                            logger.debug(f"[MediaPipe] IMU 융합 적용: {foot_side} {keypoint_type}")
                    except Exception as e:
                        logger.debug(f"[MediaPipe] IMU 융합 실패: {e}")
                
                # 전체 신뢰도 계산
                pose_confidence = landmark.visibility * landmark.presence
                total_confidence = (pose_confidence + depth_confidence) / 2
                
                foot_position = Enhanced3DFootPosition(
                    x=actual_x,
                    y=actual_y,
                    z=actual_z,
                    confidence=total_confidence,
                    keypoint_type=keypoint_type,
                    foot_side=foot_side,
                    timestamp=keypoints.timestamp,
                    imu_enhanced=imu_enhanced,
                    pose_confidence=pose_confidence,
                    depth_confidence=depth_confidence
                )
                
                foot_positions.append(foot_position)
                
                logger.debug(f"[MediaPipe] 3D 변환 완료: {foot_side} {keypoint_type} -> "
                           f"({actual_x:.2f}, {actual_y:.2f}, {actual_z:.2f}) 신뢰도: {total_confidence:.3f}")
                
            except Exception as e:
                logger.error(f"[MediaPipe] 3D 좌표 변환 오류 ({foot_side} {keypoint_type}): {e}")
                continue
        
        return foot_positions
    
    async def process_frame_for_step_measurement(self, 
                                               cv_image: np.ndarray, 
                                               user_id: str = 'current_user',
                                               enable_depth_fusion: bool = True,
                                               confidence_threshold: float = None) -> Optional[StepCalculationResult]:
        """
        MediaPipe Pose 기반 보폭 측정
        
        Args:
            cv_image: 입력 이미지
            user_id: 사용자 ID
            enable_depth_fusion: 깊이 융합 활성화 여부
            
        Returns:
            StepCalculationResult: 측정 결과 또는 None
        """
        start_time = time.time()
        
        try:
            # 1. MediaPipe로 발 키포인트 추출 (커스텀 신뢰도 적용)
            keypoints = self.extract_foot_keypoints(cv_image, confidence_threshold)
            if not keypoints:
                logger.warning("[MediaPipe] 발 키포인트 추출 실패")
                return None
            
            # 2. FastDepth 깊이 맵 생성 (선택적)
            depth_map = None
            if enable_depth_fusion and self.depth_integration_enabled:
                try:
                    # FastDepth로 깊이 맵 생성
                    depth_result = self.depth_processor.process_image_for_depth(cv_image)
                    if depth_result:
                        depth_map = depth_result.get('depth_map')
                        logger.debug("[MediaPipe] FastDepth 깊이 맵 생성 성공")
                except Exception as e:
                    logger.debug(f"[MediaPipe] 깊이 맵 생성 실패: {e}")
            
            # 3. 3D 좌표 변환
            foot_positions_3d = self.convert_to_3d_coordinates(keypoints, cv_image, depth_map)
            
            if not foot_positions_3d:
                logger.warning("[MediaPipe] 3D 좌표 변환 실패")
                return None
            
            # 4. 보폭 계산
            step_result = self._calculate_step_length_from_positions(foot_positions_3d, user_id)
            
            if step_result:
                processing_time = time.time() - start_time
                step_result.source_data["processing_time_ms"] = round(processing_time * 1000, 1)
                step_result.source_data["mediapipe_keypoints"] = len(foot_positions_3d)
                step_result.source_data["depth_fusion_enabled"] = enable_depth_fusion and depth_map is not None
                step_result.source_data["imu_fusion_enabled"] = self.imu_fusion_enabled
                
                logger.info(f"[MediaPipe] 보폭 측정 완료: {step_result.step_length_cm:.1f}cm "
                           f"(신뢰도: {step_result.confidence:.3f}, 처리시간: {processing_time*1000:.1f}ms)")
            
            return step_result
            
        except Exception as e:
            logger.error(f"[MediaPipe] 프레임 처리 오류 (user: {user_id}): {e}")
            return None
    
    def _calculate_step_length_from_positions(self, 
                                            foot_positions: List[Enhanced3DFootPosition], 
                                            user_id: str) -> Optional[StepCalculationResult]:
        """3D 발 위치에서 보폭 계산"""
        try:
            # 1순위: 엄지발가락으로 보폭 계산 (가장 정확함)
            left_big_toe = None
            right_big_toe = None
            
            for pos in foot_positions:
                if pos.keypoint_type == 'big_toe' and pos.foot_side == 'left':
                    left_big_toe = pos
                elif pos.keypoint_type == 'big_toe' and pos.foot_side == 'right':
                    right_big_toe = pos
            
            # 엄지발가락이 있으면 우선 사용
            if left_big_toe and right_big_toe:
                # 두 엄지발가락 간의 3D 거리 계산
                dx = left_big_toe.x - right_big_toe.x
                dy = left_big_toe.y - right_big_toe.y
                dz = left_big_toe.z - right_big_toe.z
                
                step_length_m = (dx**2 + dy**2 + dz**2)**0.5
                step_length_cm = step_length_m * 100
                
                # 보정 (사람의 보폭은 일반적으로 50-100cm)
                step_length_cm = max(30.0, min(150.0, step_length_cm))
                
                # 신뢰도 계산
                confidence = (left_big_toe.confidence + right_big_toe.confidence) / 2
                
                # IMU 융합 보너스
                if left_big_toe.imu_enhanced or right_big_toe.imu_enhanced:
                    confidence = min(0.98, confidence + 0.1)
                
                result = StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=round(confidence, 3),
                    step_count=1,
                    tracking_quality=self._determine_tracking_quality(confidence),
                    accuracy_level=self._determine_accuracy_level(confidence),
                    measurement_method=StepMeasurementMethod.POSE_ESTIMATION,
                    timestamp=time.time(),
                    user_id=user_id,
                    source_data={
                        "method": "mediapipe_pose_3d_big_toe_distance",
                        "left_big_toe_confidence": round(left_big_toe.confidence, 3),
                        "right_big_toe_confidence": round(right_big_toe.confidence, 3),
                        "left_imu_enhanced": left_big_toe.imu_enhanced,
                        "right_imu_enhanced": right_big_toe.imu_enhanced,
                        "pose_detection_method": "MediaPipe Pose v1.0 - Big Toe Priority",
                        "depth_fusion_used": any(pos.depth_confidence > 0.5 for pos in foot_positions)
                    }
                )
                
                return result
            
            # 2순위: 발뒤꿈치로 보폭 계산 (엄지발가락이 없을 때)
            left_heel = None
            right_heel = None
            
            for pos in foot_positions:
                if pos.keypoint_type == 'heel' and pos.foot_side == 'left':
                    left_heel = pos
                elif pos.keypoint_type == 'heel' and pos.foot_side == 'right':
                    right_heel = pos
            
            if left_heel and right_heel:
                # 두 발 뒤꿈치 간의 3D 거리 계산
                dx = left_heel.x - right_heel.x
                dy = left_heel.y - right_heel.y
                dz = left_heel.z - right_heel.z
                
                step_length_m = (dx**2 + dy**2 + dz**2)**0.5
                step_length_cm = step_length_m * 100
                
                # 보정 (사람의 보폭은 일반적으로 50-100cm)
                step_length_cm = max(30.0, min(150.0, step_length_cm))
                
                # 신뢰도 계산
                confidence = (left_heel.confidence + right_heel.confidence) / 2
                
                # IMU 융합 보너스
                if left_heel.imu_enhanced or right_heel.imu_enhanced:
                    confidence = min(0.98, confidence + 0.1)
                
                result = StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=round(confidence, 3),
                    step_count=1,
                    tracking_quality=self._determine_tracking_quality(confidence),
                    accuracy_level=self._determine_accuracy_level(confidence),
                    measurement_method=StepMeasurementMethod.POSE_ESTIMATION,
                    timestamp=time.time(),
                    user_id=user_id,
                    source_data={
                        "method": "mediapipe_pose_3d_heel_distance",
                        "left_heel_confidence": round(left_heel.confidence, 3),
                        "right_heel_confidence": round(right_heel.confidence, 3),
                        "left_imu_enhanced": left_heel.imu_enhanced,
                        "right_imu_enhanced": right_heel.imu_enhanced,
                        "pose_detection_method": "MediaPipe Pose v1.0",
                        "depth_fusion_used": any(pos.depth_confidence > 0.5 for pos in foot_positions)
                    }
                )
                
                return result
            
            # 3순위: 엄지발가락과 발뒤꿈치가 모두 없으면 발끝으로 시도
            elif len(foot_positions) >= 2:
                # 가장 신뢰도 높은 두 발 위치 선택
                sorted_positions = sorted(foot_positions, key=lambda x: x.confidence, reverse=True)
                pos1, pos2 = sorted_positions[0], sorted_positions[1]
                
                dx = pos1.x - pos2.x
                dy = pos1.y - pos2.y
                dz = pos1.z - pos2.z
                
                step_length_m = (dx**2 + dy**2 + dz**2)**0.5
                step_length_cm = max(30.0, min(150.0, step_length_m * 100))
                
                confidence = (pos1.confidence + pos2.confidence) / 2 * 0.85  # 혼합 키포인트는 약간 낮은 신뢰도
                
                result = StepCalculationResult(
                    step_length_cm=round(step_length_cm, 1),
                    confidence=round(confidence, 3),
                    step_count=1,
                    tracking_quality=self._determine_tracking_quality(confidence),
                    accuracy_level=self._determine_accuracy_level(confidence),
                    measurement_method=StepMeasurementMethod.POSE_ESTIMATION,
                    timestamp=time.time(),
                    user_id=user_id,
                    source_data={
                        "method": "mediapipe_pose_mixed_keypoints_fallback",
                        "keypoint1": f"{pos1.foot_side}_{pos1.keypoint_type}",
                        "keypoint2": f"{pos2.foot_side}_{pos2.keypoint_type}",
                        "fallback_calculation": True,
                        "note": "엄지발가락과 발뒤꿈치 없음 - 혼합 키포인트 사용"
                    }
                )
                
                return result
            
            else:
                logger.warning("[MediaPipe] 보폭 계산을 위한 충분한 키포인트 없음")
                return None
                
        except Exception as e:
            logger.error(f"[MediaPipe] 보폭 계산 오류: {e}")
            return None
    
    def _determine_tracking_quality(self, confidence: float) -> TrackingQuality:
        """신뢰도 기반 추적 품질 결정"""
        if confidence >= 0.8:
            return TrackingQuality.HIGH
        elif confidence >= 0.6:
            return TrackingQuality.MEDIUM
        else:
            return TrackingQuality.LOW
    
    def _determine_accuracy_level(self, confidence: float) -> AccuracyLevel:
        """신뢰도 기반 정확도 수준 결정"""
        if confidence >= 0.85:
            return AccuracyLevel.PROFESSIONAL
        elif confidence >= 0.7:
            return AccuracyLevel.HIGH
        elif confidence >= 0.5:
            return AccuracyLevel.MEDIUM
        else:
            return AccuracyLevel.BASIC
    
    def _update_processing_stats(self, processing_time: float, confidence: float):
        """처리 통계 업데이트"""
        self.processing_stats['total_frames'] += 1
        
        # 평균 처리 시간 업데이트
        current_avg = self.processing_stats['average_processing_time']
        total_frames = self.processing_stats['total_frames']
        self.processing_stats['average_processing_time'] = (
            (current_avg * (total_frames - 1) + processing_time) / total_frames
        )
        
        # 평균 신뢰도 업데이트
        current_conf_avg = self.processing_stats['pose_confidence_avg']
        success_count = self.processing_stats['successful_detections']
        self.processing_stats['pose_confidence_avg'] = (
            (current_conf_avg * (success_count - 1) + confidence) / success_count
        )
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        total = self.processing_stats['total_frames']
        success_rate = self.processing_stats['successful_detections'] / total if total > 0 else 0
        
        return {
            "total_frames_processed": total,
            "success_rate": round(success_rate, 3),
            "average_processing_time_ms": round(self.processing_stats['average_processing_time'] * 1000, 1),
            "average_pose_confidence": round(self.processing_stats['pose_confidence_avg'], 3),
            "depth_fusion_success_rate": round(
                self.processing_stats['depth_fusion_success'] / max(1, self.processing_stats['successful_detections']), 3
            ),
            "imu_fusion_enabled": self.imu_fusion_enabled,
            "depth_integration_enabled": self.depth_integration_enabled
        }
    
    def reset_statistics(self):
        """통계 초기화"""
        self.processing_stats = {
            'total_frames': 0,
            'successful_detections': 0,
            'failed_detections': 0,
            'average_processing_time': 0.0,
            'pose_confidence_avg': 0.0,
            'depth_fusion_success': 0
        }
        logger.info("[MediaPipe] 처리 통계 초기화 완료")
    
    def extract_foot_keypoints_enhanced(self, cv_image: np.ndarray, 
                                        detection_confidence: float = None) -> Optional[FootKeypoints]:
        """
        발 특화 감지 알고리즘 - 여러 신뢰도와 전처리 기법을 사용한 강화된 발 키포인트 감지
        
        Args:
            cv_image: 입력 이미지
            detection_confidence: 감지 신뢰도 임계값
            
        Returns:
            FootKeypoints: 발 키포인트 또는 None
        """
        if detection_confidence is None:
            detection_confidence = self.default_detection_confidence
            
        logger.debug(f"[MediaPipe] 발 특화 감지 시작 - 신뢰도: {detection_confidence}")
        
        # 1단계: 기본 감지 시도
        result = self.extract_foot_keypoints(cv_image, detection_confidence)
        if result and result.confidence_score > 0.3:
            logger.debug(f"[MediaPipe] 기본 감지 성공 - 신뢰도: {result.confidence_score:.3f}")
            return result
        
        # 2단계: 낮은 신뢰도로 재시도
        logger.debug("[MediaPipe] 낮은 신뢰도로 재시도")
        result = self.extract_foot_keypoints(cv_image, 0.1)
        if result and result.confidence_score > 0.15:
            logger.debug(f"[MediaPipe] 낮은 신뢰도 감지 성공 - 신뢰도: {result.confidence_score:.3f}")
            return result
        
        # 3단계: 이미지 전처리 후 재시도
        logger.debug("[MediaPipe] 이미지 전처리 후 재시도")
        enhanced_images = self._enhance_image_for_foot_detection(cv_image)
        
        for i, enhanced_image in enumerate(enhanced_images):
            result = self.extract_foot_keypoints(enhanced_image, 0.2)
            if result and result.confidence_score > 0.2:
                logger.debug(f"[MediaPipe] 전처리 감지 성공 (방법 {i+1}) - 신뢰도: {result.confidence_score:.3f}")
                return result
        
        # 4단계: 하체 중심 감지 (발이 화면 하단에 있을 가능성)
        logger.debug("[MediaPipe] 하체 중심 감지 시도")
        lower_half_image = self._extract_lower_half(cv_image)
        if lower_half_image is not None:
            result = self.extract_foot_keypoints(lower_half_image, 0.15)
            if result:
                # 좌표를 전체 이미지로 변환
                result = self._adjust_coordinates_for_lower_half(result, cv_image.shape)
                if result.confidence_score > 0.15:
                    logger.debug(f"[MediaPipe] 하체 중심 감지 성공 - 신뢰도: {result.confidence_score:.3f}")
                    return result
        
        logger.debug("[MediaPipe] 모든 발 특화 감지 방법 실패")
        return None
    
    def _enhance_image_for_foot_detection(self, cv_image: np.ndarray) -> List[np.ndarray]:
        """발 감지를 위한 이미지 전처리 방법들"""
        enhanced_images = []
        
        try:
            # 방법 1: 대비 및 밝기 조정
            alpha = 1.3  # 대비
            beta = 20    # 밝기
            enhanced1 = cv2.convertScaleAbs(cv_image, alpha=alpha, beta=beta)
            enhanced_images.append(enhanced1)
            
            # 방법 2: 히스토그램 균등화
            if len(cv_image.shape) == 3:
                # 컬러 이미지의 경우
                yuv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2YUV)
                yuv[:,:,0] = cv2.equalizeHist(yuv[:,:,0])
                enhanced2 = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
            else:
                enhanced2 = cv2.equalizeHist(cv_image)
            enhanced_images.append(enhanced2)
            
            # 방법 3: 가우시안 블러를 사용한 노이즈 제거
            enhanced3 = cv2.GaussianBlur(cv_image, (3, 3), 0)
            enhanced_images.append(enhanced3)
            
            # 방법 4: 샤프닝 필터
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            enhanced4 = cv2.filter2D(cv_image, -1, kernel)
            # 값 범위 정규화
            enhanced4 = np.clip(enhanced4, 0, 255).astype(np.uint8)
            enhanced_images.append(enhanced4)
            
        except Exception as e:
            logger.warning(f"[MediaPipe] 이미지 전처리 오류: {e}")
        
        return enhanced_images
    
    def _extract_lower_half(self, cv_image: np.ndarray) -> Optional[np.ndarray]:
        """이미지의 하반부를 추출 (발이 보통 화면 하단에 위치)"""
        try:
            height, width = cv_image.shape[:2]
            # 하단 60%를 추출
            start_y = int(height * 0.4)
            return cv_image[start_y:, :]
        except Exception as e:
            logger.warning(f"[MediaPipe] 하반부 추출 오류: {e}")
            return None
    
    def _adjust_coordinates_for_lower_half(self, keypoints: FootKeypoints, 
                                          original_shape: tuple) -> FootKeypoints:
        """하반부 이미지에서 감지된 좌표를 전체 이미지 좌표로 변환"""
        try:
            height = original_shape[0]
            offset_y = 0.4  # 상단에서 40% 지점부터 시작했으므로
            
            # 각 키포인트의 y 좌표를 조정
            if keypoints.left_heel:
                keypoints.left_heel.y = keypoints.left_heel.y * 0.6 + offset_y
            if keypoints.right_heel:
                keypoints.right_heel.y = keypoints.right_heel.y * 0.6 + offset_y  
            if keypoints.left_foot_index:
                keypoints.left_foot_index.y = keypoints.left_foot_index.y * 0.6 + offset_y
            if keypoints.right_foot_index:
                keypoints.right_foot_index.y = keypoints.right_foot_index.y * 0.6 + offset_y
            if keypoints.left_foot:
                keypoints.left_foot.y = keypoints.left_foot.y * 0.6 + offset_y
            if keypoints.right_foot:
                keypoints.right_foot.y = keypoints.right_foot.y * 0.6 + offset_y
                
        except Exception as e:
            logger.warning(f"[MediaPipe] 좌표 변환 오류: {e}")
        
        return keypoints

    def __del__(self):
        """리소스 정리"""
        if hasattr(self, 'pose'):
            self.pose.close()
        logger.info("[MediaPipe] Pose 프로세서 리소스 정리 완료")

# 싱글톤 인스턴스
_mediapipe_pose_processor = None

def get_mediapipe_pose_processor(enable_imu_fusion: bool = True) -> MediaPipePoseProcessor:
    """MediaPipe Pose 프로세서 싱글톤 인스턴스 반환"""
    global _mediapipe_pose_processor
    if _mediapipe_pose_processor is None:
        _mediapipe_pose_processor = MediaPipePoseProcessor(enable_imu_fusion=enable_imu_fusion)
        logger.info("[MediaPipe] Pose 프로세서 싱글톤 인스턴스 생성")
    return _mediapipe_pose_processor