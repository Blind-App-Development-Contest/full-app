"""측정 관련 라우터 - FastDepth 프레임 처리 및 보폭 측정"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
import logging
# 중앙화된 데이터베이스 연결 사용
from core.database import get_async_db
from middleware.error_handler import ErrorLogger
from models.database_models import User, Footstep, DashboardLog, Voice
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from datetime import datetime
from typing import Optional

# 카메라 거리 측정에만 필요한 모델들
from models.common_models import ExecutionStatus
from services.singleton import service_manager
# 카메라 거리 측정을 위한 FastDepth 프로세서 
from utils.fastdepth_processor import get_fastdepth_processor

# 카메라 모드 통합을 위한 임포트
from api.camera import manager as camera_manager
from pydantic import BaseModel, Field, AliasChoices
import os

logger = logging.getLogger(__name__)
router = APIRouter()

# DEBUG: 프레임 저장을 위한 디렉토리 생성
DEBUG_FRAMES_DIR = "debug_frames"
os.makedirs(DEBUG_FRAMES_DIR, exist_ok=True)

async def save_debug_frame(cv_image, frame_count: int, user_id: str):
    """진단용 프레임 저장 - 카메라 입력을 시각적으로 검사하기 위함"""
    try:
        import cv2
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{DEBUG_FRAMES_DIR}/debug_{user_id}_{timestamp}_frame_{frame_count:03d}.jpg"
        # 이미지를 파일로 저장
        success = cv2.imwrite(filename, cv_image)
        if success:
            logger.info(f"[DEBUG] 프레임 저장됨: {filename}")
        else:
            logger.warning(f"[DEBUG] 프레임 저장 실패: {filename}")
            
    except Exception as e:
        logger.error(f"[DEBUG] 프레임 저장 중 오류: {e}")

# MediaPipe 정적 테스트 엔드포인트 제거됨 (프론트엔드에서 사용되지 않음)

@router.get("")
async def measurement_status(
    uuid: Optional[str] = None,
    session: AsyncSession = Depends(get_async_db)
):
    """
    측정 서비스 상태 확인 및 사용자 온보딩 상태 체크
    
    Args:
        uuid: 사용자 UUID (옵션)
        session: 데이터베이스 세션
        
    Returns:
        - uuid가 없으면: 서비스 상태만 반환
        - uuid가 있으면: 사용자 온보딩 완료 상태 포함하여 반환
    """
    # UUID가 없으면 기본 서비스 상태만 반환
    if not uuid:
        return {
            "service": "Measurement System",
            "status": "active",
            "endpoints": {
                "frame": "POST /frame - 카메라 거리 측정",
                "reset": "POST /reset - 측정 리셋",
                "session/start": "POST /session/start - 측정 세션 시작",
                "session/stop": "POST /session/stop - 측정 세션 중지"
            }
        }
    
    # UUID가 있으면 사용자 온보딩 상태 확인
    try:
        # UUID 유효성 검사
        from uuid import UUID as UUIDValidator
        try:
            user_uuid = UUIDValidator(uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="유효하지 않은 UUID 형식입니다")
        
        # 사용자 존재 여부 확인
        user_result = await session.execute(
            select(User).where(User.user_id == user_uuid)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            return {
                "service": "Measurement System",
                "status": "active",
                "setup_complete": False,
                "reason": "user_not_found",
                "message": "사용자를 찾을 수 없습니다. 새로운 온보딩이 필요합니다."
            }
        
        # 사용자 이름 확인
        has_name = user.user_name and user.user_name.strip()
        
        # 보폭 설정 확인
        footstep_result = await session.execute(
            select(Footstep).where(Footstep.user_id == user_uuid)
        )
        footstep = footstep_result.scalar_one_or_none()
        has_footstep = footstep is not None and footstep.step_length > 0
        
        # 음성 설정 확인
        voice_result = await session.execute(
            select(Voice).where(Voice.user_id == user_uuid)
        )
        voice = voice_result.scalar_one_or_none()
        has_voice = voice is not None
        
        # 온보딩 완료 여부 결정 (이름과 보폭 모두 설정되어야 완료)
        setup_complete = bool(has_name and has_footstep)
        
        return {
            "service": "Measurement System",
            "status": "active",
            "setup_complete": setup_complete,
            "user_id": str(user_uuid),
            "user_name": user.user_name,
            "onboarding_status": {
                "has_name": bool(has_name),
                "has_footstep": bool(has_footstep),
                "has_voice": bool(has_voice),
                "step_length_cm": footstep.step_length if footstep else None
            },
            "message": "온보딩이 완료되었습니다!" if setup_complete else "온보딩을 완료해주세요."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 상태 확인 오류: {e}")
        raise HTTPException(status_code=500, detail=f"사용자 상태 확인 중 오류가 발생했습니다: {str(e)}")

# 싱글톤 서비스 인스턴스는 상단에서 이미 import됨

# 사용하지 않는 FastDepth 및 음성 명령 통합 처리 함수들 제거됨

# ===============================
# 측정 처리 기능 완료
# ===============================#

# API 전용 모델들 (측정 라우터 로컬)
class MeasurementSessionRequest(BaseModel):
    # Accept both 'uuid' and 'user_id' from clients
    user_id: UUID = Field(validation_alias=AliasChoices('uuid', 'user_id'))
    context: Optional[str] = Field("onboarding", description="측정 컨텍스트: onboarding, reset")

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



# 사용하지 않는 enhanced command 및 fastdepth 전용 엔드포인트들 제거됨

@router.post("/frame")
async def process_measurement_frame(
    file: UploadFile = File(...),
    # Accept both 'uuid' and 'user_id' from form
    uuid: str | None = Form(None),
    user_id: str | None = Form(None),
    # 카메라 기반 거리 측정 전용
    frame_count: int = Form(default=1)
):
    """
    간소화된 카메라 기반 거리 측정 시스템
    
    워크플로우:
    1. 카메라 프레임으로 거리 측정
    2. 단순 거리 계산 (10m 측정용)
    """
    try:
        uid = uuid or user_id or 'current_user'
        logger.info(f'[카메라 거리 측정] 사용자: {uid}, 프레임: {frame_count}')
        
        # 1. 측정 세션 활성 상태 확인
        command_executor = service_manager.get_command_executor()
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
        
        # 성능 최적화: 이미지 크기 축소 (보폭 측정에는 640x480이면 충분)
        original_shape = cv_image.shape
        if cv_image.shape[1] > 640:  # width > 640
            scale = 640 / cv_image.shape[1]
            new_width = 640
            new_height = int(cv_image.shape[0] * scale)
            cv_image = cv2.resize(cv_image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
            logger.info(f'[이미지 최적화] {original_shape} → {cv_image.shape}')
        
        logger.info(f'[이미지 처리] 크기: {cv_image.shape}, 프레임: {frame_count}')
        
        # 2.5. DEBUG: 프레임 저장 (진단용)
        await save_debug_frame(cv_image, frame_count, uid)
        
        # 3. 카메라 기반 간단 측정 프로세서
        processor = get_fastdepth_processor()
        
        # 4. 카메라 프레임만으로 거리 측정
        measurement_result = await processor.process_frame_for_measurement(
            cv_image=cv_image,
            user_id=uid
        )
        
        # 5. 결과 로깅 및 반환
        logger.info(f'[카메라 측정 완료] 결과: {measurement_result}')
        
        if measurement_result is None:
            logger.warning('카메라 측정 결과가 None - 기본값 반환')
            return {
                'success': True,
                'measurement': None,
                'session_active': True,
                'message': '측정 진행 중 - 카메라 처리 중',
                'user_id': uuid
            }
        
        # 6. 메모리 정리
        del cv_image, nparr, frame_data
        import gc
        gc.collect()
        
        # 7. 성공 응답
        return {
            'success': True,
            'measurement': measurement_result.model_dump() if measurement_result else None,
            'session_active': True,
            'message': '카메라 측정 완료',
            'user_id': user_id,
            'processing_method': 'FastDepth_Camera_Only'
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
        command_executor = service_manager.get_command_executor()
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
        ErrorLogger.log_api_error("Measurement", "측정 리셋", e)
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
        user_id = str(request.user_id)  # UUID를 문자열로 변환
        logger.info(f"측정 세션 시작 요청 - 사용자: {user_id}")

        command_executor = service_manager.get_command_executor()
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
        user_id = str(request.user_id)  # UUID를 문자열로 변환
        logger.info(f"측정 세션 중지 요청 - 사용자: {user_id}")

        command_executor = service_manager.get_command_executor()
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
        
        # 측정 결과 가져오기
        last_measurement = command_executor.user_settings.get("step_length")
        measurement_result = {
            "step_length_cm": last_measurement or 65.0,
            "accuracy": "낮음",
            "method": "자동 측정"
        }
        
        # 카메라 모드는 측정 완료 화면을 위해 유지
        camera_mode_switched = False
        camera_error = None
        logger.info(f'측정 완료 - 결과 화면으로 진행: {user_id} ({last_measurement}cm)')
        
        
        # 컨텍스트에 따른 다음 단계 결정
        context = getattr(request, 'context', 'onboarding')
        
        if context == "reset":
            # 재설정: DB 업데이트 후 설정화면으로 복귀
            next_step = {
                "action": "return_to_settings",
                "screen": "settings", 
                "next_process": None,
                "button_text": "설정으로 돌아가기"
            }
            # 카메라 모드를 realtime으로 즉시 복원
            try:
                if hasattr(camera_manager, 'set_user_mode'):
                    camera_manager.set_user_mode(user_id, 'realtime')
                elif user_id in camera_manager.active_connections:
                    camera_manager.user_modes[user_id] = "realtime"
                camera_mode_switched = True
                logger.info(f'재설정 완료 - 카메라 모드 복원: realtime (user: {user_id})')
            except Exception as e:
                camera_error = str(e)
                logger.warning(f'카메라 모드 복원 실패: {e}')
            
            # CommandExecutor에서 음성 메시지 가져오기
            command_executor = service_manager.get_command_executor()
            message = command_executor.get_voice_message("step_measurement_reset", step_length=measurement_result['step_length_cm'])
            camera_mode = "realtime"
        else:
            # 온보딩: 결과 화면 표시 후 음성 설정으로 진행
            next_step = {
                "action": "show_result_screen",
                "screen": "measurement_result", 
                "next_process": "voice_settings",
                "button_text": "다음 단계로"
            }
            # CommandExecutor에서 음성 메시지 가져오기
            command_executor = service_manager.get_command_executor()
            message = command_executor.get_voice_message("step_measurement_complete", step_length=measurement_result['step_length_cm'])
            camera_mode = camera_manager.user_modes.get(user_id, "measurement")  # 결과 화면을 위해 측정 모드 유지

        # 완료 정보 생성
        completion_info = {
            "success": True,
            "status": "measurement_completed",
            "message": message,
            "session_active": False,
            "user_id": user_id,
            "measurement_result": measurement_result,
            "context": context,
            "next_step": next_step,
            "camera_mode": camera_mode,
            "camera_connected": user_id in camera_manager.active_connections,
            "camera_mode_switched": camera_mode_switched
        }
        
        # 카메라 오류가 있는 경우 경고 포함
        if camera_error:
            completion_info["camera_warning"] = f"카메라 모드 설정 실패: {camera_error}"
        
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
            # 기존 보폭 업데이트 (cm를 정수로 변환)
            setattr(existing_footstep, 'step_length', int(round(request.step_length_cm)))
        else:
            # 새로운 보폭 생성 (cm를 정수로 변환)
            new_footstep = Footstep(
                user_id=request.user_id,
                step_length=int(round(request.step_length_cm))
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
        
        # SQLAlchemy 속성을 적절히 변환
        log_id_value = getattr(dashboard_log, 'dashboard_log_id')
        user_id_value = getattr(dashboard_log, 'user_id')
        timestamp_value = getattr(dashboard_log, 'timestamp')
        
        return MeasurementLogResponse(
            log_id=int(log_id_value),
            user_id=UUID(str(user_id_value)),
            step_length_cm=int(round(request.step_length_cm)),
            created_at=timestamp_value
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
                "timestamp": log.timestamp.isoformat() if hasattr(log.timestamp, 'isoformat') and log.timestamp is not None else str(log.timestamp) if log.timestamp is not None else None
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
# 측정 처리 헬퍼 함수들
# =========================

# create_pending_execution_result 함수는 중복 제거됨 - execute_command_conditionally에서 인라인 처리




# =========================
# 간소화된 카메라 전용 측정 시스템
# =========================
