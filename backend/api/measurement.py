"""측정 관련 라우터 - FastDepth 프레임 처리 및 보폭 측정"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
import asyncio
import logging

from models.fastdepth_models import (
    FastDepthFrameData,
    EnhancedCommandRequest
)
from models.execution_schemas import (
    FullCommandResponse
)
from api.speech_helpers import (
    get_current_context,
    process_fastdepth_frame,
    process_speech_command_with_context,
    build_enhanced_response
)
from utils.fastdepth_processor import get_fastdepth_processor

# 카메라 모드 통합을 위한 임포트
from api.camera import manager as camera_manager
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager

speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()

# 측정 세션 제어를 위한 모델
class MeasurementSessionRequest(BaseModel):
    user_id: str



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

@router.post("/frame")
async def process_measurement_frame(
    file: UploadFile = File(...),
    user_id: str = Form('current_user')
):
    """
    측정용 프레임 처리 - 간소화된 버전
    """
    try:
        logger.info(f'[측정 프레임] 사용자: {user_id}, 파일: {file.filename}')
        
        # 1. 측정 세션 활성 상태 확인
        if not hasattr(command_executor, 'is_measurement_active') or not command_executor.is_measurement_active():
            return {
                'success': False,
                'error': '활성화된 측정 세션이 없습니다',
                'message': '먼저 보폭 측정을 시작해주세요'
            }
        
        # 2. 이미지 파일 읽기 및 OpenCV 변환
        frame_data = await file.read()
        import cv2
        import numpy as np
        nparr = np.frombuffer(frame_data, np.uint8)
        cv_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if cv_image is None:
            raise ValueError('유효하지 않은 이미지 데이터')
        
        # 3. FastDepth 직접 처리 (모든 변환과 계산이 내부에서 처리됨)
        from utils.fastdepth_processor import get_fastdepth_processor
        fastdepth_processor = get_fastdepth_processor()
        
        measurement_result = await fastdepth_processor.process_frame_for_measurement(cv_image, user_id)
        
        # 4. 간단한 응답 반환
        return {
            'success': True,
            'measurement': measurement_result.model_dump() if measurement_result else None,
            'session_active': True,
            'message': '프레임 처리 완료',
            'user_id': user_id
        }
        
    except Exception as e:
        logger.error(f'[측정 프레임] 처리 오류: {e}')
        raise HTTPException(status_code=500, detail=f'프레임 처리 실패: {str(e)}')


@router.post("/reset")
async def reset_measurement():
    """
    진행 중인 보폭 측정 리셋
    """
    try:
        if command_executor.is_measurement_active():
            # 측정 취소 실행
            await command_executor._execute_footstep_measurement_cancel({})
            
            return {
                "success": True,
                "message": "측정이 리셋되었습니다."
            }
        else:
            return {
                "success": True,
                "message": "진행 중인 측정이 없습니다."
            }
        
    except Exception as e:
        print(f"[오류] 측정 리셋 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"리셋 오류: {str(e)}")

@router.post("/session/start")
async def start_measurement_session(request: MeasurementSessionRequest):
    """
    측정 세션 시작 및 카메라 모드 자동 전환
    
    Args:
        request: 사용자 ID 포함된 요청
        
    Returns:
        측정 세션 시작 결과 및 카메라 모드 상태
    """
    try:
        user_id = request.user_id
        logger.info(f"측정 세션 시작 요청 - 사용자: {user_id}")
        
        # 이미 측정이 활성화되어 있는지 확인
        if command_executor.is_measurement_active():
            return {
                "status": "already_active",
                "message": "측정 세션이 이미 활성화되어 있습니다.",
                "session_active": True,
                "camera_mode": camera_manager.user_modes.get(user_id, "realtime")
            }
        
        # 측정 세션 시작
        session_started = command_executor.start_step_measurement()
        
        if not session_started:
            return {
                "status": "failed",
                "message": "측정 세션 시작에 실패했습니다.",
                "session_active": False,
                "camera_mode": camera_manager.user_modes.get(user_id, "realtime")
            }
        
        # 카메라 모드를 측정 모드로 설정 (안전한 오류 처리 포함)
        camera_mode_switched = False
        camera_error = None
        try:
            if hasattr(camera_manager, 'set_user_mode'):
                camera_manager.set_user_mode(user_id, 'measurement')
                camera_mode_switched = True
                logger.info(f'카메라 모드를 측정 모드로 변경: {user_id}')
            elif user_id in camera_manager.active_connections:
                # Fallback to direct mode setting
                previous_mode = camera_manager.user_modes.get(user_id, "realtime")
                camera_manager.user_modes[user_id] = "measurement"
                camera_mode_switched = True
                logger.info(f"카메라 모드 자동 전환: {previous_mode} → measurement (user: {user_id})")
        except Exception as e:
            camera_error = str(e)
            logger.warning(f'카메라 모드 설정 실패 (측정은 계속): {e}')
        
        # 세션 정보 생성
        session_info = {
            "success": True,
            "status": "started",
            "message": "측정 세션이 시작되었습니다.",
            "session_active": True,
            "user_id": user_id,
            "camera_mode": camera_manager.user_modes.get(user_id, "realtime"),
            "camera_connected": user_id in camera_manager.active_connections,
            "camera_mode_switched": camera_mode_switched
        }
        
        # 카메라 오류가 있는 경우 경고 포함
        if camera_error:
            session_info["camera_warning"] = f"카메라 모드 설정 실패: {camera_error}"
            session_info["message"] = "측정 세션이 시작되었습니다 (카메라 모드 설정 경고 있음)."
        
        return session_info
        
    except Exception as e:
        logger.error(f"측정 세션 시작 오류: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"측정 세션 시작 중 오류가 발생했습니다: {str(e)}"
        )

@router.post("/session/stop")
async def stop_measurement_session(request: MeasurementSessionRequest):
    """
    측정 세션 중지 및 카메라 모드 자동 복원
    
    Args:
        request: 사용자 ID 포함된 요청
        
    Returns:
        측정 세션 완료 결과 및 카메라 모드 상태
    """
    try:
        user_id = request.user_id
        logger.info(f"측정 세션 중지 요청 - 사용자: {user_id}")
        
        # 현재 측정 상태 확인
        if not command_executor.is_measurement_active():
            return {
                "status": "not_active",
                "message": "활성화된 측정 세션이 없습니다.",
                "session_active": False,
                "camera_mode": camera_manager.user_modes.get(user_id, "realtime")
            }
        
        
        # 측정 세션 중지
        await command_executor._execute_footstep_measurement_cancel({})
        
        # 카메라 모드를 실시간 모드로 복원 (안전한 오류 처리 포함)
        camera_mode_switched = False
        camera_error = None
        try:
            if hasattr(camera_manager, 'set_user_mode'):
                camera_manager.set_user_mode(user_id, 'realtime')
                camera_mode_switched = True
                logger.info(f'카메라 모드를 실시간 모드로 복원: {user_id}')
            elif user_id in camera_manager.active_connections:
                # Fallback to direct mode setting
                previous_mode = camera_manager.user_modes.get(user_id, "measurement")
                camera_manager.user_modes[user_id] = "realtime"
                camera_mode_switched = True
                logger.info(f"카메라 모드 자동 복원: {previous_mode} → realtime (user: {user_id})")
        except Exception as e:
            camera_error = str(e)
            logger.warning(f'카메라 모드 복원 실패: {e}')
        
        
        # 완료 정보 생성
        completion_info = {
            "success": True,
            "status": "completed",
            "message": "측정 세션이 완료되었습니다.",
            "session_active": False,
            "user_id": user_id,
            "camera_mode": camera_manager.user_modes.get(user_id, "realtime"),
            "camera_connected": user_id in camera_manager.active_connections,
            "camera_mode_switched": camera_mode_switched
        }
        
        # 카메라 오류가 있는 경우 경고 포함
        if camera_error:
            completion_info["camera_warning"] = f"카메라 모드 복원 실패: {camera_error}"
            completion_info["message"] = "측정 세션이 완료되었습니다 (카메라 모드 복원 경고 있음)."
        
        return completion_info
        
    except Exception as e:
        logger.error(f"측정 세션 중지 오류: {e}")
        # 오류 발생 시에도 강제로 측정 중지 및 모드 복원
        try:
            command_executor.cancel_step_measurement()
            if user_id in camera_manager.active_connections:
                camera_manager.user_modes[user_id] = "realtime"
        except:
            pass
        
        raise HTTPException(
            status_code=500,
            detail=f"측정 세션 중지 중 오류가 발생했습니다: {str(e)}"
        )

