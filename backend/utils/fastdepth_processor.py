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

# StepLengthResult는 models.step_models.StepCalculationResult로 대체
# 하위 호환성을 위한 별칭
StepLengthResult = StepCalculationResult

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
        self.frame_processing_stats = {
            "total_processed": 0,
            "valid_frames": 0,
            "invalid_frames": 0,
            "average_processing_time": 0.0
        }
    
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
            
            logger.debug(f"[FastDepth] 프레임 변환 완료 (처리시간: {processing_time:.3f}s)")
            
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
    
    def preprocess_for_depth_estimation(self, frame_data: FastDepthFrameData) -> Dict[str, Any]:
        """
        깊이 추정을 위한 전처리
        
        Args:
            frame_data: 전처리할 프레임 데이터
            
        Returns:
            전처리된 데이터
        """
        try:
            processed = self.convert_frame_to_dict(frame_data)
            
            # 좌표 정규화
            normalized_data = self._normalize_coordinates(processed.frame_dict)
            
            # 노이즈 필터링
            filtered_data = self._apply_noise_filter(normalized_data)
            
            # 깊이 보정
            calibrated_data = self._calibrate_depth_values(filtered_data)
            
            # 전처리 메타데이터 추가
            calibrated_data['preprocessing'] = {
                'normalization_applied': True,
                'noise_filter_applied': True,
                'depth_calibration_applied': True,
                'original_confidence': processed.confidence_score,
                'preprocessing_timestamp': time.time()
            }
            
            logger.debug("[FastDepth] 깊이 추정 전처리 완료")
            return calibrated_data
            
        except Exception as e:
            logger.error(f"[FastDepth] 깊이 추정 전처리 실패: {e}")
            raise ValueError(f"전처리 실패: {str(e)}")
    
    def postprocess_for_step_calculation(
        self,
        frame_sequence: List[Dict[str, Any]],
        measurement_method: str = "kalman_filter"
    ) -> StepCalculationResult:
        """
        보폭 계산을 위한 후처리
        
        Args:
            frame_sequence: 프레임 시퀀스 데이터
            measurement_method: 측정 방법 ("kalman_filter", "simple_distance")
            
        Returns:
            StepLengthResult: 보폭 계산 결과
        """
        try:
            if not frame_sequence:
                raise ValueError("프레임 시퀀스가 비어있습니다")
            
            logger.info(f"[FastDepth] 통합 보폭 계산 시작 - 방법: {measurement_method}, 프레임 수: {len(frame_sequence)}")
            
            # 통합 계산기 사용 (지연 import로 순환 참조 방지)
            from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
            
            calculator = get_unified_step_calculator()
            
            # 입력 데이터 준비
            input_data = StepCalculationInput(
                frame_sequence=frame_sequence,
                preferred_method=(
                    StepMeasurementMethod.KALMAN_FILTER 
                    if measurement_method == "kalman_filter" 
                    else StepMeasurementMethod.DISTANCE_BASED
                ),
                force_fallback=(measurement_method == "simple_distance")
            )
            
            # 통합 계산 실행
            result = calculator.calculate_step_length(input_data)
            
            logger.info(f"[FastDepth] 통합 보폭 계산 완료: {result.step_length_cm}cm (신뢰도: {result.confidence:.2f})")
            return result
            
        except Exception as e:
            logger.error(f"[FastDepth] 통합 보폭 계산 후처리 실패: {e}")
            # 응급 대안으로 로컬 단순 계산 시도
            logger.warning("[FastDepth] 응급 로컬 계산 시도")
            return self._emergency_local_calculation(frame_sequence, str(e))
    
    def _normalize_coordinates(self, frame_dict: Dict[str, Any]) -> Dict[str, Any]:
        """좌표 정규화"""
        normalized = frame_dict.copy()
        
        for foot_key in ['left_foot', 'right_foot']:
            if foot_key in normalized:
                foot_data = normalized[foot_key]
                # Z 좌표 정규화 (0-10m 범위를 0-1로)
                if 'z' in foot_data:
                    foot_data['z_normalized'] = np.clip(foot_data['z'] / self.max_depth_range, 0, 1)
                
                # XY 좌표 정규화 (-50~50m 범위를 -1~1로)
                if 'x' in foot_data:
                    foot_data['x_normalized'] = np.clip(foot_data['x'] / 50.0, -1, 1)
                if 'y' in foot_data:
                    foot_data['y_normalized'] = np.clip(foot_data['y'] / 50.0, -1, 1)
        
        return normalized
    
    def _apply_noise_filter(self, frame_dict: Dict[str, Any]) -> Dict[str, Any]:
        """노이즈 필터링 적용"""
        filtered = frame_dict.copy()
        
        for foot_key in ['left_foot', 'right_foot']:
            if foot_key in filtered:
                foot_data = filtered[foot_key]
                
                # 신뢰도 기반 필터링
                if foot_data.get('confidence', 0) < self.min_confidence:
                    foot_data['filtered'] = True
                    foot_data['filter_reason'] = 'low_confidence'
                
                # 극값 필터링
                if foot_data.get('z', 0) > self.max_depth_range * 0.9:
                    foot_data['filtered'] = True
                    foot_data['filter_reason'] = 'extreme_depth'
        
        return filtered
    
    def _calibrate_depth_values(self, frame_dict: Dict[str, Any]) -> Dict[str, Any]:
        """깊이 값 보정"""
        calibrated = frame_dict.copy()
        
        # 간단한 선형 보정 (실제 환경에서는 더 복잡한 보정 필요)
        depth_calibration_factor = 1.05  # 5% 보정
        
        for foot_key in ['left_foot', 'right_foot']:
            if foot_key in calibrated and not calibrated[foot_key].get('filtered', False):
                foot_data = calibrated[foot_key]
                if 'z' in foot_data:
                    foot_data['z_calibrated'] = foot_data['z'] * depth_calibration_factor
        
        return calibrated
    
    def _calculate_step_length_kalman(self, frame_sequence: List[Dict[str, Any]]) -> StepCalculationResult:
        """칼만 필터 기반 보폭 계산"""
        # 실제 칼만 필터 구현 대신 시뮬레이션
        valid_frames = [f for f in frame_sequence if not self._is_frame_filtered(f)]
        
        if len(valid_frames) < 2:
            raise ValueError("유효한 프레임이 부족합니다 (최소 2개 필요)")
        
        # 거리 계산 시뮬레이션
        total_distance = 0.0
        step_count = 0
        confidence_scores = []
        
        for i in range(1, len(valid_frames)):
            prev_frame = valid_frames[i-1]
            curr_frame = valid_frames[i]
            
            # 발 위치 변화 계산
            distance = self._calculate_frame_distance(prev_frame, curr_frame)
            if distance > 0.1:  # 최소 이동 거리
                total_distance += distance
                step_count += 1
            
            # 신뢰도 수집
            frame_confidence = self._get_frame_confidence(curr_frame)
            confidence_scores.append(frame_confidence)
        
        if step_count == 0:
            raise ValueError("유효한 스텝이 감지되지 않았습니다")
        
        # UnifiedStepCalculator로 계산 위임
        from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
        
        calculator = get_unified_step_calculator()
        input_data = StepCalculationInput(
            distance_meters=total_distance,
            step_count=step_count,
            preferred_method=StepMeasurementMethod.KALMAN_FILTER,
            force_fallback=True  # 이미 계산된 데이터이므로 직접 계산 사용
        )
        
        result = calculator.calculate_step_length(input_data)
        
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
        응급 로컬 계산 - UnifiedStepCalculator 호출 실패 시에만 사용
        
        Note: 가능한 한 UnifiedStepCalculator 사용을 권장하며, 이는 최후의 수단입니다.
        """
        logger.warning(f"[FastDepth] 응급 로컬 계산 실행: {error}")
        
        try:
            # 마지막 시도: UnifiedStepCalculator의 단순 fallback 사용
            from services.unified_step_calculator import get_unified_step_calculator, StepCalculationInput
            
            valid_frames = [f for f in frame_sequence if not self._is_frame_filtered(f)]
            
            if len(valid_frames) >= 2:
                # 거리 기반 계산을 위한 데이터 준비
                first_frame = valid_frames[0]
                last_frame = valid_frames[-1]
                distance = self._calculate_frame_distance(first_frame, last_frame)
                estimated_steps = max(len(valid_frames) // 3, 1)
                
                # UnifiedStepCalculator의 단순 fallback 사용
                calculator = get_unified_step_calculator()
                input_data = StepCalculationInput(
                    distance_meters=distance,
                    step_count=estimated_steps,
                    preferred_method=StepMeasurementMethod.DISTANCE_BASED,
                    force_fallback=True  # 응급 계산이므로 fallback 강제
                )
                
                result = calculator.calculate_step_length(input_data)
                
                # 응급 계산임을 표시하기 위해 source_data 업데이트
                result.source_data.update({
                    "emergency_fallback": True,
                    "original_error": error,
                    "frame_count": len(frame_sequence),
                    "valid_frame_count": len(valid_frames)
                })
                
                return result
                
            else:
                # 정말 최후의 수단: 기본 보폭값 반환
                logger.error("[FastDepth] 프레임 부족 - 기본 보폭값 사용")
                return StepCalculationResult(
                    step_length_cm=65.0,  # 평균적인 보폭
                    confidence=0.1,
                    step_count=len(frame_sequence),
                    tracking_quality=AccuracyConverter.confidence_to_quality(0.1),
                    accuracy_level=AccuracyConverter.confidence_to_korean_level(0.1),
                    measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                    source_data={
                        "method": "absolute_emergency_default",
                        "error": error,
                        "frame_count": len(frame_sequence),
                        "warning": "모든 계산 불가 - 기본값 사용"
                    }
                )
                
        except Exception as emergency_error:
            logger.error(f"[FastDepth] 응급 계산조차 실패: {emergency_error}")
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
                    "emergency_error": str(emergency_error),
                    "warning": "모든 계산 실패 - 절대 기본값"
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

# 싱글톤 인스턴스
_fastdepth_processor = None

def get_fastdepth_processor() -> FastDepthProcessor:
    """FastDepthProcessor 싱글톤 인스턴스 반환"""
    global _fastdepth_processor
    if _fastdepth_processor is None:
        _fastdepth_processor = FastDepthProcessor()
    return _fastdepth_processor