"""FastDepth 프레임 처리 통합 유틸리티

이 모듈은 FastDepth 관련 모든 프레임 처리 로직을 통합합니다:
- 프레임 데이터 변환
- 깊이 추정을 위한 전처리
- 보폭 계산을 위한 후처리
- 유효하지 않은 프레임에 대한 오류 처리
"""

import time
import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime

from models.fastdepth_models import FastDepthFrameData, FastDepthFootData

# 통합 스텝 모델 import
from models.step_models import (
    StepCalculationResult,
    StepMeasurementMethod,
    AccuracyConverter
)

# 통합 계산기 import (순환 import 방지를 위해 지연 import)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.unified_step_calculator import UnifiedStepCalculator, StepCalculationInput

logger = logging.getLogger(__name__)

@dataclass
class ProcessedFrameData:
    """처리된 프레임 데이터"""
    frame_dict: Dict[str, Any]
    timestamp: float
    has_left_foot: bool
    has_right_foot: bool
    confidence_score: float
    processing_time: float

@dataclass
class FrameSequenceBuffer:
    """프레임 시퀀스 버퍼 관리"""
    user_id: str
    frames: List[Dict[str, Any]]
    max_frames: int = 10
    min_frames_for_kalman: int = 5
    last_update: float = 0.0
    
    def add_frame(self, frame_dict: Dict[str, Any]) -> None:
        """새 프레임 추가"""
        frame_dict['buffer_timestamp'] = time.time()
        self.frames.append(frame_dict)
        self.last_update = time.time()
        
        # 최대 프레임 수 제한
        if len(self.frames) > self.max_frames:
            self.frames.pop(0)  # 가장 오래된 프레임 제거
    
    def get_recent_sequence(self) -> List[Dict[str, Any]]:
        """최근 프레임 시퀀스 반환"""
        return self.frames.copy()
    
    def is_ready_for_kalman(self) -> bool:
        """칼만 필터 사용 가능한지 확인"""
        return len(self.frames) >= self.min_frames_for_kalman
    
    def clear_old_frames(self, max_age_seconds: float = 30.0) -> None:
        """오래된 프레임들 정리"""
        current_time = time.time()
        self.frames = [
            frame for frame in self.frames 
            if current_time - frame.get('buffer_timestamp', 0) < max_age_seconds
        ]


@dataclass
class FrameValidationResult:
    """프레임 검증 결과"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    confidence_score: float

class FastDepthProcessor:
    """FastDepth 프레임 처리 통합 클래스"""
    
    def __init__(self):
        self.min_confidence = 0.3
        self.max_depth_range = 10.0  # 미터
        self.min_depth_range = 0.1   # 미터
        
        # 프레임 시퀀스 버퍼링 시스템
        self.frame_buffers: Dict[str, FrameSequenceBuffer] = {}
        self.buffer_cleanup_interval = 60.0  # 1분마다 정리
        self.last_cleanup = time.time()
        
        self.frame_processing_stats = {
            "total_processed": 0,
            "valid_frames": 0,
            "invalid_frames": 0,
            "average_processing_time": 0.0,
            "kalman_calculations": 0,
            "sequence_calculations": 0
        }
    
    def get_or_create_buffer(self, user_id: str) -> FrameSequenceBuffer:
        """사용자별 프레임 버퍼 가져오기 또는 생성"""
        if user_id not in self.frame_buffers:
            self.frame_buffers[user_id] = FrameSequenceBuffer(
                user_id=user_id,
                frames=[]
            )
        return self.frame_buffers[user_id]
    
    def cleanup_old_buffers(self) -> None:
        """오래된 버퍼들 정리"""
        current_time = time.time()
        if current_time - self.last_cleanup < self.buffer_cleanup_interval:
            return
        
        # 30분 이상 사용되지 않은 버퍼 제거
        inactive_threshold = 30 * 60  # 30분
        users_to_remove = []
        
        for user_id, buffer in self.frame_buffers.items():
            if current_time - buffer.last_update > inactive_threshold:
                users_to_remove.append(user_id)
            else:
                buffer.clear_old_frames()
        
        for user_id in users_to_remove:
            del self.frame_buffers[user_id]
        
        self.last_cleanup = current_time
    
    def extract_foot_positions_from_frame(self, frame_dict: Dict[str, Any]) -> Tuple[Optional['FootPosition'], Optional['FootPosition']]:
        """
        프레임에서 발 위치 데이터 추출 (칼만 필터용)
        
        Args:
            frame_dict: FastDepth 프레임 딕셔너리
            
        Returns:
            Tuple[left_foot_pos, right_foot_pos]: 발 위치 데이터 (없으면 None)
        """
        try:
            # 지연 import로 순환 참조 방지
            from models.fastdepth_models import FastDepthFootData as FootPosition
            
            left_foot_pos = None
            right_foot_pos = None
            
            # 왼발 데이터 추출
            if 'left_foot' in frame_dict:
                left_data = frame_dict['left_foot']
                if (left_data.get('confidence', 0) >= self.min_confidence and 
                    not left_data.get('filtered', False)):
                    
                    left_foot_pos = FootPosition(
                        x=float(left_data.get('x', 0)),
                        y=float(left_data.get('y', 0)), 
                        z=float(left_data.get('z', 0)),
                        confidence=float(left_data.get('confidence', 0)),
                        timestamp=frame_dict.get('timestamp', time.time())
                    )
            
            # 오른발 데이터 추출
            if 'right_foot' in frame_dict:
                right_data = frame_dict['right_foot']
                if (right_data.get('confidence', 0) >= self.min_confidence and 
                    not right_data.get('filtered', False)):
                    
                    right_foot_pos = FootPosition(
                        x=float(right_data.get('x', 0)),
                        y=float(right_data.get('y', 0)),
                        z=float(right_data.get('z', 0)),
                        confidence=float(right_data.get('confidence', 0)),
                        timestamp=frame_dict.get('timestamp', time.time())
                    )
            
            return left_foot_pos, right_foot_pos
            
        except Exception as e:
            logger.error(f"발 위치 추출 오류: {e}")
            return None, None
    
    def convert_frame_sequence_to_foot_positions(self, frame_sequence: List[Dict[str, Any]]) -> Tuple[List['FootPosition'], List['FootPosition']]:
        """
        프레임 시퀀스를 발 위치 리스트로 변환
        
        Args:
            frame_sequence: 프레임 딕셔너리들의 리스트
            
        Returns:
            Tuple[left_positions, right_positions]: 발 위치 리스트들
        """
        left_positions = []
        right_positions = []
        
        for frame_dict in frame_sequence:
            left_pos, right_pos = self.extract_foot_positions_from_frame(frame_dict)
            
            if left_pos:
                left_positions.append(left_pos)
            if right_pos:
                right_positions.append(right_pos)
        
        return left_positions, right_positions
    
    def _calculate_with_direct_kalman_filter(self, frame_sequence: List[Dict[str, Any]]) -> Optional[StepCalculationResult]:
        """
        순환 참조 방지를 위해 칼만 필터를 직접 호출
        
        Args:
            frame_sequence: 프레임 시퀀스 데이터
            
        Returns:
            StepCalculationResult: 칼만 필터 계산 결과 또는 None
        """
        try:
            # 순환 참조 방지를 위한 지연 import
            from services.kalman_step_filter import RealTimeStepTracker
            
            # 프레임 시퀀스를 발 위치 데이터로 변환
            left_positions, right_positions = self.convert_frame_sequence_to_foot_positions(frame_sequence)
            
            if not left_positions and not right_positions:
                logger.warning("[FastDepth] 발 위치 데이터가 없어 칼만 필터 사용 불가")
                return None
            
            # 새로운 칼만 추적기 인스턴스 생성 (세션별)
            tracker = RealTimeStepTracker()
            
            # 발 위치 데이터를 순서대로 추가
            for pos in left_positions:
                tracker.add_foot_measurement("left", pos)
            
            for pos in right_positions:
                tracker.add_foot_measurement("right", pos)
            
            # 칼만 필터 결과 가져오기
            result = tracker.get_current_step_result()
            
            # FastDepth 처리 정보 추가
            if result:
                result.source_data.update({
                    "method": "direct_kalman_filter",
                    "fastdepth_frame_count": len(frame_sequence),
                    "left_foot_points": len(left_positions),
                    "right_foot_points": len(right_positions),
                    "tracking_mode": "direct_fastdepth_integration"
                })
                
            
            return result
            
        except Exception as e:
            logger.error(f"[FastDepth] 직접 칼만 필터 호출 실패: {e}")
            return None
    
    def validate_frame(self, frame_data: FastDepthFrameData) -> FrameValidationResult:
        """
        FastDepth 프레임 데이터 검증
        
        Args:
            frame_data: 검증할 프레임 데이터
            
        Returns:
            FrameValidationResult: 검증 결과
        """
        errors = []
        warnings = []
        confidence_scores = []
        
        try:
            # 기본 구조 검증
            if not frame_data:
                errors.append("프레임 데이터가 비어있습니다")
                return FrameValidationResult(False, errors, warnings, 0.0)
            
            # 발 데이터 존재 확인
            if not frame_data.left_foot and not frame_data.right_foot:
                errors.append("왼발 또는 오른발 데이터 중 하나는 필수입니다")
                return FrameValidationResult(False, errors, warnings, 0.0)
            
            # 왼발 데이터 검증
            if frame_data.left_foot:
                left_validation = self._validate_foot_data(frame_data.left_foot, "왼발")
                errors.extend(left_validation["errors"])
                warnings.extend(left_validation["warnings"])
                confidence_scores.append(left_validation["confidence"])
            
            # 오른발 데이터 검증
            if frame_data.right_foot:
                right_validation = self._validate_foot_data(frame_data.right_foot, "오른발")
                errors.extend(right_validation["errors"])
                warnings.extend(right_validation["warnings"])
                confidence_scores.append(right_validation["confidence"])
            
            # 타임스탬프 검증
            if frame_data.timestamp and frame_data.timestamp <= 0:
                warnings.append("타임스탬프가 유효하지 않습니다")
            
            # 전체 신뢰도 계산
            overall_confidence = np.mean(confidence_scores) if confidence_scores else 0.0
            
            # 낮은 신뢰도 경고
            if overall_confidence < self.min_confidence:
                warnings.append(f"전체 신뢰도가 낮습니다: {overall_confidence:.2f}")
            
            is_valid = len(errors) == 0
            
            return FrameValidationResult(
                is_valid=is_valid,
                errors=errors,
                warnings=warnings,
                confidence_score=overall_confidence
            )
            
        except Exception as e:
            logger.error(f"프레임 검증 중 오류: {e}")
            errors.append(f"검증 프로세스 오류: {str(e)}")
            return FrameValidationResult(False, errors, warnings, 0.0)
    
    def _validate_foot_data(self, foot_data: FastDepthFootData, foot_name: str) -> Dict[str, Any]:
        """개별 발 데이터 검증"""
        errors = []
        warnings = []
        
        # 좌표 범위 검증
        if not (-50.0 <= foot_data.x <= 50.0):
            errors.append(f"{foot_name} X 좌표가 유효 범위를 벗어났습니다: {foot_data.x}")
        
        if not (-50.0 <= foot_data.y <= 50.0):
            errors.append(f"{foot_name} Y 좌표가 유효 범위를 벗어났습니다: {foot_data.y}")
        
        # 깊이(Z) 검증
        if not (self.min_depth_range <= foot_data.z <= self.max_depth_range):
            if foot_data.z <= 0:
                errors.append(f"{foot_name} 깊이가 음수입니다: {foot_data.z}")
            else:
                warnings.append(f"{foot_name} 깊이가 예상 범위를 벗어났습니다: {foot_data.z}m")
        
        # 신뢰도 검증
        if not (0.0 <= foot_data.confidence <= 1.0):
            errors.append(f"{foot_name} 신뢰도가 유효 범위(0-1)를 벗어났습니다: {foot_data.confidence}")
        elif foot_data.confidence < self.min_confidence:
            warnings.append(f"{foot_name} 신뢰도가 낮습니다: {foot_data.confidence}")
        
        return {
            "errors": errors,
            "warnings": warnings,
            "confidence": foot_data.confidence
        }
    
    def convert_frame_to_dict(self, frame_data: FastDepthFrameData) -> ProcessedFrameData:
        """
        FastDepth 프레임 데이터를 딕셔너리로 변환 (통합 버전)
        
        Args:
            frame_data: 변환할 프레임 데이터
            
        Returns:
            ProcessedFrameData: 처리된 프레임 데이터
            
        Raises:
            ValueError: 프레임 데이터가 유효하지 않은 경우
        """
        start_time = time.time()
        
        try:
            # 프레임 검증
            validation = self.validate_frame(frame_data)
            if not validation.is_valid:
                raise ValueError(f"유효하지 않은 프레임: {', '.join(validation.errors)}")
            
            # 경고 로깅
            if validation.warnings:
                for warning in validation.warnings:
                    logger.warning(f"[FastDepth] {warning}")
            
            # 딕셔너리 변환
            frame_dict = {}
            
            # 왼발 데이터 변환
            if frame_data.left_foot:
                frame_dict['left_foot'] = {
                    'x': float(frame_data.left_foot.x),
                    'y': float(frame_data.left_foot.y),
                    'z': float(frame_data.left_foot.z),
                    'confidence': float(frame_data.left_foot.confidence)
                }
            
            # 오른발 데이터 변환
            if frame_data.right_foot:
                frame_dict['right_foot'] = {
                    'x': float(frame_data.right_foot.x),
                    'y': float(frame_data.right_foot.y),
                    'z': float(frame_data.right_foot.z),
                    'confidence': float(frame_data.right_foot.confidence)
                }
            
            # 타임스탬프 처리
            timestamp = frame_data.timestamp or time.time()
            frame_dict['timestamp'] = float(timestamp)
            
            # 메타데이터 추가
            frame_dict['validation'] = {
                'confidence_score': validation.confidence_score,
                'warnings': validation.warnings,
                'processed_at': datetime.now().isoformat()
            }
            
            processing_time = time.time() - start_time
            
            # 통계 업데이트
            self._update_processing_stats(processing_time, True)
            
            
            return ProcessedFrameData(
                frame_dict=frame_dict,
                timestamp=timestamp,
                has_left_foot=frame_data.left_foot is not None,
                has_right_foot=frame_data.right_foot is not None,
                confidence_score=validation.confidence_score,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            self._update_processing_stats(processing_time, False)
            logger.error(f"[FastDepth] 프레임 변환 실패: {e}")
            raise ValueError(f"프레임 변환 실패: {str(e)}")
    
    
    def postprocess_for_step_calculation(
        self,
        frame_sequence: List[Dict[str, Any]],
        measurement_method: str = "kalman_filter"
    ) -> StepCalculationResult:
        """
        보폭 계산을 위한 후처리 - 순환 참조 방지를 위해 직접 칼만 필터 호출
        
        Args:
            frame_sequence: 프레임 시퀀스 데이터
            measurement_method: 측정 방법 ("kalman_filter", "simple_distance")
            
        Returns:
            StepCalculationResult: 보폭 계산 결과
        """
        try:
            if not frame_sequence:
                raise ValueError("프레임 시퀀스가 비어있습니다")
            
            
            # 칼만 필터 방법 시도
            if measurement_method == "kalman_filter" and len(frame_sequence) >= 3:
                result = self._calculate_with_direct_kalman_filter(frame_sequence)
                if result and result.confidence >= 0.3:
                    self.frame_processing_stats["kalman_calculations"] += 1
                    return result
                else:
                    logger.warning("[FastDepth] 칼만 필터 신뢰도 낮음 - 단순 방법으로 fallback")
            
            # UnifiedStepCalculator의 단순 fallback 사용
            from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
            
            valid_frames = [f for f in frame_sequence if not self._is_frame_filtered(f)]
            if len(valid_frames) >= 2:
                first_frame = valid_frames[0]
                last_frame = valid_frames[-1]
                distance = self._calculate_frame_distance(first_frame, last_frame)
                estimated_steps = max(len(valid_frames) // 3, 1)
                
                calculator = get_unified_step_calculator()
                input_data = StepCalculationInput(
                    distance_meters=distance,
                    step_count=estimated_steps,
                    preferred_method=StepMeasurementMethod.DISTANCE_BASED,
                    force_fallback=True
                )
                result = calculator.calculate_step_length(input_data)
            else:
                raise ValueError("유효한 프레임 부족")
            self.frame_processing_stats["sequence_calculations"] += 1
            return result
            
        except Exception as e:
            logger.error(f"[FastDepth] 통합 보폭 계산 후처리 실패: {e}")
            # 응급 대안으로 로컬 단순 계산 시도
            logger.warning("[FastDepth] 응급 로컬 계산 시도")
            return self._emergency_local_calculation(frame_sequence, str(e))
    
    
        
        # FastDepth 처리 정보 추가
        result.source_data.update({
            "fastdepth_total_distance_m": total_distance,
            "fastdepth_step_count": step_count,
            "frame_count": len(frame_sequence),
            "valid_frame_count": len(valid_frames),
            "fastdepth_method": "kalman_filter",
            "frame_confidence": np.mean(confidence_scores)
        })
        
        return result
    
    # _calculate_step_length_simple method removed - use UnifiedStepCalculator exclusively
    
    def _calculate_frame_distance(self, frame1: Dict[str, Any], frame2: Dict[str, Any]) -> float:
        """두 프레임 간의 거리 계산"""
        # 양쪽 발 중 더 신뢰할 수 있는 발 선택
        foot1_data = self._get_best_foot_data(frame1)
        foot2_data = self._get_best_foot_data(frame2)
        
        if not foot1_data or not foot2_data:
            return 0.0
        
        # 3D 거리 계산
        dx = foot2_data['x'] - foot1_data['x']
        dy = foot2_data['y'] - foot1_data['y']
        dz = foot2_data['z'] - foot1_data['z']
        
        distance = np.sqrt(dx**2 + dy**2 + dz**2)
        return float(distance)
    
    def _get_best_foot_data(self, frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """프레임에서 가장 신뢰할 수 있는 발 데이터 반환"""
        left_foot = frame.get('left_foot')
        right_foot = frame.get('right_foot')
        
        if not left_foot and not right_foot:
            return None
        
        if not left_foot:
            return right_foot
        if not right_foot:
            return left_foot
        
        # 신뢰도가 높은 발 선택
        left_confidence = left_foot.get('confidence', 0)
        right_confidence = right_foot.get('confidence', 0)
        
        return left_foot if left_confidence >= right_confidence else right_foot
    
    def _get_frame_confidence(self, frame: Dict[str, Any]) -> float:
        """프레임의 전체 신뢰도 계산"""
        confidences = []
        
        for foot_key in ['left_foot', 'right_foot']:
            foot_data = frame.get(foot_key)
            if foot_data and not foot_data.get('filtered', False):
                confidences.append(foot_data.get('confidence', 0))
        
        return np.mean(confidences) if confidences else 0.0
    
    def _is_frame_filtered(self, frame: Dict[str, Any]) -> bool:
        """프레임이 필터링되었는지 확인"""
        for foot_key in ['left_foot', 'right_foot']:
            foot_data = frame.get(foot_key)
            if foot_data and foot_data.get('filtered', False):
                return True
        return False
    
    def _validate_step_length_result(self, result: StepCalculationResult) -> StepCalculationResult:
        """보폭 계산 결과 검증"""
        # 검증 및 조정된 값들
        adjusted_confidence = result.confidence
        validation_warnings = []
        
        # 보폭 범위 검증 (30-150cm)
        if result.step_length_cm < 30:
            adjusted_confidence *= 0.5
            validation_warnings.append('step_length_too_short')
        elif result.step_length_cm > 150:
            adjusted_confidence *= 0.5
            validation_warnings.append('step_length_too_long')
        
        # 신뢰도 조정
        adjusted_confidence = float(np.clip(adjusted_confidence, 0.0, 1.0))
        
        # 검증 정보가 있는 경우 새로운 source_data 생성
        updated_source_data = result.source_data.copy()
        if validation_warnings:
            updated_source_data['validation_warnings'] = validation_warnings
        updated_source_data['original_confidence'] = result.confidence
        updated_source_data['adjusted_confidence'] = adjusted_confidence
        
        # 새로운 인스턴스 생성 (Pydantic 모델은 불변)
        return result.model_copy(update={
            'confidence': adjusted_confidence,
            'tracking_quality': AccuracyConverter.confidence_to_quality(adjusted_confidence),
            'accuracy_level': AccuracyConverter.confidence_to_korean_level(adjusted_confidence),
            'source_data': updated_source_data
        })
    
    def _emergency_local_calculation(self, frame_sequence: List[Dict[str, Any]], error: str) -> StepCalculationResult:
        """
        응급 계산 - UnifiedStepCalculator._emergency_calculation 위임
        """
        logger.warning(f"[FastDepth] 응급 계산 실행: {error}")
        
        try:
            # UnifiedStepCalculator의 응급 계산 사용
            from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
            
            valid_frames = [f for f in frame_sequence if not self._is_frame_filtered(f)]
            distance = 2.0  # 기본 거리
            steps = max(len(valid_frames) // 3, 1)
            
            if len(valid_frames) >= 2:
                first_frame = valid_frames[0]
                last_frame = valid_frames[-1]
                distance = self._calculate_frame_distance(first_frame, last_frame) or 2.0
            
            calculator = get_unified_step_calculator()
            input_data = StepCalculationInput(
                distance_meters=distance,
                step_count=steps,
                preferred_method=StepMeasurementMethod.DISTANCE_BASED
            )
            
            # UnifiedStepCalculator의 _emergency_calculation 직접 사용
            result = calculator._emergency_calculation(input_data, error)
            result.source_data["fastdepth_emergency"] = True
            return result
            
        except Exception as emergency_error:
            logger.error(f"[FastDepth] 최종 응급 계산 실패: {emergency_error}")
            # 절대 최후의 수단
            return StepCalculationResult(
                step_length_cm=65.0,
                confidence=0.05,
                step_count=1,
                tracking_quality=AccuracyConverter.confidence_to_quality(0.05),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(0.05),
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                source_data={
                    "method": "absolute_fallback",
                    "original_error": error,
                    "emergency_error": str(emergency_error)
                }
            )
    
    def _update_processing_stats(self, processing_time: float, success: bool):
        """처리 통계 업데이트"""
        self.frame_processing_stats["total_processed"] += 1
        
        if success:
            self.frame_processing_stats["valid_frames"] += 1
        else:
            self.frame_processing_stats["invalid_frames"] += 1
        
        # 평균 처리 시간 업데이트
        total = self.frame_processing_stats["total_processed"]
        current_avg = self.frame_processing_stats["average_processing_time"]
        new_avg = ((current_avg * (total - 1)) + processing_time) / total
        self.frame_processing_stats["average_processing_time"] = new_avg
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        return self.frame_processing_stats.copy()
    
    def reset_stats(self):
        """통계 리셋"""
        self.frame_processing_stats = {
            "total_processed": 0,
            "valid_frames": 0,
            "invalid_frames": 0,
            "average_processing_time": 0.0
        }
    
    async def process_frame_for_measurement(self, cv_image, user_id: str = 'current_user') -> Optional[StepCalculationResult]:
        """
        이미지 파일을 프레임 시퀀스 버퍼에 추가하고 칼만 필터로 보폭 측정 처리
        
        Args:
            cv_image: OpenCV 이미지 (numpy.ndarray)
            user_id: 사용자 ID
            
        Returns:
            StepCalculationResult: 보폭 계산 결과, 또는 실패시 None
        """
        try:
            import cv2
            import numpy as np
            
            start_time = time.time()
            logger.info(f'[FastDepth] 시퀀스 기반 이미지 처리 시작: {user_id}')
            
            # 0. 버퍼 정리 (주기적)
            self.cleanup_old_buffers()
            
            # 1. 이미지 검증
            if cv_image is None or cv_image.size == 0:
                raise ValueError('유효하지 않은 이미지')
            
            height, width = cv_image.shape[:2]
            logger.info(f'[FastDepth] 이미지 크기: {width}x{height}')
            
            # 2. 이미지를 FastDepth가 처리할 수 있는 frame_dict 형식으로 변환
            frame_dict = self._convert_cv_image_to_frame_dict(cv_image, user_id)
            
            # 3. 사용자별 프레임 버퍼에 추가
            buffer = self.get_or_create_buffer(user_id)
            buffer.add_frame(frame_dict)
            
            logger.info(f'[FastDepth] 버퍼 상태: {len(buffer.frames)}개 프레임, 칼만 필터 준비: {buffer.is_ready_for_kalman()}')
            
            # 4. 칼만 필터 사용 가능한지 확인
            if buffer.is_ready_for_kalman():
                # 칼만 필터로 계산
                frame_sequence = buffer.get_recent_sequence()
                step_result = self.postprocess_for_step_calculation(frame_sequence, "kalman_filter")
                
                if step_result and step_result.confidence >= 0.3:
                    logger.info(f'[FastDepth] 칼만 필터 성공: {step_result.step_length_cm}cm')
                    self.frame_processing_stats["kalman_calculations"] += 1
                else:
                    # 단순 방법으로 fallback
                    logger.warning('[FastDepth] 칼만 필터 신뢰도 낮음 - 단순 방법 사용')
                    step_result = self.postprocess_for_step_calculation(frame_sequence, "simple_distance")
                    self.frame_processing_stats["sequence_calculations"] += 1
            else:
                # 프레임이 부족하면 단일 프레임 기반 단순 계산
                logger.info(f'[FastDepth] 프레임 부족 ({len(buffer.frames)}개) - 단일 프레임 계산')
                step_result = await self._calculate_step_from_single_frame(frame_dict, user_id)
            
            processing_time = time.time() - start_time
            
            if step_result:
                # 처리 시간 정보 추가
                step_result.source_data.update({
                    "processing_time_ms": int(processing_time * 1000),
                    "image_dimensions": f"{width}x{height}",
                    "direct_image_processing": True
                })
                logger.info(f'[FastDepth] 직접 처리 완료: {step_result.step_length_cm:.1f}cm (처리시간: {processing_time:.3f}s)')
            else:
                logger.warning('[FastDepth] 보폭 계산 실패')
            
            return step_result
            
        except Exception as e:
            logger.error(f'[FastDepth] 직접 이미지 처리 오류: {e}')
            return None

    def _convert_cv_image_to_frame_dict(self, cv_image, user_id: str = 'current_user') -> Dict[str, Any]:
        """
        OpenCV 이미지를 FastDepth가 이해할 수 있는 frame_dict로 변환
        
        Args:
            cv_image: OpenCV 이미지
            user_id: 사용자 ID
            
        Returns:
            Dict: FastDepth 프레임 딕셔너리 형식
        """
        try:
            import cv2
            import base64
            
            # 이미지를 JPEG로 인코딩 (압축률 90%)
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
            result, encimg = cv2.imencode('.jpg', cv_image, encode_param)
            
            if not result:
                raise ValueError('이미지 인코딩 실패')
            
            # Base64로 인코딩
            img_base64 = base64.b64encode(encimg).decode('utf-8')
            
            # 단순화된 frame_dict 형식으로 변환 (실제 측정 시뮬레이션용)
            frame_dict = {
                'frame_data': cv_image.tolist(),  # numpy array를 list로 변환 (API 호환성)
                'frame_data_base64': img_base64,  # Base64 인코딩된 이미지
                'timestamp': time.time(),
                'user_id': user_id,
                'width': cv_image.shape[1],
                'height': cv_image.shape[0],
                'channels': cv_image.shape[2] if len(cv_image.shape) > 2 else 1
            }
            
            logger.debug(f'이미지 변환 완료 - 크기: {cv_image.shape}, Base64 길이: {len(img_base64)}')
            return frame_dict
            
        except Exception as e:
            logger.error(f'이미지 변환 오류: {e}')
            raise

    async def _calculate_step_from_single_frame(self, frame_dict: Dict[str, Any], user_id: str) -> Optional[StepCalculationResult]:
        """
        단일 프레임에서 실제 보폭 계산 - 발 위치 데이터 기반
        
        Args:
            frame_dict: 변환된 프레임 딕셔너리
            user_id: 사용자 ID
            
        Returns:
            StepCalculationResult: 계산 결과 또는 None
        """
        try:
            logger.info(f'[FastDepth] 단일 프레임 실제 보폭 계산 시작: {user_id}')
            
            # 프레임에서 발 위치 데이터 추출
            left_foot_pos, right_foot_pos = self.extract_foot_positions_from_frame(frame_dict)
            
            if not left_foot_pos and not right_foot_pos:
                logger.warning('[FastDepth] 발 위치 데이터 없음 - 계산 불가')
                return None
            
            # 이미지 품질 기반 기본 신뢰도 계산
            width = frame_dict.get('width', 640)
            height = frame_dict.get('height', 480)
            resolution_factor = min(1.0, (width * height) / (1920 * 1080))
            
            # 두 발이 모두 감지된 경우 - 현재 거리 계산
            if left_foot_pos and right_foot_pos:
                # 두 발 사이의 거리 계산 (3D 유클리드 거리)
                dx = left_foot_pos.x - right_foot_pos.x
                dy = left_foot_pos.y - right_foot_pos.y
                dz = left_foot_pos.z - right_foot_pos.z
                foot_distance_m = (dx**2 + dy**2 + dz**2)**0.5
                
                # 발 사이 거리를 보폭으로 사용 (cm 단위)
                step_length_cm = foot_distance_m * 100
                
                # 신뢰도: 두 발의 신뢰도와 해상도 결합
                confidence = (left_foot_pos.confidence + right_foot_pos.confidence) / 2
                confidence = confidence * (0.7 + resolution_factor * 0.3)
                
                # 보폭 합리성 검증
                if 30 <= step_length_cm <= 120:
                    quality_multiplier = 1.0
                elif 25 <= step_length_cm <= 150:
                    quality_multiplier = 0.8
                    logger.warning(f'[FastDepth] 비정상적 보폭 감지: {step_length_cm:.1f}cm')
                else:
                    # 너무 비정상적인 경우 기본값 사용
                    step_length_cm = 65.0
                    quality_multiplier = 0.4
                    logger.warning(f'[FastDepth] 극도로 비정상적 보폭 -> 기본값 사용: {step_length_cm:.1f}cm')
                
                confidence *= quality_multiplier
                method_name = "single_frame_dual_foot"
                
            else:
                # 한 발만 감지된 경우 - 추정 계산
                detected_foot = left_foot_pos or right_foot_pos
                
                # 발 위치의 Z값(깊이)을 기반으로 추정
                depth_m = abs(detected_foot.z)
                estimated_step_cm = min(max(depth_m * 80, 40), 90)  # 깊이 기반 추정
                
                step_length_cm = estimated_step_cm
                confidence = detected_foot.confidence * 0.6 * (0.7 + resolution_factor * 0.3)
                method_name = "single_frame_single_foot"
                logger.info(f'[FastDepth] 단일 발 감지 - 추정 보폭: {step_length_cm:.1f}cm')
            
            # 최종 보정
            step_length_cm = max(30.0, min(120.0, step_length_cm))
            confidence = max(0.2, min(0.95, confidence))
            
            # 결과 생성
            result = StepCalculationResult(
                step_length_cm=round(step_length_cm, 1),
                confidence=round(confidence, 3),
                step_count=1,  # 단일 프레임이므로
                tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                timestamp=frame_dict.get('timestamp', time.time()),
                user_id=user_id,
                source_data={
                    "method": method_name,
                    "image_resolution": f"{width}x{height}",
                    "resolution_factor": round(resolution_factor, 3),
                    "left_foot_detected": left_foot_pos is not None,
                    "right_foot_detected": right_foot_pos is not None,
                    "frame_timestamp": frame_dict.get('timestamp'),
                    "processing_mode": "direct_image_real_calculation"
                }
            )
            
            logger.info(f'[FastDepth] 단일 프레임 계산 완료: {step_length_cm:.1f}cm (신뢰도: {confidence:.3f})')
            return result
            
        except Exception as e:
            logger.error(f'단일 프레임 보폭 계산 오류: {e}')
            return None

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor