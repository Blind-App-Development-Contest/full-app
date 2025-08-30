# utils/imu_fusion_processor.py
import numpy as np
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque
from datetime import datetime
import math
import cv2

logger = logging.getLogger("uvicorn.error")

@dataclass
class IMUData:
    """IMU 센서 데이터 클래스"""
    accelerometer: Tuple[float, float, float]  # (x, y, z) m/s²
    gyroscope: Tuple[float, float, float]      # (x, y, z) rad/s
    magnetometer: Optional[Tuple[float, float, float]] = None  # (x, y, z) µT
    timestamp: float = 0.0
    device_orientation: Optional[str] = None   # 'portrait', 'landscape' 등

@dataclass
class FilteredIMUState:
    """필터링된 IMU 상태"""
    position: Tuple[float, float, float]      # (x, y, z) 위치
    velocity: Tuple[float, float, float]      # (x, y, z) 속도
    acceleration: Tuple[float, float, float]  # (x, y, z) 가속도
    orientation: Tuple[float, float, float]   # (roll, pitch, yaw) 자세
    confidence: float                         # 신뢰도 (0-1)
    timestamp: float

@dataclass
class CameraPose:
    """카메라 자세 정보"""
    roll: float      # x축 회전 (라디안)
    pitch: float     # y축 회전 (라디안)  
    yaw: float       # z축 회전 (라디안)
    rotation_matrix: np.ndarray  # 3x3 회전 행렬
    timestamp: float

@dataclass
class CorrectedDepthResult:
    """자세 보정된 깊이 결과"""
    corrected_depth: float
    original_depth: float
    correction_factor: float
    camera_pose: CameraPose
    confidence: float

@dataclass
class FusionResult:
    """비전-IMU 융합 결과"""
    fused_position: Tuple[float, float, float]
    vision_weight: float
    imu_weight: float
    confidence: float
    fusion_method: str

class ExtendedKalmanFilter:
    """
    확장 칼만 필터 - IMU 및 비전 데이터 융합
    
    상태 벡터: [x, y, z, vx, vy, vz, ax, ay, az, roll, pitch, yaw]
    - 위치 (x, y, z)
    - 속도 (vx, vy, vz)  
    - 가속도 (ax, ay, az)
    - 자세 (roll, pitch, yaw)
    """
    
    def __init__(self):
        # 상태 벡터 크기 (12차원)
        self.state_size = 12
        
        # 상태 벡터 초기화 [x, y, z, vx, vy, vz, ax, ay, az, roll, pitch, yaw]
        self.state = np.zeros(self.state_size)
        
        # 공분산 행렬 초기화
        self.P = np.eye(self.state_size) * 0.1
        
        # 프로세스 노이즈 공분산 (Q)
        self.Q = np.eye(self.state_size) * 0.01
        self.Q[6:9, 6:9] *= 10  # 가속도 노이즈 크게
        self.Q[9:12, 9:12] *= 5  # 자세 노이즈
        
        # 관측 노이즈 공분산 (R)
        self.R_vision = np.eye(3) * 0.05  # 비전 위치 측정
        self.R_imu = np.eye(6) * 0.1      # IMU 가속도 + 자세 측정
        
        # 시간 관련
        self.last_time = time.time()
        self.dt = 0.033  # 기본 30fps
        
        logger.info("[EKF] 확장 칼만 필터 초기화 완료")
    
    def predict(self, dt: float, gyro_data: Optional[Tuple[float, float, float]] = None):
        """향상된 예측 단계 (걸음 이벤트 및 자세 보정 포함)"""
        try:
            # 상태 전이 행렬 F 구성
            F = np.eye(self.state_size)
            
            # 위치 = 위치 + 속도*dt + 0.5*가속도*dt²
            F[0:3, 3:6] = np.eye(3) * dt      # 위치 <- 속도
            F[0:3, 6:9] = np.eye(3) * 0.5 * dt**2  # 위치 <- 가속도
            
            # 속도 = 속도 + 가속도*dt
            F[3:6, 6:9] = np.eye(3) * dt      # 속도 <- 가속도
            
            # 자세 업데이트 (자이로스코프 데이터 사용)
            if gyro_data is not None:
                # 각속도를 사용한 자세 예측
                F[9:12, 9:12] = np.eye(3)  # 자세는 독립적으로 업데이트
                gyro = np.array(gyro_data)
                self.state[9:12] += gyro * dt
                
                # 자세 각도를 -π ~ π 범위로 정규화
                self.state[9:12] = ((self.state[9:12] + np.pi) % (2 * np.pi)) - np.pi
            
            # 상태 예측
            predicted_state = F @ self.state
            
            # 물리적 제약 조건 적용
            predicted_state = self._apply_physical_constraints(predicted_state)
            
            self.state = predicted_state
            
            # 적응형 프로세스 노이즈 계산
            adaptive_Q = self._calculate_adaptive_process_noise(dt)
            
            # 공분산 예측
            self.P = F @ self.P @ F.T + adaptive_Q * dt
            
            # 공분산 행렬 안정성 확보
            self.P = self._ensure_positive_definite(self.P)
            
        except Exception as e:
            logger.error(f"[EKF] 예측 단계 오류: {e}")
    
    def _apply_physical_constraints(self, state: np.ndarray) -> np.ndarray:
        """물리적 제약 조건 적용"""
        # 속도 제한 (보행자의 최대 속도 ~5m/s)
        max_velocity = 5.0
        state[3:6] = np.clip(state[3:6], -max_velocity, max_velocity)
        
        # 가속도 제한 (일반적인 보행자 가속도 ~10m/s²)
        max_acceleration = 10.0
        state[6:9] = np.clip(state[6:9], -max_acceleration, max_acceleration)
        
        # Z축 위치 제한 (지면 아래로 가지 않도록)
        state[2] = max(0.0, state[2])
        
        return state
    
    def _calculate_adaptive_process_noise(self, dt: float) -> np.ndarray:
        """상황에 따른 적응형 프로세스 노이즈 계산"""
        # 기본 노이즈 행렬
        adaptive_Q = self.Q.copy()
        
        # 현재 가속도 크기에 따른 노이즈 조정
        current_accel = np.linalg.norm(self.state[6:9])
        if current_accel > 5.0:  # 높은 가속도 시 노이즈 증가
            adaptive_Q[6:9, 6:9] *= 2.0
            adaptive_Q[3:6, 3:6] *= 1.5
        elif current_accel < 1.0:  # 낮은 가속도 시 노이즈 감소
            adaptive_Q[6:9, 6:9] *= 0.5
        
        # 자세 변화량에 따른 노이즈 조정
        angular_velocity = np.linalg.norm(self.state[9:12])
        if angular_velocity > 0.5:  # 빠른 회전 시
            adaptive_Q[9:12, 9:12] *= 1.5
        
        return adaptive_Q
    
    def _ensure_positive_definite(self, matrix: np.ndarray) -> np.ndarray:
        """공분산 행렬의 양정치성 보장"""
        try:
            # 고유값 분해
            eigenvalues, eigenvectors = np.linalg.eigh(matrix)
            
            # 음수 고유값을 작은 양수로 변경
            eigenvalues = np.maximum(eigenvalues, 1e-6)
            
            # 행렬 재구성
            return eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        except Exception:
            # 실패 시 단위 행렬로 초기화
            return np.eye(matrix.shape[0]) * 0.1
        
    def update_with_vision(self, vision_position: Tuple[float, float, float], confidence: float, 
                          depth_correction: Optional[Dict] = None):
        """향상된 비전 측정값으로 업데이트 (깊이 보정 포함)"""
        try:
            # 관측 행렬 H (위치만 관측)
            H = np.zeros((3, self.state_size))
            H[0:3, 0:3] = np.eye(3)
            
            # 측정값 (깊이 보정 적용)
            corrected_position = list(vision_position)
            if depth_correction and 'corrected_depth' in depth_correction:
                corrected_position[2] = depth_correction['corrected_depth']
            
            z = np.array(corrected_position)
            
            # 예측된 측정값
            h = H @ self.state
            
            # 잔차
            y = z - h
            
            # 잔차 이상치 검출 및 처리
            if self._is_measurement_outlier(y):
                logger.warning(f"[EKF] 비전 측정값 이상치 검출: {y}")
                # 이상치인 경우 신뢰도를 크게 감소
                confidence *= 0.3
                
                # 잔차 크기 제한
                max_residual = 2.0  # 2미터
                y = np.clip(y, -max_residual, max_residual)
            
            # 적응형 측정 노이즈 (신뢰도와 깊이 보정 품질 반영)
            base_noise_factor = 1.0 / max(0.1, confidence)
            
            if depth_correction:
                correction_quality = depth_correction.get('confidence', 0.8)
                base_noise_factor /= correction_quality
            
            R_adaptive = self.R_vision * base_noise_factor
            
            # 잔차 공분산
            S = H @ self.P @ H.T + R_adaptive
            
            # 수치적 안정성을 위한 정칙화
            S += np.eye(S.shape[0]) * 1e-6
            
            try:
                # 칼만 게인 계산
                K = self.P @ H.T @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                # 역행렬 계산 실패 시 의사 역행렬 사용
                K = self.P @ H.T @ np.linalg.pinv(S)
            
            # 상태 업데이트
            self.state = self.state + K @ y
            
            # 공분산 업데이트 (Joseph 형태 - 수치적 안정성)
            I = np.eye(self.state_size)
            IKH = I - K @ H
            self.P = IKH @ self.P @ IKH.T + K @ R_adaptive @ K.T
            
            # 공분산 양정치성 보장
            self.P = self._ensure_positive_definite(self.P)
            
            logger.debug(f"[EKF] 비전 업데이트 완료: 위치={corrected_position}, 신뢰도={confidence:.3f}")
            
        except Exception as e:
            logger.error(f"[EKF] 비전 업데이트 오류: {e}")
    
    def _is_measurement_outlier(self, residual: np.ndarray, threshold: float = 3.0) -> bool:
        """측정값 이상치 검출 (마할라노비스 거리 기반)"""
        try:
            # 잔차 크기가 임계값을 초과하는지 확인
            residual_norm = np.linalg.norm(residual)
            return residual_norm > threshold
        except Exception:
            return False
        
    def update_with_imu(self, imu_data: IMUData):
        """IMU 측정값으로 업데이트"""
        # 가속도 측정값
        accel = np.array(imu_data.accelerometer)
        
        # 중력 제거 (간단화 - 실제로는 자세 기반 회전 필요)
        gravity = np.array([0, 0, -9.81])
        accel_corrected = accel - gravity
        
        # 관측 행렬 H (가속도 관측)
        H = np.zeros((3, self.state_size))
        H[0:3, 6:9] = np.eye(3)
        
        # 측정값
        z = accel_corrected
        
        # 예측된 측정값
        h = H @ self.state
        
        # 잔차
        y = z - h
        
        # 잔차 공분산
        S = H @ self.P @ H.T + self.R_imu[0:3, 0:3]
        
        # 칼만 게인
        K = self.P @ H.T @ np.linalg.inv(S)
        
        # 상태 업데이트
        self.state = self.state + K @ y
        
        # 공분산 업데이트
        I = np.eye(self.state_size)
        self.P = (I - K @ H) @ self.P
        
        # 자세 정보 업데이트 (gyroscope 사용)
        gyro = np.array(imu_data.gyroscope)
        self.state[9:12] += gyro * self.dt
        
    def get_current_state(self) -> FilteredIMUState:
        """현재 필터 상태 반환"""
        return FilteredIMUState(
            position=tuple(self.state[0:3]),
            velocity=tuple(self.state[3:6]),
            acceleration=tuple(self.state[6:9]),
            orientation=tuple(self.state[9:12]),
            confidence=self._calculate_confidence(),
            timestamp=time.time()
        )
    
    def _calculate_confidence(self) -> float:
        """필터 신뢰도 계산"""
        # 공분산 행렬의 대각합을 기반으로 신뢰도 계산
        position_uncertainty = np.trace(self.P[0:3, 0:3])
        max_uncertainty = 1.0  # 최대 불확실성
        confidence = max(0.0, 1.0 - position_uncertainty / max_uncertainty)
        return confidence

class IMUFusionProcessor:
    """
    IMU 센서와 비전 데이터 융합 프로세서
    
    주요 기능:
    - IMU 데이터 수집 및 전처리
    - 확장 칼만 필터를 통한 상태 추정
    - 비전 데이터와 IMU 데이터 융합
    - 걸음 감지 및 보폭 보정
    """
    
    def __init__(self):
        # 칼만 필터 초기화
        self.kalman_filter = ExtendedKalmanFilter()
        
        # IMU 데이터 버퍼
        self.imu_buffer = deque(maxlen=100)  # 최근 100개 IMU 데이터
        
        # 비전 데이터 히스토리
        self.vision_history = deque(maxlen=30)  # 최근 30개 비전 측정
        
        # 걸음 감지를 위한 상태 (향상된 알고리즘)
        self.step_detector = {
            'last_step_time': 0.0,
            'step_threshold': 2.5,  # 걸음 감지 임계값 (m/s²)
            'min_step_interval': 0.4,  # 최소 걸음 간격 (초)
            'max_step_interval': 2.0,  # 최대 걸음 간격 (초)
            'step_count': 0,
            'step_buffer': deque(maxlen=10),  # 최근 10개 걸음 이벤트
            'acceleration_buffer': deque(maxlen=20),  # 가속도 히스토리
            'peak_detection': {
                'threshold_factor': 1.5,  # 동적 임계값 계수
                'window_size': 5,  # 피크 검출 윈도우
                'last_peak': 0.0,
                'peaks_history': deque(maxlen=50)
            },
            'walking_state': {
                'is_walking': False,
                'walking_start_time': 0.0,
                'step_frequency': 0.0,  # 걸음 빈도 (steps/sec)
                'avg_step_interval': 0.8  # 평균 걸음 간격
            }
        }
        
        # 융합 설정
        self.fusion_params = {
            'vision_weight_base': 0.7,
            'imu_weight_base': 0.3,
            'confidence_threshold': 0.5,
            'fusion_timeout': 1.0  # 1초 이상 오래된 데이터는 무시
        }
        
        # 카메라 자세 보정 설정
        self.camera_correction = {
            'intrinsic_matrix': None,  # 3x3 카메라 내부 파라미터 행렬
            'distortion_coeffs': None,  # 렌즈 왜곡 계수
            'baseline_pose': None,     # 기준 자세 (수평일 때)
            'correction_enabled': True,
            'max_tilt_angle': math.radians(45),  # 최대 기울기 각도 (45도)
            'depth_correction_factor': 1.2,     # 깊이 보정 계수
        }
        
        # 자세 히스토리 (카메라 자세 추적)
        self.pose_history = deque(maxlen=50)  # 최근 50개 자세 데이터
        
        # 처리 통계
        self.stats = {
            'total_fusions': 0,
            'successful_fusions': 0,
            'imu_updates': 0,
            'vision_updates': 0,
            'detected_steps': 0
        }
        
        logger.info("[IMU Fusion] IMU 융합 프로세서 초기화 완료")
    
    def add_imu_data(self, imu_data: IMUData) -> bool:
        """
        IMU 데이터 추가 및 처리
        
        Args:
            imu_data: IMU 센서 데이터
            
        Returns:
            bool: 처리 성공 여부
        """
        try:
            # 데이터 검증
            if not self._validate_imu_data(imu_data):
                return False
            
            # 버퍼에 추가
            self.imu_buffer.append(imu_data)
            
            # 시간 간격 계산
            current_time = time.time()
            if len(self.imu_buffer) > 1:
                dt = current_time - self.imu_buffer[-2].timestamp
                self.kalman_filter.dt = min(max(dt, 0.01), 0.1)  # 0.01~0.1초 제한
            
            # 칼만 필터 예측 단계 (자이로스코프 데이터 포함)
            self.kalman_filter.predict(self.kalman_filter.dt, imu_data.gyroscope)
            
            # IMU 데이터로 업데이트
            self.kalman_filter.update_with_imu(imu_data)
            
            # 걸음 감지
            self._detect_steps(imu_data)
            
            self.stats['imu_updates'] += 1
            logger.debug(f"[IMU Fusion] IMU 데이터 추가: {imu_data.accelerometer}")
            
            return True
            
        except Exception as e:
            logger.error(f"[IMU Fusion] IMU 데이터 처리 오류: {e}")
            return False
    
    def fuse_with_vision(self, 
                        vision_x: float, vision_y: float, vision_z: float,
                        foot_side: str, timestamp: float) -> Optional[Tuple[float, float, float]]:
        """
        비전 데이터와 IMU 데이터 융합
        
        Args:
            vision_x, vision_y, vision_z: 비전 기반 3D 위치
            foot_side: 발 구분 ('left', 'right')
            timestamp: 타임스탬프
            
        Returns:
            Tuple[float, float, float]: 융합된 3D 위치 또는 None
        """
        try:
            vision_position = (vision_x, vision_y, vision_z)
            
            # 오래된 데이터 체크
            current_time = time.time()
            if current_time - timestamp > self.fusion_params['fusion_timeout']:
                logger.warning("[IMU Fusion] 비전 데이터가 너무 오래됨")
                return None
            
            # IMU 데이터가 충분한지 확인
            if len(self.imu_buffer) < 5:
                logger.debug("[IMU Fusion] IMU 데이터 부족 - 비전 데이터만 사용")
                return vision_position
            
            # 현재 IMU 상태 가져오기
            imu_state = self.kalman_filter.get_current_state()
            
            # 융합 가중치 계산
            vision_confidence = self._calculate_vision_confidence(vision_position, timestamp)
            imu_confidence = imu_state.confidence
            
            # 적응형 가중치
            total_confidence = vision_confidence + imu_confidence
            if total_confidence > 0:
                vision_weight = vision_confidence / total_confidence
                imu_weight = imu_confidence / total_confidence
            else:
                vision_weight = self.fusion_params['vision_weight_base']
                imu_weight = self.fusion_params['imu_weight_base']
            
            # 위치 융합
            imu_position = imu_state.position
            
            fused_x = vision_x * vision_weight + imu_position[0] * imu_weight
            fused_y = vision_y * vision_weight + imu_position[1] * imu_weight  
            fused_z = vision_z * vision_weight + imu_position[2] * imu_weight
            
            fused_position = (fused_x, fused_y, fused_z)
            
            # 칼만 필터에 비전 측정값 업데이트 (깊이 보정 정보 포함)
            fusion_confidence = (vision_confidence + imu_confidence) / 2
            
            # 깊이 보정 정보가 있다면 함께 전달
            depth_correction_info = None
            if hasattr(self, 'last_depth_correction'):
                depth_correction_info = self.last_depth_correction
            
            self.kalman_filter.update_with_vision(vision_position, fusion_confidence, depth_correction_info)
            
            # 히스토리에 추가
            fusion_result = FusionResult(
                fused_position=fused_position,
                vision_weight=vision_weight,
                imu_weight=imu_weight,
                confidence=fusion_confidence,
                fusion_method="weighted_average_kalman"
            )
            self.vision_history.append((timestamp, fusion_result))
            
            # 통계 업데이트
            self.stats['total_fusions'] += 1
            self.stats['successful_fusions'] += 1
            self.stats['vision_updates'] += 1
            
            logger.debug(f"[IMU Fusion] 융합 완료: {foot_side} - "
                        f"Vision({vision_weight:.2f}) + IMU({imu_weight:.2f}) = {fused_position}")
            
            return fused_position
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 데이터 융합 오류: {e}")
            self.stats['total_fusions'] += 1
            return None
    
    def _validate_imu_data(self, imu_data: IMUData) -> bool:
        """IMU 데이터 검증"""
        try:
            # 가속도 범위 체크 (일반적으로 -50 ~ 50 m/s²)
            for acc in imu_data.accelerometer:
                if abs(acc) > 50.0:
                    logger.warning(f"[IMU Fusion] 가속도 값 이상: {acc}")
                    return False
            
            # 자이로스코프 범위 체크 (일반적으로 -10 ~ 10 rad/s)
            for gyro in imu_data.gyroscope:
                if abs(gyro) > 10.0:
                    logger.warning(f"[IMU Fusion] 자이로스코프 값 이상: {gyro}")
                    return False
            
            return True
            
        except Exception:
            return False
    
    def _detect_steps(self, imu_data: IMUData):
        """향상된 가속도 기반 걸음 감지 및 이벤트 예측"""
        try:
            current_time = time.time()
            
            # 3축 가속도 크기 계산 (보행 패턴 감지를 위함)
            accel = np.array(imu_data.accelerometer)
            accel_magnitude = np.linalg.norm(accel)
            
            # 수직 가속도 (z축) - 주요 걸음 신호
            vertical_accel = abs(accel[2])
            
            # 가속도 히스토리에 추가
            accel_entry = {
                'timestamp': current_time,
                'magnitude': accel_magnitude,
                'vertical': vertical_accel,
                'raw': accel
            }
            self.step_detector['acceleration_buffer'].append(accel_entry)
            
            # 동적 임계값 계산 (최근 가속도 평균 기반)
            if len(self.step_detector['acceleration_buffer']) >= 10:
                recent_magnitudes = [entry['magnitude'] for entry in 
                                   list(self.step_detector['acceleration_buffer'])[-10:]]
                baseline = np.mean(recent_magnitudes)
                dynamic_threshold = baseline * self.step_detector['peak_detection']['threshold_factor']
            else:
                dynamic_threshold = self.step_detector['step_threshold']
            
            # 피크 검출 알고리즘
            step_detected = self._detect_step_peak(accel_entry, dynamic_threshold, current_time)
            
            # 걸음 상태 업데이트
            self._update_walking_state(step_detected, current_time)
            
            # 걸음 예측 (칼만 필터와 연동)
            if step_detected:
                self._predict_next_step(current_time)
                
        except Exception as e:
            logger.debug(f"[IMU Fusion] 고급 걸음 감지 오류: {e}")
    
    def _detect_step_peak(self, accel_entry: Dict, threshold: float, current_time: float) -> bool:
        """피크 검출 기반 걸음 감지"""
        try:
            peak_detection = self.step_detector['peak_detection']
            
            # 윈도우 크기만큼 데이터가 쌓였는지 확인
            if len(self.step_detector['acceleration_buffer']) < peak_detection['window_size']:
                return False
            
            # 현재 가속도가 임계값을 초과하는지 확인
            if accel_entry['magnitude'] < threshold:
                return False
            
            # 최소 걸음 간격 확인
            time_since_last_step = current_time - self.step_detector['last_step_time']
            if time_since_last_step < self.step_detector['min_step_interval']:
                return False
            
            # 최대 걸음 간격 확인 (너무 오래 걸음이 없으면 상태 리셋)
            if time_since_last_step > self.step_detector['max_step_interval']:
                self.step_detector['walking_state']['is_walking'] = False
            
            # 피크 검출: 현재 값이 윈도우 내에서 최대값인지 확인
            window_data = list(self.step_detector['acceleration_buffer'])[-peak_detection['window_size']:]
            current_is_peak = all(accel_entry['magnitude'] >= entry['magnitude'] for entry in window_data[:-1])
            
            if current_is_peak:
                # 걸음 이벤트 등록
                step_event = {
                    'timestamp': current_time,
                    'magnitude': accel_entry['magnitude'],
                    'interval': time_since_last_step,
                    'confidence': min(1.0, accel_entry['magnitude'] / threshold)
                }
                
                self.step_detector['step_buffer'].append(step_event)
                self.step_detector['step_count'] += 1
                self.step_detector['last_step_time'] = current_time
                self.stats['detected_steps'] += 1
                
                # 피크 히스토리 업데이트
                peak_detection['peaks_history'].append(step_event)
                peak_detection['last_peak'] = current_time
                
                logger.debug(f"[IMU Fusion] 고급 걸음 감지: #{self.step_detector['step_count']} "
                           f"(크기: {accel_entry['magnitude']:.2f}, 임계값: {threshold:.2f})")
                
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"[IMU Fusion] 피크 검출 오류: {e}")
            return False
    
    def _update_walking_state(self, step_detected: bool, current_time: float):
        """걸음 상태 업데이트 및 빈도 계산"""
        try:
            walking_state = self.step_detector['walking_state']
            
            if step_detected:
                if not walking_state['is_walking']:
                    # 걷기 시작
                    walking_state['is_walking'] = True
                    walking_state['walking_start_time'] = current_time
                    logger.debug("[IMU Fusion] 걷기 상태 시작")
                
                # 걸음 빈도 계산 (최근 5개 걸음 기준)
                recent_steps = list(self.step_detector['step_buffer'])[-5:]
                if len(recent_steps) >= 2:
                    intervals = [recent_steps[i]['interval'] for i in range(1, len(recent_steps))]
                    avg_interval = np.mean(intervals)
                    walking_state['avg_step_interval'] = avg_interval
                    walking_state['step_frequency'] = 1.0 / avg_interval if avg_interval > 0 else 0
                    
                    logger.debug(f"[IMU Fusion] 걸음 빈도: {walking_state['step_frequency']:.2f} steps/sec")
            
            # 걷기 상태 타임아웃 확인
            elif walking_state['is_walking']:
                time_since_last_step = current_time - self.step_detector['last_step_time']
                if time_since_last_step > self.step_detector['max_step_interval']:
                    walking_state['is_walking'] = False
                    walking_state['step_frequency'] = 0.0
                    logger.debug("[IMU Fusion] 걷기 상태 종료 (타임아웃)")
                    
        except Exception as e:
            logger.debug(f"[IMU Fusion] 걸음 상태 업데이트 오류: {e}")
    
    def _predict_next_step(self, current_time: float):
        """다음 걸음 예측 (칼만 필터 기반)"""
        try:
            walking_state = self.step_detector['walking_state']
            
            if not walking_state['is_walking'] or walking_state['avg_step_interval'] <= 0:
                return
            
            # 다음 걸음 예상 시간 계산
            next_step_time = current_time + walking_state['avg_step_interval']
            
            # 칼만 필터에서 미래 상태 예측
            predicted_state = self.kalman_filter.get_current_state()
            
            # 예측된 걸음 위치 계산 (현재 속도 기반)
            dt = walking_state['avg_step_interval']
            predicted_position = (
                predicted_state.position[0] + predicted_state.velocity[0] * dt,
                predicted_state.position[1] + predicted_state.velocity[1] * dt,
                predicted_state.position[2] + predicted_state.velocity[2] * dt
            )
            
            # 예측 정보 저장 (다른 시스템에서 사용 가능)
            self.step_detector['next_step_prediction'] = {
                'predicted_time': next_step_time,
                'predicted_position': predicted_position,
                'confidence': min(0.9, walking_state['step_frequency'] * 0.5),
                'prediction_timestamp': current_time
            }
            
            logger.debug(f"[IMU Fusion] 다음 걸음 예측: {next_step_time - current_time:.2f}초 후 "
                        f"위치 ({predicted_position[0]:.2f}, {predicted_position[1]:.2f}, {predicted_position[2]:.2f})")
            
        except Exception as e:
            logger.debug(f"[IMU Fusion] 걸음 예측 오류: {e}")
    
    def get_step_prediction(self) -> Optional[Dict[str, Any]]:
        """현재 걸음 예측 정보 반환"""
        try:
            prediction = self.step_detector.get('next_step_prediction')
            if prediction:
                current_time = time.time()
                # 예측이 5초 이상 오래되었으면 무효화
                if current_time - prediction['prediction_timestamp'] > 5.0:
                    return None
                return prediction
            return None
        except Exception:
            return None
    
    def get_walking_state(self) -> Dict[str, Any]:
        """현재 걸음 상태 정보 반환"""
        try:
            walking_state = self.step_detector['walking_state']
            return {
                'is_walking': walking_state['is_walking'],
                'step_frequency': walking_state['step_frequency'],
                'avg_step_interval': walking_state['avg_step_interval'],
                'total_steps': self.step_detector['step_count'],
                'recent_steps': len(self.step_detector['step_buffer']),
                'walking_duration': (time.time() - walking_state['walking_start_time']) if walking_state['is_walking'] else 0
            }
        except Exception:
            return {'is_walking': False, 'error': 'state_unavailable'}
    
    def _calculate_vision_confidence(self, vision_position: Tuple[float, float, float], timestamp: float) -> float:
        """비전 데이터 신뢰도 계산"""
        try:
            base_confidence = 0.7
            
            # 시간 기반 신뢰도 감소
            age = time.time() - timestamp
            time_factor = max(0.1, 1.0 - age / self.fusion_params['fusion_timeout'])
            
            # 위치 안정성 기반 신뢰도
            if len(self.vision_history) > 3:
                recent_positions = [result[1].fused_position for result in list(self.vision_history)[-3:]]
                position_variance = np.var(recent_positions, axis=0)
                stability_factor = max(0.3, 1.0 - np.mean(position_variance))
            else:
                stability_factor = 1.0
            
            confidence = base_confidence * time_factor * stability_factor
            return min(1.0, max(0.0, confidence))
            
        except Exception:
            return 0.5
    
    def get_step_count(self) -> int:
        """감지된 걸음 수 반환"""
        return self.step_detector['step_count']
    
    def reset_step_count(self):
        """걸음 수 초기화"""
        self.step_detector['step_count'] = 0
        self.step_detector['last_step_time'] = 0.0
        logger.info("[IMU Fusion] 걸음 수 초기화")
    
    def get_current_imu_state(self) -> Optional[FilteredIMUState]:
        """현재 IMU 상태 반환"""
        try:
            return self.kalman_filter.get_current_state()
        except Exception as e:
            logger.error(f"[IMU Fusion] 상태 조회 오류: {e}")
            return None
    
    def get_fusion_statistics(self) -> Dict[str, Any]:
        """융합 통계 반환"""
        success_rate = (self.stats['successful_fusions'] / max(1, self.stats['total_fusions']))
        
        return {
            "total_fusions": self.stats['total_fusions'],
            "success_rate": round(success_rate, 3),
            "imu_updates": self.stats['imu_updates'],
            "vision_updates": self.stats['vision_updates'],
            "detected_steps": self.stats['detected_steps'],
            "imu_buffer_size": len(self.imu_buffer),
            "vision_history_size": len(self.vision_history),
            "current_step_count": self.get_step_count()
        }
    
    def reset_statistics(self):
        """통계 초기화"""
        self.stats = {
            'total_fusions': 0,
            'successful_fusions': 0,
            'imu_updates': 0,
            'vision_updates': 0,
            'detected_steps': 0
        }
        logger.info("[IMU Fusion] 통계 초기화 완료")
    
    def set_camera_calibration(self, intrinsic_matrix: np.ndarray, distortion_coeffs: np.ndarray):
        """
        카메라 캘리브레이션 파라미터 설정
        
        Args:
            intrinsic_matrix: 3x3 카메라 내부 파라미터 행렬
            distortion_coeffs: 렌즈 왜곡 계수 배열
        """
        self.camera_correction['intrinsic_matrix'] = intrinsic_matrix.copy()
        self.camera_correction['distortion_coeffs'] = distortion_coeffs.copy()
        logger.info("[IMU Fusion] 카메라 캘리브레이션 파라미터 설정 완료")
    
    def get_current_camera_pose(self) -> Optional[CameraPose]:
        """
        현재 카메라 자세 계산 (IMU 기반)
        
        Returns:
            CameraPose: 현재 카메라 자세 또는 None
        """
        try:
            if len(self.imu_buffer) == 0:
                return None
            
            # 최신 IMU 상태 가져오기
            imu_state = self.kalman_filter.get_current_state()
            
            # 자세 각도 추출
            roll, pitch, yaw = imu_state.orientation
            
            # 회전 행렬 계산
            rotation_matrix = self._euler_to_rotation_matrix(roll, pitch, yaw)
            
            # 카메라 자세 객체 생성
            camera_pose = CameraPose(
                roll=roll,
                pitch=pitch,
                yaw=yaw,
                rotation_matrix=rotation_matrix,
                timestamp=time.time()
            )
            
            # 자세 히스토리에 추가
            self.pose_history.append(camera_pose)
            
            return camera_pose
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 카메라 자세 계산 오류: {e}")
            return None
    
    def _euler_to_rotation_matrix(self, roll: float, pitch: float, yaw: float) -> np.ndarray:
        """
        오일러 각도를 회전 행렬로 변환
        
        Args:
            roll, pitch, yaw: 오일러 각도 (라디안)
            
        Returns:
            np.ndarray: 3x3 회전 행렬
        """
        # Roll 회전 행렬 (X축)
        R_x = np.array([
            [1, 0, 0],
            [0, math.cos(roll), -math.sin(roll)],
            [0, math.sin(roll), math.cos(roll)]
        ])
        
        # Pitch 회전 행렬 (Y축)
        R_y = np.array([
            [math.cos(pitch), 0, math.sin(pitch)],
            [0, 1, 0],
            [-math.sin(pitch), 0, math.cos(pitch)]
        ])
        
        # Yaw 회전 행렬 (Z축)
        R_z = np.array([
            [math.cos(yaw), -math.sin(yaw), 0],
            [math.sin(yaw), math.cos(yaw), 0],
            [0, 0, 1]
        ])
        
        # 최종 회전 행렬: R = R_z * R_y * R_x
        rotation_matrix = R_z @ R_y @ R_x
        return rotation_matrix
    
    def correct_depth_with_pose(self, original_depth: float, pixel_x: int, pixel_y: int, 
                               image_width: int, image_height: int) -> Optional[CorrectedDepthResult]:
        """
        카메라 자세를 고려한 깊이 보정
        
        Args:
            original_depth: 원본 깊이 값 (미터)
            pixel_x, pixel_y: 픽셀 좌표
            image_width, image_height: 이미지 해상도
            
        Returns:
            CorrectedDepthResult: 보정된 깊이 결과 또는 None
        """
        try:
            # 카메라 자세 보정이 비활성화된 경우
            if not self.camera_correction['correction_enabled']:
                return None
            
            # 현재 카메라 자세 가져오기
            camera_pose = self.get_current_camera_pose()
            if camera_pose is None:
                return None
            
            # 카메라 내부 파라미터 확인
            if self.camera_correction['intrinsic_matrix'] is None:
                # 기본 내부 파라미터 사용 (추정값)
                fx = image_width * 0.7  # 대략적인 focal length
                fy = image_height * 0.7
                cx = image_width / 2
                cy = image_height / 2
                
                intrinsic_matrix = np.array([
                    [fx, 0, cx],
                    [0, fy, cy],
                    [0, 0, 1]
                ])
            else:
                intrinsic_matrix = self.camera_correction['intrinsic_matrix']
            
            # 픽셀 좌표를 정규화된 카메라 좌표로 변환
            fx, fy = intrinsic_matrix[0, 0], intrinsic_matrix[1, 1]
            cx, cy = intrinsic_matrix[0, 2], intrinsic_matrix[1, 2]
            
            # 정규화된 카메라 좌표
            x_cam = (pixel_x - cx) / fx
            y_cam = (pixel_y - cy) / fy
            
            # 3D 카메라 좌표 (원본 깊이 사용)
            camera_point = np.array([x_cam * original_depth, y_cam * original_depth, original_depth])
            
            # 카메라 자세를 고려한 실제 3D 점으로 변환
            world_point = camera_pose.rotation_matrix @ camera_point
            
            # 보정된 깊이 계산 (실제 거리)
            corrected_depth = np.linalg.norm(world_point)
            
            # 기울기 각도에 따른 추가 보정
            tilt_angle = math.sqrt(camera_pose.pitch**2 + camera_pose.roll**2)
            if tilt_angle > self.camera_correction['max_tilt_angle']:
                # 기울기가 너무 클 때 보정 계수 적용
                tilt_correction = self.camera_correction['depth_correction_factor']
                corrected_depth *= tilt_correction
            
            # 보정 계수 계산
            correction_factor = corrected_depth / original_depth if original_depth > 0 else 1.0
            
            # 신뢰도 계산 (기울기가 클수록 신뢰도 감소)
            max_angle = self.camera_correction['max_tilt_angle']
            confidence = max(0.3, 1.0 - (tilt_angle / max_angle))
            
            result = CorrectedDepthResult(
                corrected_depth=corrected_depth,
                original_depth=original_depth,
                correction_factor=correction_factor,
                camera_pose=camera_pose,
                confidence=confidence
            )
            
            logger.debug(f"[IMU Fusion] 깊이 보정: {original_depth:.3f}m → {corrected_depth:.3f}m "
                        f"(기울기: {math.degrees(tilt_angle):.1f}°)")
            
            return result
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 깊이 보정 오류: {e}")
            return None
    
    def correct_keypoint_coordinates(self, keypoints: List[Tuple[int, int]], 
                                   image_width: int, image_height: int) -> List[Tuple[int, int]]:
        """
        카메라 자세를 고려한 키포인트 좌표 보정
        
        Args:
            keypoints: 키포인트 좌표 리스트 [(x, y), ...]
            image_width, image_height: 이미지 해상도
            
        Returns:
            List[Tuple[int, int]]: 보정된 키포인트 좌표
        """
        try:
            # 카메라 자세 가져오기
            camera_pose = self.get_current_camera_pose()
            if camera_pose is None or not self.camera_correction['correction_enabled']:
                return keypoints  # 보정 불가능하면 원본 반환
            
            corrected_keypoints = []
            
            for x, y in keypoints:
                # 이미지 중심을 기준으로 좌표 이동
                center_x, center_y = image_width // 2, image_height // 2
                rel_x, rel_y = x - center_x, y - center_y
                
                # 카메라 기울기에 따른 보정
                pitch_correction = rel_y * math.sin(camera_pose.pitch) * 0.1
                roll_correction = rel_x * math.sin(camera_pose.roll) * 0.1
                
                # 보정된 좌표 계산
                corrected_x = int(x + roll_correction)
                corrected_y = int(y + pitch_correction)
                
                # 이미지 경계 내로 제한
                corrected_x = max(0, min(image_width - 1, corrected_x))
                corrected_y = max(0, min(image_height - 1, corrected_y))
                
                corrected_keypoints.append((corrected_x, corrected_y))
            
            return corrected_keypoints
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 키포인트 좌표 보정 오류: {e}")
            return keypoints
    
    def is_camera_stable(self, stability_threshold: float = 0.1) -> bool:
        """
        카메라 자세 안정성 확인
        
        Args:
            stability_threshold: 안정성 임계값 (라디안)
            
        Returns:
            bool: 카메라가 안정된 상태인지 여부
        """
        try:
            if len(self.pose_history) < 10:
                return False
            
            # 최근 10개 자세 데이터 분석
            recent_poses = list(self.pose_history)[-10:]
            
            # 각 축별 변화량 계산
            roll_variance = np.var([pose.roll for pose in recent_poses])
            pitch_variance = np.var([pose.pitch for pose in recent_poses])
            yaw_variance = np.var([pose.yaw for pose in recent_poses])
            
            # 전체 변화량 계산
            total_variance = roll_variance + pitch_variance + yaw_variance
            
            is_stable = total_variance < stability_threshold
            
            logger.debug(f"[IMU Fusion] 카메라 안정성: {'안정' if is_stable else '불안정'} "
                        f"(변화량: {total_variance:.4f})")
            
            return is_stable
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 카메라 안정성 확인 오류: {e}")
            return False
    
    def get_pose_correction_info(self) -> Dict[str, Any]:
        """카메라 자세 보정 정보 반환"""
        try:
            current_pose = self.get_current_camera_pose()
            
            info = {
                "correction_enabled": self.camera_correction['correction_enabled'],
                "calibration_set": self.camera_correction['intrinsic_matrix'] is not None,
                "pose_history_size": len(self.pose_history),
                "camera_stable": self.is_camera_stable(),
            }
            
            if current_pose:
                info.update({
                    "current_roll_deg": math.degrees(current_pose.roll),
                    "current_pitch_deg": math.degrees(current_pose.pitch),
                    "current_yaw_deg": math.degrees(current_pose.yaw),
                    "tilt_angle_deg": math.degrees(
                        math.sqrt(current_pose.pitch**2 + current_pose.roll**2)
                    )
                })
            
            return info
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 자세 보정 정보 조회 오류: {e}")
            return {"error": str(e)}
    
    def process_complete_measurement_cycle(self, cv_image: np.ndarray, imu_data: IMUData) -> Dict[str, Any]:
        """
        완전한 측정 사이클 처리 (MediaPipe + FastDepth + IMU 통합)
        
        Args:
            cv_image: OpenCV 이미지
            imu_data: IMU 센서 데이터
            
        Returns:
            Dict: 통합 측정 결과
        """
        try:
            measurement_start_time = time.time()
            
            # 1. IMU 데이터 추가 및 처리
            imu_success = self.add_imu_data(imu_data)
            
            # 2. 현재 카메라 자세 계산
            camera_pose = self.get_current_camera_pose()
            
            # 3. MediaPipe로 발 키포인트 감지
            from utils.mediapipe_pose_processor import get_mediapipe_pose_processor
            mediapipe_processor = get_mediapipe_pose_processor(enable_imu_fusion=True)
            
            keypoints = mediapipe_processor.extract_foot_keypoints(cv_image)
            foot_positions_3d = None
            
            if keypoints:
                foot_positions_3d = mediapipe_processor.convert_to_3d_coordinates(keypoints, cv_image)
            
            # 4. IMU 기반 깊이 보정 적용
            corrected_results = {}
            if foot_positions_3d:
                height, width = cv_image.shape[:2]
                
                # 왼발 보정
                if foot_positions_3d.left_foot:
                    left_correction = self.correct_depth_with_pose(
                        original_depth=foot_positions_3d.left_foot.depth_m,
                        pixel_x=int(foot_positions_3d.left_foot.pixel_x),
                        pixel_y=int(foot_positions_3d.left_foot.pixel_y),
                        image_width=width,
                        image_height=height
                    )
                    corrected_results['left_foot'] = left_correction
                
                # 오른발 보정
                if foot_positions_3d.right_foot:
                    right_correction = self.correct_depth_with_pose(
                        original_depth=foot_positions_3d.right_foot.depth_m,
                        pixel_x=int(foot_positions_3d.right_foot.pixel_x),
                        pixel_y=int(foot_positions_3d.right_foot.pixel_y),
                        image_width=width,
                        image_height=height
                    )
                    corrected_results['right_foot'] = right_correction
            
            # 5. 비전-IMU 데이터 융합
            fusion_results = {}
            if foot_positions_3d:
                current_time = time.time()
                
                # 왼발 융합
                if foot_positions_3d.left_foot:
                    left_pos = foot_positions_3d.left_foot
                    corrected_depth = (corrected_results['left_foot'].corrected_depth 
                                     if 'left_foot' in corrected_results else left_pos.depth_m)
                    
                    fused_left = self.fuse_with_vision(
                        vision_x=left_pos.x_m,
                        vision_y=left_pos.y_m,
                        vision_z=corrected_depth,
                        foot_side='left',
                        timestamp=current_time
                    )
                    fusion_results['left_foot'] = fused_left
                
                # 오른발 융합
                if foot_positions_3d.right_foot:
                    right_pos = foot_positions_3d.right_foot
                    corrected_depth = (corrected_results['right_foot'].corrected_depth 
                                     if 'right_foot' in corrected_results else right_pos.depth_m)
                    
                    fused_right = self.fuse_with_vision(
                        vision_x=right_pos.x_m,
                        vision_y=right_pos.y_m,
                        vision_z=corrected_depth,
                        foot_side='right',
                        timestamp=current_time
                    )
                    fusion_results['right_foot'] = fused_right
            
            # 6. 걸음 예측 정보
            step_prediction = self.get_step_prediction()
            walking_state = self.get_walking_state()
            
            # 7. 현재 시스템 상태
            current_imu_state = self.get_current_imu_state()
            
            processing_time = time.time() - measurement_start_time
            
            # 8. 통합 결과 구성
            integrated_result = {
                'timestamp': measurement_start_time,
                'processing_time_ms': int(processing_time * 1000),
                'success': imu_success and keypoints is not None,
                
                # IMU 관련
                'imu_data': {
                    'success': imu_success,
                    'current_state': current_imu_state.__dict__ if current_imu_state else None,
                    'camera_pose': camera_pose.__dict__ if camera_pose else None,
                    'camera_stable': self.is_camera_stable()
                },
                
                # 비전 관련
                'vision_data': {
                    'keypoints_detected': keypoints is not None,
                    'foot_positions_3d': foot_positions_3d.__dict__ if foot_positions_3d else None,
                    'corrected_depths': corrected_results,
                },
                
                # 융합 결과
                'fusion_results': fusion_results,
                
                # 걸음 관련
                'step_analysis': {
                    'walking_state': walking_state,
                    'step_prediction': step_prediction,
                    'total_detected_steps': self.get_step_count()
                },
                
                # 시스템 통계
                'system_stats': {
                    'fusion_stats': self.get_fusion_statistics(),
                    'pose_correction_info': self.get_pose_correction_info()
                }
            }
            
            logger.info(f"[IMU Fusion] 통합 측정 사이클 완료 ({processing_time*1000:.1f}ms): "
                       f"IMU={'✓' if imu_success else '✗'}, "
                       f"비전={'✓' if keypoints else '✗'}, "
                       f"융합={'✓' if fusion_results else '✗'}")
            
            return integrated_result
            
        except Exception as e:
            logger.error(f"[IMU Fusion] 통합 측정 사이클 오류: {e}")
            return {
                'timestamp': time.time(),
                'success': False,
                'error': str(e),
                'processing_time_ms': int((time.time() - measurement_start_time) * 1000)
            }

# 싱글톤 인스턴스
_imu_fusion_processor = None

def get_imu_fusion_processor() -> IMUFusionProcessor:
    """IMU 융합 프로세서 싱글톤 인스턴스 반환"""
    global _imu_fusion_processor
    if _imu_fusion_processor is None:
        _imu_fusion_processor = IMUFusionProcessor()
        logger.info("[IMU Fusion] 싱글톤 인스턴스 생성")
    return _imu_fusion_processor