"""실시간 FastDepth 프레임 처리 전용 라우터"""

from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any
import logging
import time
import base64
import cv2
import numpy as np

from models.fastdepth_models import (
    FastDepthFrameData, FrameProcessRequest, FrameProcessResponse
)
from models.common_models import (
    RealTimeMeasurementStatus, SchemaConverter
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
                measurement_active=False
            )
        
        # FastDepthFrame을 딕셔너리로 변환
        frame_dict = SchemaConverter.fastdepth_frame_to_dict(request.frame)
        
        # CommandExecutor의 통합 프레임 처리 메서드 사용
        result = command_executor.process_step_frame(frame_dict)
        
        # 현재 측정 상태 가져오기
        measurement_status = command_executor.get_step_measurement_status()
        
        if result:
            logger.debug(f"프레임 처리 성공 - 보폭: {result.step_length_cm}cm, 걸음수: {result.step_count}")
            
            return FrameProcessResponse(
                success=True,
                message=f"프레임 처리 완료 - 현재 보폭: {result.step_length_cm}cm",
                measurement_active=True,
                current_result=result
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

