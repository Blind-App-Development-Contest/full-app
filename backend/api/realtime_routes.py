"""실시간 FastDepth 프레임 처리 전용 라우터"""

from fastapi import APIRouter, HTTPException
import logging
import time

from models.fastdepth_models import (
    FrameProcessRequest, FrameProcessResponse
)
from models.common_models import (
    RealTimeMeasurementStatus
)
from services.singleton import service_manager
# 카메라 스트림 통합을 위한 추가 임포트
from utils.fastdepth_processor import get_fastdepth_processor

logger = logging.getLogger(__name__)
router = APIRouter()

# 싱글톤 CommandExecutor 사용
command_executor = service_manager.get_command_executor()

@router.post("/frame", response_model=FrameProcessResponse)
async def process_frame(request: FrameProcessRequest):
    """
    POST /frame: FastDepth 프레임 처리
    
    CommandExecutor의 통합 step measurement 시스템을 사용하여
    단일 FastDepth 프레임을 처리합니다.
    """
    try:
        logger.info(f"프레임 처리 요청 - 사용자: {request.user_id}")
        
        # 측정이 활성화되어 있는지 확인
        if not command_executor.is_measurement_active():
            return FrameProcessResponse(
                success=False,
                message="보폭 측정이 비활성화되어 있습니다. 먼저 측정을 시작해주세요.",
                measurement_active=False,
                current_result=None
            )
        
        # 새로운 IMU 통합 시스템 사용
        fastdepth_processor = get_fastdepth_processor()
        
        # 더미 이미지 생성 (실제로는 클라이언트에서 이미지를 함께 보내야 함)
        import numpy as np
        dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # 기본 IMU 데이터
        default_imu_data = {
            'accelerometer': [0, 0, 9.81],
            'gyroscope': [0, 0, 0],
            'timestamp': time.time(),
            'device_orientation': 'portrait'
        }
        
        # 새로운 시스템으로 처리
        result = await fastdepth_processor.process_frame_for_measurement(
            cv_image=dummy_image,
            user_id=request.user_id or "realtime_user",
            imu_data=default_imu_data,
            enable_advanced_fusion=False
        )
        
        if result:
            logger.debug(f"프레임 처리 성공 - 보폭: {result.step_length_cm}cm, 걸음수: {result.step_count}")
            
            # StepCalculationResult를 딕셔너리로 변환
            current_result = {
                "step_length_cm": result.step_length_cm,
                "confidence": result.confidence,
                "tracking_quality": result.tracking_quality.value,
                "accuracy_level": result.accuracy_level.value,
                "measurement_method": result.measurement_method.value
            }
            
            return FrameProcessResponse(
                success=True,
                message=f"프레임 처리 완료 - 현재 보폭: {result.step_length_cm}cm",
                measurement_active=True,
                current_result=current_result
            )
        else:
            # 프레임 처리는 성공했지만 아직 유의미한 결과가 없음
            return FrameProcessResponse(
                success=True,
                message="프레임 처리 완료 - 측정 계속 진행중",
                measurement_active=True,
                current_result=None
            )
            
    except Exception as e:
        logger.error(f"프레임 처리 오류: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"프레임 처리 중 오류가 발생했습니다: {str(e)}"
        )

@router.get("/measurement/status", response_model=RealTimeMeasurementStatus)
async def get_measurement_status():
    """
    GET /measurement/status: 현재 실시간 측정 상태 반환
    
    CommandExecutor의 단일 상태 관리 시스템에서
    현재 보폭 측정 상태를 조회합니다.
    """
    try:
        logger.debug("측정 상태 조회 요청")
        
        # CommandExecutor의 통합 상태 조회 메서드 사용
        status = command_executor.get_step_measurement_status()
        
        logger.debug(f"측정 상태: active={status.measurement_active}, status={status.measurement_status}")
        
        return status
        
    except Exception as e:
        logger.error(f"측정 상태 조회 오류: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"측정 상태 조회 중 오류가 발생했습니다: {str(e)}"
        )

