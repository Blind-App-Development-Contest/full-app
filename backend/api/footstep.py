from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from uuid import UUID
from typing import Dict, Any
from datetime import datetime
import time
# 기존 데이터베이스 연결 설정 제거하고 중앙화된 것 사용
from core.database import get_async_db
from models.database_models import User, Footstep
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# 통합 스텝 모델 import - 중복 제거됨
from models.step_models import (
    StepMeasurementRequest,
    StepMeasurementResponse,
    StepUpdateRequest,
    StepMeasurementMethod,
    validate_step_measurement_inputs
)

# 레거시 호환성을 위한 모델들 (새 코드는 step_models 사용 권장)
class FootstepUpdateRequest(BaseModel):
    user_id: UUID
    step_length_cm: int

class FootstepResponse(BaseModel):
    user_id: UUID
    step_length_cm: int
    updated_at: datetime

# 새로운 IMU 통합 시스템 import (레거시 호환성 유지)
from utils.fastdepth_processor import get_fastdepth_processor

router = APIRouter()

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager
command_executor = service_manager.get_command_executor()

# 레거시 함수들은 UnifiedStepCalculator와 StepValidationResult로 대체됨

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
        
# 새로운 IMU 통합 시스템을 사용한 보폭 계산
        processor = get_fastdepth_processor()
        
        # 거리 기반 계산을 위해 간단한 더미 이미지 생성
        import numpy as np
        dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # 기본 IMU 데이터 (센서가 없을 때의 기본값)
        default_imu_data = {
            'accelerometer': [0, 0, 9.81],
            'gyroscope': [0, 0, 0],
            'timestamp': time.time(),
            'device_orientation': 'portrait'
        }
        
        # 새로운 통합 시스템으로 계산 (레거시 API 호환)
        step_result = await processor.process_frame_for_measurement(
            cv_image=dummy_image,
            user_id=str(request.user_id) if getattr(request, 'user_id', None) else 'api_user',
            imu_data=default_imu_data,
            enable_advanced_fusion=False  # API 호출에서는 기본 모드 사용
        )
        
        # 레거시 API 호환을 위해 결과가 없으면 거리 기반 단순 계산
        if not step_result:
            from models.step_models import StepCalculationResult, AccuracyConverter
            # 거리 기반 단순 계산 (None 체크)
            if request.distance_meters is None or request.step_count is None or request.step_count == 0:
                raise HTTPException(status_code=400, detail="거리와 걸음 수는 필수입니다.")
            step_length_cm = (request.distance_meters / request.step_count) * 100
            confidence = 0.7 if request.distance_meters >= 3.0 else 0.5
            
            step_result = StepCalculationResult(
                step_length_cm=round(step_length_cm, 1),
                confidence=confidence,
                step_count=request.step_count,
                tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
                measurement_method=request.measurement_method,
                consistency_score=None,
                processing_time_ms=None,
                timestamp=datetime.now(),
                source_data={
                    "method": "distance_based_api_fallback",
                    "distance_meters": request.distance_meters,
                    "step_count": request.step_count
                }
            )
        
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
            },
            validation=None
        )
        
    except Exception as e:
        print(f"[오류] FastDepth 보폭 측정 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"측정 실패: {str(e)}")

# =========================
# DB 연동 엔드포인트
# =========================

@router.post("/update", response_model=FootstepResponse)
async def update_footstep(
    request: FootstepUpdateRequest,
    session: AsyncSession = Depends(get_async_db)
):
    """사용자 보폭 길이 업데이트 (ORM 방식으로 UPSERT)"""
    try:
        # 사용자 존재 확인
        user_result = await session.execute(
            select(User).where(User.user_id == request.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        # 기존 보폭 정보 확인
        footstep_result = await session.execute(
            select(Footstep).where(Footstep.user_id == request.user_id)
        )
        existing_footstep = footstep_result.scalar_one_or_none()
        
        if existing_footstep:
            # 실제 값 할당
            setattr(existing_footstep, "step_length", request.step_length_cm)
            await session.commit()
            await session.refresh(existing_footstep)
            footstep = existing_footstep
        else:
            # 새로운 데이터 생성
            footstep = Footstep(
                user_id=request.user_id,
                step_length=request.step_length_cm
            )
            session.add(footstep)
            await session.commit()
            await session.refresh(footstep)
        
        return FootstepResponse(
            user_id=getattr(footstep, "user_id"),
            step_length_cm=getattr(footstep, "step_length"),
            updated_at=getattr(footstep, "step_updated_at")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"보폭 업데이트 오류: {str(e)}")

@router.get("/user/{user_id}", response_model=FootstepResponse)
async def get_user_footstep(
    user_id: UUID,
    session: AsyncSession = Depends(get_async_db)
):
    """사용자별 보폭 길이 조회 (ORM 방식)"""
    try:
        # ORM으로 보폭 정보 조회 (사용자 정보도 함께 로딩)
        result = await session.execute(
            select(Footstep)
            .options(selectinload(Footstep.user))
            .where(Footstep.user_id == user_id)
        )
        footstep = result.scalar_one_or_none()
        
        if not footstep:
            raise HTTPException(status_code=404, detail="사용자 보폭 정보를 찾을 수 없습니다")
        
        return FootstepResponse(
            user_id=getattr(footstep, "user_id"),
            step_length_cm=getattr(footstep, "step_length"),
            updated_at=getattr(footstep, "step_updated_at")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"보폭 조회 오류: {str(e)}")

@router.get("", tags=["Footstep Settings"])
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
        
        # 간단한 보폭 계산 (검증용)
        expected_step_length = (distance_meters / step_count) * 100
        
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

@router.delete("/user/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_footstep(
    user_id: UUID,
    session: AsyncSession = Depends(get_async_db)
):
    """
    사용자별 보폭 정보 삭제 (ORM 방식)
    """
    try:
        result = await session.execute(
            select(Footstep).where(Footstep.user_id == user_id)
        )
        footstep = result.scalar_one_or_none()
        if not footstep:
            raise HTTPException(status_code=404, detail="삭제할 보폭 정보가 없습니다")
        await session.delete(footstep)
        await session.commit()
        return  # 204 No Content
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"보폭 삭제 오류: {str(e)}")