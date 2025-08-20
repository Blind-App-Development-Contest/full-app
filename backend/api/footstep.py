from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

router = APIRouter()

# Pydantic 모델들
class FootstepDepthMeasurementRequest(BaseModel):
    """FastDepth 기반 보폭 측정 요청 모델"""
    distance_meters: float = Field(
        ...,
        description="FastDepth로 측정된 거리 (미터)",
        gt=0.5,  # 최소 0.5미터
        le=50.0,  # 최대 50미터
        example=3.0
    )
    step_count: int = Field(
        ...,
        description="걸음 수",
        gt=0,
        le=500,
        example=45
    )
    user_id: Optional[str] = Field(None, description="사용자 ID")

class FootstepDepthMeasurementResponse(BaseModel):
    """FastDepth 기반 보폭 측정 응답 모델"""
    success: bool = Field(description="측정 성공 여부")
    message: str = Field(description="응답 메시지")
    step_length_cm: float = Field(description="계산된 보폭 길이 (cm)")
    distance_meters: float = Field(description="측정된 거리 (미터)")
    distance_cm: float = Field(description="측정된 거리 (cm)")
    step_count: int = Field(description="걸음 수")
    accuracy_level: str = Field(description="측정 정확도 수준")

class FootstepUpdateRequest(BaseModel):
    """보폭 업데이트 요청 모델"""
    step_length: float = Field(
        ...,
        description="새로운 보폭 길이 (cm)",
        gt=30,
        lt=150,
        example=65.5
    )

# 전역 변수로 CommandExecutor 싱글톤 관리
_command_executor = None

def get_command_executor():
    """CommandExecutor 싱글톤 인스턴스 반환"""
    global _command_executor
    if _command_executor is None:
        from services.command_executor import CommandExecutor
        _command_executor = CommandExecutor()
    return _command_executor

def calculate_step_length_from_distance(distance_meters: float, step_count: int) -> dict:
    """
    거리와 걸음 수로 보폭 계산
    
    Args:
        distance_meters: FastDepth로 측정된 거리 (미터)
        step_count: 걸음 수
        
    Returns:
        계산 결과 딕셔너리
    """
    # 미터를 센티미터로 변환
    distance_cm = distance_meters * 100
    
    # 보폭 계산: 총 거리 ÷ 걸음 수
    step_length_cm = distance_cm / step_count
    
    # 정확도 수준 평가
    accuracy_level = evaluate_measurement_accuracy(distance_meters, step_count, step_length_cm)
    
    return {
        "step_length_cm": round(step_length_cm, 1),  # 소수점 첫째 자리까지
        "distance_meters": distance_meters,
        "distance_cm": distance_cm,
        "step_count": step_count,
        "accuracy_level": accuracy_level
    }

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

@router.post("/measurement/depth", response_model=FootstepDepthMeasurementResponse)
async def measure_footstep_with_depth(request: FootstepDepthMeasurementRequest):
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
        
        # 보폭 계산
        calculation_result = calculate_step_length_from_distance(
            request.distance_meters, 
            request.step_count
        )
        
        # CommandExecutor에 보폭 등록
        command_executor = get_command_executor()
        previous_step_length = command_executor.user_settings.get("step_length")
        command_executor.user_settings["step_length"] = calculation_result["step_length_cm"]
        
        # 로그 출력
        print(f"[FastDepth 보폭 측정] 완료")
        print(f"  - 계산된 보폭: {calculation_result['step_length_cm']}cm")
        print(f"  - 정확도: {calculation_result['accuracy_level']}")
        print(f"  - 이전 보폭: {previous_step_length}cm → 새 보폭: {calculation_result['step_length_cm']}cm")
        
        # 정확도에 따른 메시지 생성
        accuracy_msg = ""
        if calculation_result["accuracy_level"] == "높음":
            accuracy_msg = " (높은 정확도로 측정됨)"
        elif calculation_result["accuracy_level"] == "낮음":
            accuracy_msg = " (더 긴 거리에서 재측정을 권장함)"
        
        return FootstepDepthMeasurementResponse(
            success=True,
            message=f"보폭 측정이 완료되었습니다! 계산된 보폭은 {calculation_result['step_length_cm']}cm입니다.{accuracy_msg}",
            step_length_cm=calculation_result["step_length_cm"],
            distance_meters=calculation_result["distance_meters"],
            distance_cm=calculation_result["distance_cm"],
            step_count=calculation_result["step_count"],
            accuracy_level=calculation_result["accuracy_level"]
        )
        
    except Exception as e:
        print(f"[오류] FastDepth 보폭 측정 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"측정 실패: {str(e)}")

@router.get("/current")
async def get_current_footstep():
    """
    현재 설정된 보폭 길이 조회
    
    Returns:
        현재 보폭 정보
    """
    try:
        command_executor = get_command_executor()
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

@router.put("/update", response_model=Dict[str, Any])
async def update_footstep(request: FootstepUpdateRequest):
    """
    보폭 수동 업데이트 (설정에서 재설정용)
    
    Args:
        request: 새로운 보폭 길이
        
    Returns:
        업데이트 결과
    """
    try:
        command_executor = get_command_executor()
        previous_step_length = command_executor.user_settings.get("step_length")
        
        # 새로운 보폭 설정
        command_executor.user_settings["step_length"] = request.step_length
        
        print(f"[보폭 업데이트] {previous_step_length}cm → {request.step_length}cm")
        
        return {
            "success": True,
            "message": f"보폭이 {request.step_length}cm로 업데이트되었습니다.",
            "previous_step_length": previous_step_length,
            "new_step_length": request.step_length,
            "updated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"[오류] 보폭 업데이트 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"보폭 업데이트 실패: {str(e)}")

@router.post("/validate-measurement")
async def validate_measurement_data(distance_meters: float, step_count: int):
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
        
        # 예상 보폭 계산 및 검증
        expected_step_length = (distance_meters * 100) / step_count
        
        if expected_step_length < 30:
            warnings.append("계산될 보폭이 너무 짧습니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
        elif expected_step_length > 120:
            warnings.append("계산될 보폭이 너무 깁니다")
            recommendations.append("거리 측정값이나 걸음 수를 확인해주세요")
        
        validation_result = {
            "valid": len(warnings) == 0,
            "expected_step_length": round(expected_step_length, 1),
            "warnings": warnings,
            "recommendations": recommendations,
            "accuracy_prediction": evaluate_measurement_accuracy(distance_meters, step_count, expected_step_length)
        }
        
        return validation_result
        
    except Exception as e:
        print(f"[오류] 데이터 검증 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"검증 실패: {str(e)}")