from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from uuid import UUID
from typing import Dict, Any
from datetime import datetime
import numpy as np
import tempfile
# 기존 데이터베이스 연결 설정 제거하고 중앙화된 것 사용
from core.database import get_async_db
from models.database_models import User, Footstep
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# 통합 스텝 모델 import
from models.step_models import (
    StepMeasurementRequest,
    StepMeasurementResponse,
    StepUpdateRequest,
    StepMeasurementMethod,
    validate_step_measurement_inputs,
    StepCalculationUtils
)

# 레거시 호환성을 위한 모델들
class FootstepUpdateRequest(BaseModel):
    user_id: UUID
    step_length_cm: int

class FootstepResponse(BaseModel):
    user_id: UUID
    step_length_cm: int
    updated_at: datetime

# 새로운 IMU 통합 시스템 import (레거시 호환성 유지)
from utils.fastdepth_processor import get_fastdepth_processor
from middleware.error_handler import ErrorLogger

router = APIRouter()

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager
command_executor = service_manager.get_command_executor()
speech_service = service_manager.get_speech_service()
speech_analyzer = service_manager.get_speech_analyzer()

# 레거시 함수들은 UnifiedStepCalculator와 StepValidationResult로 대체됨

@router.post("/measurements/files", response_model=StepMeasurementResponse)
async def measurement_from_files(
    voice_file: UploadFile = File(..., description="걸음수 추출용 음성 파일"),
    frame_file: UploadFile = File(..., description="거리 측정용 프레임 이미지"),
    user_id: str = Form(default="api_user")
):
    """
    파일 업로드 방식 통합형 보폭 측정
    
    Args:
        voice_file: 걸음수 추출용 음성 파일
        frame_file: 거리 측정용 프레임 이미지  
        user_id: 사용자 ID
        
    Returns:
        StepMeasurementResponse: 측정 결과
    """
    try:
        print(f"[파일 업로드 보폭 측정] 시작 - 사용자: {user_id}")
        
        # 1단계: 음성에서 걸음수 추출
        step_count = await _extract_step_count_from_voice(voice_file)
        
        # 2단계: 프레임에서 거리 측정
        cv_image = await _convert_upload_to_cv_image(frame_file)
        measured_distance_meters = await _measure_distance_from_frame(cv_image)
        
        # 3단계: 통합 보폭 계산
        return await _calculate_unified_step_measurement(
            step_count=step_count,
            distance_meters=measured_distance_meters,
            user_id=user_id,
            method="file_upload_integration"
        )
        
    except Exception as e:
        ErrorLogger.log_api_error("Footstep", "파일 업로드 보폭 측정", e)
        raise HTTPException(status_code=500, detail=f"파일 업로드 측정 실패: {str(e)}")

async def _extract_step_count_from_voice(voice_file: UploadFile) -> int:
    """음성 파일에서 걸음수 추출"""
    try:
        # 음성을 텍스트로 변환
        transcribed_text = await speech_service.transcribe_from_uploadfile(voice_file)
        print(f"[음성인식] 변환된 텍스트: '{transcribed_text}'")
        
        # 텍스트에서 의도 분석
        speech_result = speech_analyzer.analyze_command(
            transcribed_text, 
            context="awaiting_step_count"
        )
        
        # 걸음수 추출
        if speech_result.intent == "STEP_COUNT_RESPONSE":
            if "step_count" in speech_result.entities:
                step_count = speech_result.entities["step_count"]
                print(f"[음성분석] 걸음수 추출 성공: {step_count}걸음")
                return int(step_count)
        
        # 직접 숫자 추출 시도
        import re
        numbers = re.findall(r'\d+', transcribed_text)
        if numbers:
            # 첫 번째 숫자를 걸음수로 사용
            step_count = int(numbers[0])
            print(f"[음성분석] 직접 숫자 추출: {step_count}걸음")
            return step_count
        
        raise ValueError("음성에서 걸음수를 찾을 수 없습니다")
        
    except Exception as e:
        print(f"[음성처리 오류] {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"음성에서 걸음수 추출 실패: {str(e)}"
        )

async def _convert_upload_to_cv_image(image_file: UploadFile) -> np.ndarray:
    """UploadFile을 OpenCV 이미지로 변환"""
    try:
        # 파일 내용 읽기
        image_bytes = await image_file.read()
        
        # NumPy 배열로 변환
        nparr = np.frombuffer(image_bytes, np.uint8)
        
        # OpenCV 이미지로 디코드
        import cv2
        cv_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if cv_image is None:
            raise ValueError("이미지 파일을 디코드할 수 없습니다")
        
        print(f"[이미지처리] 변환 완료: {cv_image.shape}")
        return cv_image
        
    except Exception as e:
        print(f"[이미지처리 오류] {e}")
        raise HTTPException(
            status_code=400,
            detail=f"이미지 파일 처리 실패: {str(e)}"
        )

async def _measure_distance_from_frame(cv_image: np.ndarray) -> float:
    """프레임에서 거리 측정 (공통 유틸리티)"""
    try:
        processor = get_fastdepth_processor()
        distance_meters = processor._analyze_frame_for_distance(cv_image)
        print(f"[거리 측정] {distance_meters:.2f}m")
        return distance_meters
    except Exception as e:
        print(f"[거리 측정 오류] {e}")
        raise HTTPException(status_code=500, detail=f"거리 측정 실패: {str(e)}")

async def _calculate_unified_step_measurement(
    step_count: int, 
    distance_meters: float, 
    user_id: str,
    method: str
) -> StepMeasurementResponse:
    """통합 보폭 계산 (공통 유틸리티)"""
    try:
        from models.step_models import StepCalculationResult, AccuracyConverter
        
        # 보폭 계산
        step_length_cm = StepCalculationUtils.calculate_step_length_cm(distance_meters, step_count)
        confidence = StepCalculationUtils.get_confidence_from_distance(distance_meters)
        
        step_result = StepCalculationResult(
            step_length_cm=round(step_length_cm, 1),
            confidence=confidence,
            step_count=step_count,
            tracking_quality=AccuracyConverter.confidence_to_quality(confidence),
            accuracy_level=AccuracyConverter.confidence_to_korean_level(confidence),
            measurement_method=StepMeasurementMethod.DISTANCE_BASED,
            consistency_score=None,
            processing_time_ms=None,
            timestamp=datetime.now(),
            source_data={
                "method": method,
                "step_count": step_count,
                "distance_meters": distance_meters,
                "distance_source": "midas_frame_analysis",
                "step_count_source": "whisper_voice_recognition"
            }
        )
        
        # 설정 업데이트
        previous_step_length = command_executor.user_settings.get("step_length")
        command_executor.user_settings["step_length"] = step_result.step_length_cm
        
        # 로그 출력
        print(f"[통합 보폭 계산] 완료")
        print(f"  - 걸음수: {step_count}걸음")
        print(f"  - 거리: {distance_meters:.2f}m") 
        print(f"  - 보폭: {step_result.step_length_cm}cm")
        
        # 정확도 메시지
        accuracy_msg = ""
        if step_result.accuracy_level.value == "높음":
            accuracy_msg = " (높은 정확도로 측정됨)"
        elif step_result.accuracy_level.value == "낮음":
            accuracy_msg = " (더 긴 거리나 더 많은 걸음으로 재측정을 권장함)"
        
        return StepMeasurementResponse(
            success=True,
            message=command_executor.get_voice_message("step_measurement_complete", step_length=step_result.step_length_cm),
            result=step_result,
            input_data={
                "step_count": step_count,
                "distance_meters": distance_meters,
                "method": method,
                "user_id": user_id
            },
            processing_info={
                "method": method,
                "voice_processing": "whisper_stt",
                "frame_processing": "midas_depth_estimation", 
                "previous_step_length": previous_step_length,
                "updated_user_settings": True
            },
            validation=None
        )
        
    except Exception as e:
        print(f"[보폭 계산 오류] {e}")
        raise HTTPException(status_code=500, detail=f"보폭 계산 실패: {str(e)}")

@router.post("/measurements", response_model=StepMeasurementResponse)
async def create_footstep_measurement(request: StepMeasurementRequest):
    """
    통합형 보폭 측정 (음성 or 직접입력 걸음수 + 프레임 거리 측정)
    
    Args:
        request: 음성/프레임 데이터 또는 직접 입력 데이터
        
    Returns:
        StepMeasurementResponse: 측정 결과
    """
    try:
        print(f"[통합 보폭 측정] 시작")
        
        step_count = None
        measured_distance_meters = None
        
        # 1단계: 걸음수 확보 (음성 우선, 직접입력 백업)
        if hasattr(request, 'voice_data') and request.voice_data is not None:
            print("[음성 처리] 음성에서 걸음수 추출")
            try:
                # 음성 데이터를 임시 파일로 저장하여 처리
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_file.write(request.voice_data)
                    temp_file.flush()
                    
                    # UploadFile 객체로 변환
                    from fastapi import UploadFile
                    temp_upload = UploadFile(filename="temp_voice.wav", file=open(temp_file.name, "rb"))
                    step_count = await _extract_step_count_from_voice(temp_upload)
                    temp_upload.file.close()
                    
                print(f"  - 음성에서 추출된 걸음수: {step_count}걸음")
            except Exception as e:
                print(f"[음성 처리 실패] {e}")
                if request.step_count is not None:
                    step_count = request.step_count
                    print(f"  - 백업 직접입력 사용: {step_count}걸음")
                else:
                    raise HTTPException(status_code=400, detail="음성 처리 실패, 걸음수 직접입력이 필요합니다")
        elif request.step_count is not None:
            step_count = request.step_count
            print(f"  - 직접 입력된 걸음수: {step_count}걸음")
        else:
            raise HTTPException(status_code=400, detail="걸음수는 음성 또는 직접 입력으로 제공해야 합니다")
        
        # 2단계: 거리 측정 (프레임 필수)
        if not hasattr(request, 'frame_data') or request.frame_data is None:
            raise HTTPException(status_code=400, detail="프레임 데이터가 필요합니다 (거리 측정용)")
        
        # 2단계: 프레임에서 거리 측정
        measured_distance_meters = await _measure_distance_from_frame(request.frame_data)
        
        # 3단계: 통합 보폭 계산
        return await _calculate_unified_step_measurement(
            step_count=step_count,
            distance_meters=measured_distance_meters,
            user_id=getattr(request, 'user_id', 'api_user'),
            method="integrated_voice_frame_data"
        )
        
    except Exception as e:
        ErrorLogger.log_api_error("Footstep", "FastDepth 보폭 측정", e)
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
        
        # user_settings 테이블도 자동 업데이트
        from sqlalchemy import text
        await session.execute(
            text("""
                INSERT INTO user_settings (user_id, step_id)
                VALUES (:user_id, :step_id)
                ON CONFLICT (user_id) DO UPDATE SET
                    step_id = EXCLUDED.step_id,
                    setting_updated_at = NOW()
            """),
            {"user_id": request.user_id, "step_id": footstep.step_id}
        )
        await session.commit()
        
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

@router.get("", tags=["Footstep Management"])
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
        ErrorLogger.log_api_error("Footstep", "현재 보폭 조회", e)
        raise HTTPException(status_code=500, detail=f"보폭 조회 실패: {str(e)}")

@router.put("", response_model=Dict[str, Any], tags=["Footstep Management"])
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
        ErrorLogger.log_api_error("Footstep", "보폭 업데이트", e)
        raise HTTPException(status_code=500, detail=f"보폭 업데이트 실패: {str(e)}")

@router.post("/measurements/validate", tags=["Footstep Management"])
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
        
        # 중앙화된 보폭 계산 사용
        expected_step_length = StepCalculationUtils.calculate_step_length_cm(distance_meters, step_count)
        
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
        ErrorLogger.log_api_error("Footstep", "데이터 검증", e)
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