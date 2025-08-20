from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime

# 통합 스텝 모델 import
from models.step_models import (
    StepMeasurementRequest,
    StepMeasurementResponse,
    StepUpdateRequest,
    StepModelConverter,
    StepMeasurementMethod,
    validate_step_measurement_inputs
)

# 통합 보폭 계산기 import
from services.unified_step_calculator import (
    get_unified_step_calculator,
    StepCalculationInput
)

router = APIRouter()

# 레거시 호환성을 위한 별칭
FootstepDepthMeasurementRequest = StepMeasurementRequest
FootstepDepthMeasurementResponse = StepMeasurementResponse
FootstepUpdateRequest = StepUpdateRequest

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager
command_executor = service_manager.get_command_executor()

def calculate_step_length_from_distance(distance_meters: float, step_count: int) -> dict:
    """
    거리와 걸음 수로 보폭 계산 (레거시 호환성)
    
    이제 통합 계산기를 사용하며, 단순 계산은 응급 대안으로만 사용됩니다.
    
    Args:
        distance_meters: 측정된 거리 (미터)
        step_count: 걸음 수
        
    Returns:
        계산 결과 딕셔너리 (레거시 호환성)
    """
    # 통합 계산기 사용
    calculator = get_unified_step_calculator()
    
    # 입력 데이터 준비
    input_data = StepCalculationInput(
        distance_meters=distance_meters,
        step_count=step_count,
        preferred_method=StepMeasurementMethod.DISTANCE_BASED,
        force_fallback=True  # 레거시 호출은 단순 계산 강제
    )
    
    # 계산 실행
    result = calculator.calculate_step_length(input_data)
    
    # 레거시 딕셔너리 형식으로 변환
    return StepModelConverter.to_legacy_response_dict(result)

def evaluate_measurement_accuracy(distance_meters: float, step_count: int, step_length_cm: float) -> str:
    """
    측정 정확도 평가
    
    Args:
        distance_meters: 측정 거리
        step_count: 걸음 수
        step_length_cm: 계산된 보폭
        
    Returns:
        정확도 수준 ("높음", "보통", "낮음")
    """
    # 1. 거리 기준 평가 (더 긴 거리일수록 정확함)
    distance_score = min(distance_meters / 5.0, 1.0)  # 5미터 기준으로 정규화
    
    # 2. 걸음 수 기준 평가 (더 많은 걸음일수록 정확함)
    step_score = min(step_count / 30.0, 1.0)  # 30걸음 기준으로 정규화
    
    # 3. 보폭 합리성 평가 (일반적인 보폭 범위: 50-90cm)
    if 50 <= step_length_cm <= 90:
        step_length_score = 1.0
    elif 40 <= step_length_cm <= 100:
        step_length_score = 0.7
    else:
        step_length_score = 0.3
    
    # 종합 점수 계산
    total_score = (distance_score * 0.4 + step_score * 0.3 + step_length_score * 0.3)
    
    if total_score >= 0.8:
        return "높음"
    elif total_score >= 0.6:
        return "보통"
    else:
        return "낮음"

@router.post("/measurements", response_model=StepMeasurementResponse)
async def create_footstep_measurement(request: StepMeasurementRequest):
    """
    FastDepth 기반 보폭 측정
    
    Args:
        request: 거리와 걸음 수 정보
        
    Returns:
        FootstepDepthMeasurementResponse: 측정 결과
    """
    try:
        print(f"[FastDepth 보폭 측정] 시작")
        print(f"  - 측정 거리: {request.distance_meters}m")
        print(f"  - 걸음 수: {request.step_count}걸음")
        
        # 고급 통합 보폭 계산 사용
        calculator = get_unified_step_calculator()
        
        # 입력 데이터 준비 (고급 방법 우선 시도)
        input_data = StepCalculationInput(
            distance_meters=request.distance_meters,
            step_count=request.step_count,
            preferred_method=request.measurement_method,
            force_fallback=False  # 고급 방법 우선 시도
        )
        
        # 통합 계산 실행
        step_result = calculator.calculate_step_length(input_data)
        
        # CommandExecutor에 보폭 등록
        previous_step_length = command_executor.user_settings.get("step_length")
        command_executor.user_settings["step_length"] = step_result.step_length_cm
        
        # 로그 출력
        print(f"[FastDepth 보폭 측정] 완료")
        print(f"  - 계산된 보폭: {step_result.step_length_cm}cm")
        print(f"  - 정확도: {step_result.accuracy_level.value}")
        print(f"  - 품질: {step_result.tracking_quality.value}")
        print(f"  - 이전 보폭: {previous_step_length}cm → 새 보폭: {step_result.step_length_cm}cm")
        
        # 정확도에 따른 메시지 생성
        accuracy_msg = ""
        if step_result.accuracy_level.value == "높음":
            accuracy_msg = " (높은 정확도로 측정됨)"
        elif step_result.accuracy_level.value == "낮음":
            accuracy_msg = " (더 긴 거리에서 재측정을 권장함)"
        
        # 입력 데이터 준비
        input_data = {
            "distance_meters": request.distance_meters,
            "step_count": request.step_count,
            "measurement_method": request.measurement_method.value,
            "user_id": request.user_id
        }
        
        return StepMeasurementResponse(
            success=True,
            message=f"보폭 측정이 완료되었습니다! 계산된 보폭은 {step_result.step_length_cm}cm입니다.{accuracy_msg}",
            result=step_result,
            input_data=input_data,
            processing_info={
                "method": "distance_based_calculation",
                "previous_step_length": previous_step_length,
                "updated_user_settings": True
            }
        )
        
    except Exception as e:
        print(f"[오류] FastDepth 보폭 측정 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"측정 실패: {str(e)}")

@router.get("/", tags=["Footstep Settings"])
async def get_footstep_settings():
    """
    현재 설정된 보폭 길이 조회
    
    Returns:
        현재 보폭 정보
    """
    try:
        # command_executor는 이미 모듈 레벨에서 초기화됨
        current_settings = command_executor.user_settings
        
        step_length = current_settings.get("step_length")
        user_name = current_settings.get("user_name", "사용자")
        
        if step_length is None:
            return {
                "step_length": None,
                "message": "아직 보폭이 설정되지 않았습니다.",
                "user_name": user_name,
                "is_set": False
            }
        
        return {
            "step_length": step_length,
            "message": f"{user_name}님의 현재 보폭은 {step_length}cm입니다.",
            "user_name": user_name,
            "is_set": True,
            "unit": "cm"
        }
        
    except Exception as e:
        print(f"[오류] 현재 보폭 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"보폭 조회 실패: {str(e)}")

@router.put("/", response_model=Dict[str, Any], tags=["Footstep Settings"])
async def update_footstep_settings(request: StepUpdateRequest):
    """
    보폭 수동 업데이트 (설정에서 재설정용)
    
    Args:
        request: 새로운 보폭 길이
        
    Returns:
        업데이트 결과
    """
    try:
        # command_executor는 이미 모듈 레벨에서 초기화됨
        previous_step_length = command_executor.user_settings.get("step_length")
        
        # 새로운 보폭 설정
        command_executor.user_settings["step_length"] = request.step_length_cm
        
        print(f"[보폭 업데이트] {previous_step_length}cm → {request.step_length_cm}cm")
        
        return {
            "success": True,
            "message": f"보폭이 {request.step_length_cm}cm로 업데이트되었습니다.",
            "previous_step_length": previous_step_length,
            "new_step_length": request.step_length_cm,
            "updated_at": datetime.now().isoformat(),
            "update_reason": request.update_reason
        }
        
    except Exception as e:
        print(f"[오류] 보폭 업데이트 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"보폭 업데이트 실패: {str(e)}")

@router.post("/measurements/validate", tags=["Footstep Validation"])
async def validate_measurement_request(distance_meters: float, step_count: int):
    """
    측정 전 데이터 유효성 검증
    
    Args:
        distance_meters: 측정할 거리
        step_count: 예상 걸음 수
        
    Returns:
        검증 결과 및 권장사항
    """
    try:
        warnings = []
        recommendations = []
        
        # 거리 검증
        if distance_meters < 2.0:
            warnings.append("측정 거리가 짧습니다 (2m 미만)")
            recommendations.append("더 긴 거리에서 측정하면 정확도가 향상됩니다")
        
        if distance_meters > 20.0:
            warnings.append("측정 거리가 매우 깁니다")
            recommendations.append("FastDepth 정확도를 확인해주세요")
        
        # 걸음 수 검증
        if step_count < 10:
            warnings.append("걸음 수가 적습니다")
            recommendations.append("더 많은 걸음으로 측정하면 정확도가 향상됩니다")
        
        # 예상 보폭 계산 및 검증 - UnifiedStepCalculator 사용
        calculator = get_unified_step_calculator()
        input_data = StepCalculationInput(
            distance_meters=distance_meters,
            step_count=step_count,
            preferred_method=StepMeasurementMethod.DISTANCE_BASED,
            force_fallback=True  # 검증용 계산이므로 단순 계산 사용
        )
        result = calculator.calculate_step_length(input_data)
        expected_step_length = result.step_length_cm
        
        if expected_step_length < 30:
            warnings.append("계산될 보폭이 너무 짧습니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
        elif expected_step_length > 120:
            warnings.append("계산될 보폭이 너무 깁니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
        
        # 통합 검증 시스템 사용
        validation_result = validate_step_measurement_inputs(
            distance_meters=distance_meters,
            step_count=step_count,
            method=StepMeasurementMethod.DISTANCE_BASED
        )
        
        # 레거시 형식으로 변환 (API 호환성)
        return {
            "valid": validation_result.is_valid,
            "expected_step_length": validation_result.expected_step_length_cm,
            "warnings": validation_result.warnings,
            "recommendations": validation_result.recommendations,
            "accuracy_prediction": validation_result.predicted_accuracy.value if validation_result.predicted_accuracy else "보통",
            "overall_score": validation_result.overall_score,
            "detailed_validation": {
                "distance": validation_result.distance_validation,
                "step_count": validation_result.step_count_validation,
                "step_length": validation_result.step_length_validation
            }
        }
        
    except Exception as e:
        print(f"[오류] 데이터 검증 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"검증 실패: {str(e)}")