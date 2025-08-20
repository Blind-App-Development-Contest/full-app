"""측정 관련 라우터 - FastDepth 프레임 처리 및 보폭 측정"""

from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any
import time
import asyncio
import logging

from models.fastdepth_models import (
    FastDepthFootData,
    FastDepthFrameData,
    EnhancedCommandRequest
)
from models.common_models import (
    MeasurementStatusResponse,
    SystemStatusResponse,
    MeasurementProgress,
    AppMode,
    UserSettings
)
from models.execution_schemas import (
    FullCommandRequest,
    FullCommandResponse,
    CommandExecutionResponse
)
from services.command_executor import CommandExecutionResult
from api.speech_helpers import (
    get_current_context,
    process_fastdepth_frame,
    process_speech_command_with_context,
    build_enhanced_response,
    get_available_commands_for_context
)
from utils.fastdepth_processor import get_fastdepth_processor

logger = logging.getLogger(__name__)
router = APIRouter()

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager

speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()

@router.post("/commands/enhanced", response_model=FullCommandResponse)
async def execute_enhanced_speech_commands(request: EnhancedCommandRequest):
    """
    음성 명령 + FastDepth 프레임 통합 처리
    """
    try:
        print(f"\n[향상된 명령] 시작: '{request.command_text}'")
        if request.fastdepth_frame:
            print(f"[FastDepth] 프레임 데이터 포함됨")
        
        # 컨텍스트 결정 (요청에서 제공되지 않은 경우 자동 감지)
        context = request.context or get_current_context()
        print(f"[컨텍스트] 사용 중인 컨텍스트: {context}")
        
        # 병렬 처리를 위한 태스크들
        tasks = []
        
        # 1. FastDepth 프레임 처리 (있는 경우)
        frame_task = None
        if request.fastdepth_frame:
            frame_task = asyncio.create_task(
                process_fastdepth_frame(request.fastdepth_frame)
            )
            tasks.append(frame_task)
        
        # 2. 음성 명령 처리 (있는 경우)
        command_task = None
        if request.command_text and request.command_text.strip():
            command_task = asyncio.create_task(
                process_speech_command_with_context(request, context)
            )
            tasks.append(command_task)
        
        # 병렬 처리 실행
        if not tasks:
            raise HTTPException(400, "command_text 또는 fastdepth_frame 중 하나는 필수입니다")
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 결과 분리
        frame_result = results[0] if frame_task else None
        command_result = results[1] if command_task and len(results) > 1 else results[0] if command_task else None
        
        # 에러 처리
        for result in results:
            if isinstance(result, Exception):
                raise result
        
        # 응답 구성
        response = build_enhanced_response(command_result, frame_result, context)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 향상된 명령 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@router.post("/fastdepth/frame")
async def process_fastdepth_frame_only(frame_data: FastDepthFrameData):
    """
    FastDepth 프레임만 처리 - 통합 프로세서 전용
    """
    try:
        logger.debug("[FastDepth] 통합 프로세서로 프레임 처리 시작")
        
        # 통합 FastDepth 프로세서 사용 (유일한 프레임 처리 방식)
        processor = get_fastdepth_processor()
        processed_frame = processor.convert_frame_to_dict(frame_data)
        
        # CommandExecutor로 이미 변환된 프레임 전달
        result = await command_executor.process_fastdepth_frame(processed_frame.frame_dict)
        
        if result:
            return {
                "success": True,
                "message": result.message,
                "data": result.data,
                "actions": result.actions,
                "measurement_active": command_executor.is_measurement_active(),
                "processing_time_ms": processed_frame.processing_time * 1000,
                "confidence_score": processed_frame.confidence_score
            }
        else:
            return {
                "success": False,
                "message": "측정이 활성화되지 않았습니다.",
                "measurement_active": False
            }
        
    except ValueError as e:
        logger.error(f"FastDepth 프레임 검증 실패: {e}")
        raise HTTPException(status_code=400, detail=f"프레임 데이터 오류: {str(e)}")
    except Exception as e:
        logger.error(f"FastDepth 프레임 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"프레임 처리 오류: {str(e)}")

@router.get("/status", response_model=MeasurementStatusResponse)
async def get_measurement_status():
    """
    현재 보폭 측정 상태 조회 - StatusService 통합
    """
    try:
        from services.status_service import get_status_service
        
        status_service = get_status_service()
        result = status_service.get_measurement_status()
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"측정 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 오류: {str(e)}")

@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status():
    """
    전체 시스템 상태 조회 - StatusService 통합
    """
    try:
        from services.status_service import get_status_service
        
        status_service = get_status_service()
        result = status_service.get_system_status()
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"시스템 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"시스템 상태 조회 오류: {str(e)}")

@router.post("/reset")
async def reset_measurement():
    """
    진행 중인 보폭 측정 리셋 (상태 서비스와 연동)
    """
    try:
        if command_executor.is_measurement_active():
            # 측정 취소 실행
            result = await command_executor._execute_footstep_measurement_cancel({})
            
            # 상태 캐시 무효화 (측정 리셋 후)
            status_service = get_status_service()
            status_service.clear_cache()
            
            return {
                "success": True,
                "message": "측정이 리셋되었습니다.",
                "previous_status": "active",
                "reset_result": {
                    "status": result.status.value,
                    "message": result.message
                }
            }
        else:
            return {
                "success": True,
                "message": "진행 중인 측정이 없습니다.",
                "previous_status": "inactive"
            }
        
    except Exception as e:
        print(f"[오류] 측정 리셋 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"리셋 오류: {str(e)}")