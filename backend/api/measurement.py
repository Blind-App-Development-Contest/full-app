"""측정 관련 라우터 - FastDepth 프레임 처리 및 보폭 측정"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
import asyncio
import logging
# 중앙화된 데이터베이스 연결 사용
from core.database import get_async_db
from models.database_models import User, Footstep, DashboardLog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from uuid import UUID
from datetime import datetime
from typing import Optional

from models.fastdepth_models import (
    FastDepthFrameData,
    EnhancedCommandRequest
)
from models.execution_schemas import (
    FullCommandResponse
)
from models.common_models import ExecutionStatus
from models.recognition_schemas import SpeechRecognitionResponse
from models.execution_schemas import CommandExecutionResponse
from services.command_executor import CommandExecutionResult
# speech_helpers.py 기능을 통합하여 직접 구현
from utils.fastdepth_processor import get_fastdepth_processor

# 카메라 모드 통합을 위한 임포트
from api.camera import manager as camera_manager
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("")
@router.get("/")
async def measurement_status():
    """측정 서비스 상태 확인"""
    return {
        "service": "Measurement System",
        "status": "active",
        "endpoints": {
            "commands/enhanced": "POST /commands/enhanced - 향상된 명령 처리",
            "fastdepth/frame": "POST /fastdepth/frame - FastDepth 프레임 처리",
            "frame": "POST /frame - 측정용 프레임 처리",
            "reset": "POST /reset - 측정 리셋",
            "session/start": "POST /session/start - 측정 세션 시작",
            "session/stop": "POST /session/stop - 측정 세션 중지"
        }
    }

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager

speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()

# ===============================
# speech_helpers.py 통합 기능들
# ===============================

def get_current_context() -> str:
    """현재 컨텍스트 조회"""
    try:
        if command_executor.is_measurement_active():
            return "measurement_active"
        else:
            return "default"
    except Exception as e:
        logger.error(f"컨텍스트 조회 실패: {e}")
        return "default"

async def process_fastdepth_frame(frame: FastDepthFrameData):
    """프레임 처리 - 새로운 IMU 통합 시스템 사용"""
    try:
        # 새로운 IMU 통합 시스템 사용
        processor = get_fastdepth_processor()
        
        # 더미 이미지 생성 (실제로는 클라이언트에서 이미지를 함께 보내야 함)
        import numpy as np
        dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # 기본 IMU 데이터
        import time
        default_imu_data = {
            'accelerometer': [0, 0, 9.81],
            'gyroscope': [0, 0, 0],
            'timestamp': time.time(),
            'device_orientation': 'portrait'
        }
        
        # 새로운 시스템으로 처리
        result = await processor.process_frame_for_measurement(
            cv_image=dummy_image,
            user_id="frame_processor",
            imu_data=default_imu_data,
            enable_advanced_fusion=False
        )
        
        return result
        
    except Exception as e:
        logger.error(f"FastDepth 프레임 처리 실패: {e}")
        raise

async def process_speech_command_with_context(request: EnhancedCommandRequest, context: str):
    """컨텍스트를 포함한 음성 명령 처리 - 새로운 시스템 사용"""
    try:
        # SpeechAnalyzer로 분석 (컨텍스트 포함)
        recognition_result = speech_analyzer.analyze_command(request.command_text, context)
        
        # 통합 조건부 실행 로직 사용
        execution_result = await execute_command_conditionally(
            recognition_result, 
            request.execute_immediately, 
            context
        )
        
        return recognition_result, execution_result
        
    except Exception as e:
        logger.error(f"음성 명령 처리 실패: {e}")
        raise

async def execute_command_conditionally(
    recognition_result: SpeechRecognitionResponse, 
    execute_immediately: bool,
    context: str = None
) -> CommandExecutionResult:
    """조건부 명령 실행 로직"""
    if execute_immediately:
        return await command_executor.execute_command(recognition_result)
    else:
        return CommandExecutionResult(
            status=ExecutionStatus.PENDING,
            message="명령이 분석되었습니다.",
            data={"execute_immediately": False, "context": context or get_current_context()},
            actions=["analyze_command"]
        )

def build_enhanced_response(command_result, frame_result, context: str):
    """향상된 응답 구성"""
    if command_result:
        recognition_result, execution_result = command_result
    else:
        recognition_result = SpeechRecognitionResponse(
            intent="FASTDEPTH_FRAME_ONLY",
            entities={"frame_processing": True, "context": context},
            confidence=1.0,
            command_text=""
        )
        execution_result = frame_result
    
    response_data = execution_result.data.copy() if execution_result else {}
    response_actions = execution_result.actions.copy() if execution_result else []
    
    # 컨텍스트 정보 추가
    response_data.update({
        "context": context
    })
    
    if frame_result:
        response_data.update({
            "frame_processing": {
                "processed": True,
                "frame_result": frame_result.data if hasattr(frame_result, 'data') else frame_result,
                "frame_message": frame_result.message if hasattr(frame_result, 'message') else "프레임 처리 완료"
            }
        })
    
    return FullCommandResponse(
        intent=recognition_result.intent,
        entities=recognition_result.entities,
        confidence=recognition_result.confidence,
        execution=CommandExecutionResponse(
            status=execution_result.status if execution_result else ExecutionStatus.SUCCESS,
            message=execution_result.message if execution_result else "처리 완료",
            data=response_data,
            actions=response_actions,
            timestamp=execution_result.timestamp if execution_result else datetime.now()
        )
    )

# ===============================
# 통합 완료 - speech_helpers.py 기능 포함
# ===============================#

# 측정 세션 제어를 위한 모델
class MeasurementSessionRequest(BaseModel):
    user_id: str

# 측정 결과 저장을 위한 모델
class MeasurementResultSave(BaseModel):
    user_id: UUID
    step_length_cm: int
    session_duration_seconds: Optional[int] = None
    frame_count: Optional[int] = None
    measurement_type: Optional[str] = None

class MeasurementLogResponse(BaseModel):
    log_id: int
    user_id: UUID
    step_length_cm: int
    created_at: datetime



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
    FastDepth 프레임만 처리 - 새로운 IMU 통합 시스템 사용
    """
    try:
        logger.debug("[FastDepth] 새로운 IMU 통합 시스템으로 프레임 처리 시작")
        
        # 새로운 통합 시스템 사용
        result = await process_fastdepth_frame(frame_data)
        
        if result:
            return {
                "success": True,
                "message": f"보폭 측정 완료: {result.step_length_cm}cm",
                "data": {
                    "step_length_cm": result.step_length_cm,
                    "confidence": result.confidence,
                    "method": result.source_data.get("method", "imu_integrated")
                },
                "actions": ["frame_processed"],
                "measurement_active": command_executor.is_measurement_active(),
                "processing_time_ms": result.source_data.get("processing_time_ms", 0)
            }
        else:
            return {
                "success": False,
                "message": "프레임 처리 결과가 없습니다.",
                "measurement_active": command_executor.is_measurement_active()
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
    user_id: str = Form('current_user'),
    enable_kalman: str = Form('true'),
    measurement_type: str = Form('sequence'),
    foot_detection_mode: str = Form('aggressive')
):
    """
    측정용 프레임 처리 - 간소화된 버전
    """
    try:
        logger.info(f'[측정 프레임] 사용자: {user_id}, 파일: {file.filename}')
        logger.info(f'[설정] Kalman 활성화: {enable_kalman}, 측정 타입: {measurement_type}, 발 인식 모드: {foot_detection_mode}')
        
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
        
        # 3. FastDepth 직접 처리 (Kalman 설정 포함)
        fastdepth_processor = get_fastdepth_processor()
        
        # Kalman filter 설정 정보 추가
        kalman_enabled = enable_kalman.lower() == 'true'
        logger.info(f'[Kalman 설정] 활성화: {kalman_enabled}')
        
        # IMU 데이터 기본값 (없으므로 None)
        imu_data = None
        
        measurement_result = await fastdepth_processor.process_frame_for_measurement(
            cv_image, 
            user_id, 
            imu_data=imu_data,
            enable_advanced_fusion=kalman_enabled  # Kalman 설정을 fusion 옵션으로 매핑
        )
        
        logger.info(f'[측정 결과] measurement_result: {measurement_result}')
        
        if measurement_result is None:
            logger.warning(f'[측정 결과] 결과가 None - 기본값 반환')
            return {
                'success': True,
                'measurement': None,
                'session_active': True,
                'message': '측정 진행 중 - 아직 결과 없음',
                'user_id': user_id
            }
        
        # 4. 메모리 정리 (메모리 누수 방지)
        del cv_image, nparr, frame_data
        import gc
        gc.collect()
        
        # 5. 간단한 응답 반환
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

# =========================
# DB 연동 엔드포인트
# =========================

@router.post("/results/save", response_model=MeasurementLogResponse)
async def save_measurement_result(
    request: MeasurementResultSave,
    session: AsyncSession = Depends(get_async_db)
):
    """측정 결과를 데이터베이스에 저장 (ORM 방식)"""
    try:
        # 1. 사용자 존재 확인
        user_result = await session.execute(
            select(User).where(User.user_id == request.user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        # 2. footstep 테이블에 보폭 정보 저장/업데이트 (ORM 방식)
        footstep_result = await session.execute(
            select(Footstep).where(Footstep.user_id == request.user_id)
        )
        existing_footstep = footstep_result.scalar_one_or_none()
        
        if existing_footstep:
            # 기존 보폭 업데이트
            existing_footstep.step_length = request.step_length_cm
        else:
            # 새로운 보폭 생성
            new_footstep = Footstep(
                user_id=request.user_id,
                step_length=request.step_length_cm
            )
            session.add(new_footstep)
        
        # 3. dashboard_logs에 측정 로그 저장 (ORM 방식)
        log_data_str = f"step_length: {request.step_length_cm}cm, duration: {request.session_duration_seconds}s, frames: {request.frame_count}, type: {request.measurement_type}"
        
        dashboard_log = DashboardLog(
            user_id=request.user_id,
            log_type="measurement_result",
            log_data=log_data_str
        )
        
        session.add(dashboard_log)
        await session.commit()
        
        # 새로 생성된 로그 정보 새로고침
        await session.refresh(dashboard_log)
        
        return MeasurementLogResponse(
            log_id=dashboard_log.dashboard_log_id,
            user_id=dashboard_log.user_id,
            step_length_cm=request.step_length_cm,
            created_at=dashboard_log.timestamp
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"측정 결과 저장 오류: {str(e)}")

@router.get("/results/user/{user_id}")
async def get_user_measurement_history(
    user_id: UUID,
    limit: int = 10,
    session: AsyncSession = Depends(get_async_db)
):
    """사용자별 측정 기록 조회 (ORM 방식)"""
    try:
        # 1. 사용자 존재 확인
        user_result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        
        # 2. ORM으로 측정 기록 조회
        logs_result = await session.execute(
            select(DashboardLog)
            .where(
                (DashboardLog.user_id == user_id) & 
                (DashboardLog.log_type == "measurement_result")
            )
            .order_by(DashboardLog.timestamp.desc())
            .limit(limit)
        )
        logs = logs_result.scalars().all()
        
        # 3. 응답 데이터 구성
        measurement_history = []
        for log in logs:
            measurement_history.append({
                "log_id": log.dashboard_log_id,
                "user_id": str(log.user_id),
                "log_data": log.log_data,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None
            })
        
        return {
            "user_id": str(user_id), 
            "measurement_history": measurement_history, 
            "count": len(measurement_history)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"측정 기록 조회 오류: {str(e)}")


# =========================
# 헬퍼 함수들 (speech_helpers.py에서 통합된 고유 함수들)
# =========================

# 공유 명령 실행 로직
def create_pending_execution_result(context: str = None) -> CommandExecutionResult:
    """
    PENDING 상태의 CommandExecutionResult 생성 (중복 제거용)
    
    Args:
        context: 실행 컨텍스트
        
    Returns:
        표준화된 PENDING CommandExecutionResult
    """
    return CommandExecutionResult(
        status=ExecutionStatus.PENDING,
        message="명령이 분석되었습니다.",
        data={"execute_immediately": False, "context": context or get_current_context()},
        actions=["analyze_command"]
    )


async def execute_command_conditionally(
    recognition_result: SpeechRecognitionResponse, 
    execute_immediately: bool,
    context: str = None
) -> CommandExecutionResult:
    """
    조건부 명령 실행 로직 (중복 제거용)
    
    Args:
        recognition_result: 음성 인식 결과
        execute_immediately: 즉시 실행 여부
        context: 실행 컨텍스트
        
    Returns:
        명령 실행 결과
    """
    if execute_immediately:
        return await command_executor.execute_command(recognition_result)
    else:
        return create_pending_execution_result(context)

