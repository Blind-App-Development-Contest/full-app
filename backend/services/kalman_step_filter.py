import numpy as np
import time
from typing import Optional, Dict, List, Tuple
from collections import deque
from models.fastdepth_models import FastDepthFootData as FootPosition
from models.step_models import StepCalculationResult, StepMeasurementMethod, StepTrackingQuality, AccuracyLevel, AccuracyConverter

class KalmanStepFilter:
    """단일 발용 칼만 필터"""
   
    def __init__(self, measurement_noise: float = 0.05, process_noise: float = 0.1):
        self.measurement_noise = measurement_noise
        self.process_noise = process_noise
        self.dt = 1/30.0  # 30fps
        
        # 상태 벡터: [x, y, z, vx, vy, vz]
        self.state = np.zeros(6)
        self.covariance = np.eye(6) * 1.0
        self.initialized = False
        
        # 상태 전이 행렬 (등속도 모델)
        self.F = np.array([
            [1, 0, 0, self.dt, 0, 0],
            [0, 1, 0, 0, self.dt, 0],
            [0, 0, 1, 0, 0, self.dt],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ])
        
        # 측정 행렬 (위치만 측정)
        self.H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0]
        ])
        
        # 프로세스 노이즈 행렬
        q = self.process_noise
        self.Q = q * np.array([
            [self.dt**4/4, 0, 0, self.dt**3/2, 0, 0],
            [0, self.dt**4/4, 0, 0, self.dt**3/2, 0],
            [0, 0, self.dt**4/4, 0, 0, self.dt**3/2],
            [self.dt**3/2, 0, 0, self.dt**2, 0, 0],
            [0, self.dt**3/2, 0, 0, self.dt**2, 0],
            [0, 0, self.dt**3/2, 0, 0, self.dt**2]
        ])
        
        # 측정 노이즈 행렬
        self.R = self.measurement_noise**2 * np.eye(3)
        
        # 품질 추적
        self.confidence = 0.0
        self.prediction_errors = deque(maxlen=10)
   
    def update(self, measurement: Optional[FootPosition]) -> Optional[np.ndarray]:
        """칼만 필터 업데이트"""
        if measurement is None:
            return self._predict_only()
        
        position = np.array([measurement.x, measurement.y, measurement.z])
        
        if not self._is_valid_measurement(position):
            return self._predict_only()
        
        if not self.initialized:
            return self._initialize(position)
        
        # 예측 단계
        self.state = self.F @ self.state
        self.covariance = self.F @ self.covariance @ self.F.T + self.Q
        
        # 측정 노이즈를 신뢰도에 따라 조정
        R_adjusted = self.R / (measurement.confidence + 0.1)
        
        # 업데이트 단계
        innovation = position - self.H @ self.state
        innovation_covariance = self.H @ self.covariance @ self.H.T + R_adjusted
        
        try:
            kalman_gain = self.covariance @ self.H.T @ np.linalg.inv(innovation_covariance)
            
            # 이상치 검증
            if self._validate_innovation(innovation, innovation_covariance):
                self.state = self.state + kalman_gain @ innovation
                self.covariance = (np.eye(6) - kalman_gain @ self.H) @ self.covariance
                self.confidence = min(self.confidence + 0.1, 1.0)
            else:
                self.confidence = max(self.confidence - 0.2, 0.0)
        except np.linalg.LinAlgError:
            # 행렬 역산 실패 시 예측만 수행
            self.confidence = max(self.confidence - 0.1, 0.0)
        
        # 예측 오차 기록
        self.prediction_errors.append(np.linalg.norm(innovation))
        
        return self.state[:3].copy()
   
    def _predict_only(self) -> Optional[np.ndarray]:
        """예측만 수행"""
        if not self.initialized:
            return None
        
        self.state = self.F @ self.state
        self.covariance = self.F @ self.covariance @ self.F.T + self.Q
        self.confidence = max(self.confidence - 0.05, 0.0)
        
        return self.state[:3].copy()
   
    def _initialize(self, position: np.ndarray) -> np.ndarray:
        """필터 초기화"""
        self.state[:3] = position
        self.state[3:] = 0  # 초기 속도는 0
        self.initialized = True
        self.confidence = 0.5
        return position
   
    def _is_valid_measurement(self, position: np.ndarray) -> bool:
        """측정값 유효성 검사"""
        # NaN, 무한값 체크
        if np.any(np.isnan(position)) or np.any(np.isinf(position)):
            return False
        
        # 실내 환경 범위 체크 (0.1m ~ 15m)
        if np.any(position < 0.1) or np.any(position > 15.0):
            return False
        
        # 급격한 변화 체크 (50cm 이상)
        if self.initialized:
            distance = np.linalg.norm(position - self.state[:3])
            if distance > 0.5:
                return False
        
        return True
   
    def _validate_innovation(self, innovation: np.ndarray, S: np.ndarray) -> bool:
        """혁신 검증 (이상치 탐지)"""
        try:
            mahalanobis_dist = innovation.T @ np.linalg.inv(S) @ innovation
            return mahalanobis_dist < 9.21  # 카이제곱 99% 신뢰구간
        except:
            return False
   
    def get_velocity(self) -> np.ndarray:
        """현재 속도 반환"""
        return self.state[3:6].copy() if self.initialized else np.zeros(3)
   
    def get_confidence(self) -> float:
        """필터 신뢰도 반환"""
        return self.confidence
   
    def reset(self):
        """필터 리셋"""
        self.state = np.zeros(6)
        self.covariance = np.eye(6) * 1.0
        self.initialized = False
        self.confidence = 0.0
        self.prediction_errors.clear()

class RealTimeStepTracker:
    """
    실시간 보폭 추적기 - CommandExecutor로부터 상태를 전달받는 순수 계산 엔진
    
    이 클래스는 더 이상 측정 세션 상태(frame_count, start_time)를 직접 관리하지 않습니다.
    CommandExecutor가 Single Source of Truth로 모든 상태를 관리합니다.
    """
   
    def __init__(self):
        # 양발 칼만 필터
        self.left_filter = KalmanStepFilter()
        self.right_filter = KalmanStepFilter()
        
        # 보폭 계산 상태 (순수한 계산 상태만 유지)
        self.step_history = deque(maxlen=20)
        self.step_positions = {'left': deque(maxlen=5), 'right': deque(maxlen=5)}
        self.last_step_time = {'left': 0, 'right': 0}
        
        # 발걸음 검출 상태 (순수한 알고리즘 상태만 유지)
        self.foot_states = {'left': 'air', 'right': 'air'}
        self.step_count = 0  # 보폭 계산을 위한 스텝 카운트 (CommandExecutor의 frame_count와 독립)
   
    def add_foot_measurement(self, foot: str, position: Optional[FootPosition]) -> Dict:
        """
        발 위치 측정값 추가 - 순수한 계산 로직만 수행
        
        프레임 카운팅은 CommandExecutor에서 수행됩니다.
        이 메서드는 오직 칼만 필터링과 스텝 검출만 담당합니다.
        """
        if foot not in ['left', 'right']:
            raise ValueError("foot must be 'left' or 'right'")
        
        filter_obj = self.left_filter if foot == 'left' else self.right_filter
        
        # 칼만 필터 업데이트
        filtered_position = filter_obj.update(position)
        
        step_detected = False
        if filtered_position is not None:
            # 발걸음 검출
            step_detected = self._detect_step(foot, filtered_position, filter_obj.get_velocity())
            
            if step_detected:
                self._calculate_step(foot, filtered_position)
        
        # 프레임 카운트 증가 제거 - CommandExecutor에서 관리
        
        return {
            'filtered_position': filtered_position,
            'confidence': filter_obj.get_confidence(),
            'velocity': filter_obj.get_velocity(),
            'step_detected': step_detected
        }
   
    def _detect_step(self, foot: str, position: np.ndarray, velocity: np.ndarray) -> bool:
        """발걸음 검출"""
        # 발이 땅에 닿았는지 판단
        ground_threshold = 0.08  # 8cm 이내
        velocity_threshold = 0.03  # 3cm/s 이하
        
        is_on_ground = (position[1] < ground_threshold and 
                       abs(velocity[1]) < velocity_threshold)
        
        step_detected = False
        current_time = time.time()
        
        if self.foot_states[foot] == 'air' and is_on_ground:
            # 착지 검출 - 최소 간격 체크
            time_since_last = current_time - self.last_step_time[foot]
            if time_since_last > 0.3:  # 최소 0.3초 간격
                self.foot_states[foot] = 'ground'
                self.step_positions[foot].append(position.copy())
                self.last_step_time[foot] = current_time
                self.step_count += 1
                step_detected = True
                
        elif self.foot_states[foot] == 'ground' and not is_on_ground:
            # 이륙 검출
            self.foot_states[foot] = 'air'
        
        return step_detected
   
    def _calculate_step(self, foot: str, current_position: np.ndarray):
        """보폭 계산"""
        opposite_foot = 'right' if foot == 'left' else 'left'
        opposite_positions = self.step_positions[opposite_foot]
        
        if len(opposite_positions) > 0:
            # 가장 최근 반대편 발 위치와의 거리 계산
            last_opposite_pos = opposite_positions[-1]
            
            # XZ 평면에서의 거리 (Y축은 높이 제외)
            step_length = np.sqrt(
                (current_position[0] - last_opposite_pos[0])**2 + 
                (current_position[2] - last_opposite_pos[2])**2
            )
            
            # 유효한 보폭인지 확인 (30cm ~ 180cm)
            if 0.3 <= step_length <= 1.8:
                self.step_history.append(step_length * 100)  # cm로 변환
   
    def get_current_step_result(self) -> StepCalculationResult:
        """현재 보폭 측정 결과 반환"""
        if len(self.step_history) == 0:
            # Return minimum valid result for empty history
            return StepCalculationResult(
                step_length_cm=1.0,  # Minimum valid value > 0
                confidence=0.0,
                step_count=0,
                tracking_quality=StepTrackingQuality.POOR,
                accuracy_level=AccuracyLevel.LOW,
                measurement_method=StepMeasurementMethod.KALMAN_FILTER,
                source_data={"empty_history": True, "method": "kalman_filter"}
            )
        
        # 평균 보폭 계산 (최근 10개)
        recent_steps = list(self.step_history)[-10:]
        avg_step = np.mean(recent_steps)
        
        # 신뢰도 계산
        left_conf = self.left_filter.get_confidence()
        right_conf = self.right_filter.get_confidence()
        overall_confidence = (left_conf + right_conf) / 2
        
        # 추적 품질 평가
        tracking_quality_str = self._evaluate_tracking_quality(overall_confidence)
        tracking_quality = AccuracyConverter.confidence_to_quality(overall_confidence)
        accuracy_level = AccuracyConverter.confidence_to_korean_level(overall_confidence)
        
        return StepCalculationResult(
            step_length_cm=max(1.0, round(avg_step, 1)),  # Ensure > 0
            confidence=overall_confidence,
            step_count=len(self.step_history),
            tracking_quality=tracking_quality,
            accuracy_level=accuracy_level,
            measurement_method=StepMeasurementMethod.KALMAN_FILTER,
            source_data={
                "method": "kalman_filter",
                "left_confidence": left_conf,
                "right_confidence": right_conf,
                "recent_steps": recent_steps,
                "tracking_quality_raw": tracking_quality_str
            }
        )
   
    def _evaluate_tracking_quality(self, confidence: float) -> str:
        """추적 품질 평가"""
        step_consistency = self._calculate_step_consistency()
        fps = self._calculate_fps()
        
        # 성능 점수 계산
        fps_score = min(fps / 25.0, 1.0)  # 25fps 기준
        combined_score = (confidence * 0.5 + step_consistency * 0.3 + fps_score * 0.2)
        
        if combined_score >= 0.85:
            return "excellent"
        elif combined_score >= 0.7:
            return "good"
        elif combined_score >= 0.5:
            return "fair"
        else:
            return "poor"
   
    def _calculate_step_consistency(self) -> float:
        """보폭 일관성 계산"""
        if len(self.step_history) < 3:
            return 0.0
        
        recent_steps = list(self.step_history)[-10:]
        std_dev = np.std(recent_steps)
        mean_step = np.mean(recent_steps)
        
        if mean_step > 0:
            cv = std_dev / mean_step  # 변동계수
            consistency = max(0, 1 - cv * 2)
        else:
            consistency = 0
        
        return consistency
   
    def get_performance_metrics(self, frame_count: int, start_time: float) -> Dict:
        """
        성능 메트릭 반환 - CommandExecutor로부터 상태를 전달받음
        
        Args:
            frame_count: CommandExecutor에서 관리하는 프레임 수
            start_time: CommandExecutor에서 관리하는 측정 시작 시간
        """
        elapsed_time = time.time() - start_time if start_time else 0
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
        
        return {
            "fps": fps,
            "frame_count": frame_count,  # CommandExecutor에서 전달받은 값 사용
            "left_confidence": self.left_filter.get_confidence(),
            "right_confidence": self.right_filter.get_confidence(),
            "step_consistency": self._calculate_step_consistency(),
            "step_count": self.step_count,  # 스텝 검출 카운트 (프레임 카운트와 다름)
            "elapsed_time": elapsed_time
        }
   
    def reset(self):
        """
        추적기 완전 리셋 - 순수한 계산 상태만 리셋
        
        프레임 카운트와 시작 시간은 CommandExecutor에서 관리하므로 여기서 리셋하지 않습니다.
        """
        self.left_filter.reset()
        self.right_filter.reset()
        self.step_history.clear()
        self.step_positions['left'].clear()
        self.step_positions['right'].clear()
        self.step_count = 0  # 스텝 검출 카운트만 리셋
        self.foot_states = {'left': 'air', 'right': 'air'}
        self.last_step_time = {'left': 0, 'right': 0}
        
        # frame_count, start_time 제거 - CommandExecutor에서 관리
