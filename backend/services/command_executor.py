import asyncio
import logging
import requests
import time
import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from models.recognition_schemas import SpeechRecognitionResponse 
from models.common_models import (
    AppMode, ExecutionStatus, MeasurementStatus,
    RealTimeMeasurementStatus, TrackingQuality, SchemaConverter
)
from models.database_models import User, UserSetting
from core.database import get_sync_session
from models.step_models import (
    StepCalculationResult as StepResult, 
    StepMeasurementMethod, 
    AccuracyConverter, 
    StepCalculationInput,
    StepTrackingQuality
)
from config.settings import get_settings
from utils.fastdepth_processor import get_fastdepth_processor
from utils.voice_speed_converter import convert_to_google_tts_speed

settings = get_settings()
logger = logging.getLogger(__name__)

class SetupStep(Enum):
    """설정 단계"""
    START = "start"                    # 시작
    USER_NAME = "user_name"           # 사용자 이름
    STEP_LENGTH = "step_length"       # 보폭 측정
    VOICE_GENDER = "voice_gender"     # 음성 종류 (여성/남성)
    VOICE_SPEED = "voice_speed"       # 음성 속도
    CAREGIVER_INFO = "caregiver_info" # 보호자 정보
    MODE_SELECTION = "mode_selection" # 모드 선택 (길찾기/카메라)
    COMPLETE = "complete"             # 설정 완료

class CommandExecutionResult:
    """명령 실행 결과"""
    def __init__(
        self, 
        status: ExecutionStatus, 
        message: str, 
        data: Optional[Dict[str, Any]] = None,
        actions: Optional[List[str]] = None
    ):
        self.status = status
        self.message = message
        self.data = data or {}
        self.actions = actions or []
        self.timestamp = datetime.now()

class CommandExecutor:
    """음성 명령 실행 엔진"""
    
    def __init__(self, user_id: str = None):
        self.user_id = user_id
        self.is_listening = True
        self.current_mode = AppMode.SETUP
        self.current_setup_step = SetupStep.START
        self.execution_history = []
        
        # 상태 영속화 초기화
        if user_id:
            self._load_user_state(user_id)

        # 사용자 설정 정보 
        self.user_settings = {
            "user_name": None,
            "step_length": None,
            "voice_gender": "F", 
            "voice_speed": 1.0, # Google TTS speaking_rate (0.25-4.0)
            "caregiver_name": None,
            "caregiver_phone": None,
            "preferred_mode": None
        }

        # 실시간 측정을 위한 상태 변수
        self.measurement_active = False
        self.measurement_status = MeasurementStatus.INACTIVE
        self.measurement_start_time = None
        self.frame_count = 0
        self.step_tracker = None  # 레거시 호환성 (더 이상 사용하지 않음)
        
        self.fastdepth_processor = None  # 새로운 FastDepth 프로세서
        self.session_id = None # 측정 세션 ID

    def _load_user_state(self, user_id: str):
        """데이터베이스에서 사용자 설정을 조회하여 상태를 판단"""
        try:
            with get_sync_session() as session:
                # 사용자 정보 조회
                user = session.query(User).filter(User.user_id == user_id).first()
                if not user:
                    print(f"[DEBUG] 새 사용자 - 기본 상태로 초기화")
                    return
                
                # 관련 설정 조회 - 직접 각 테이블에서 확인 (더 안전한 방법)
                user_setting = session.query(UserSetting).filter(UserSetting.user_id == user_id).first()
                
                # 각 테이블에서 직접 데이터 존재 확인
                from models.database_models import Voice, Caregiver, Footstep
                voice_exists = session.query(Voice).filter(Voice.user_id == user_id).first() is not None
                caregiver_exists = session.query(Caregiver).filter(Caregiver.user_id == user_id).first() is not None
                footstep_exists = session.query(Footstep).filter(Footstep.user_id == user_id).first() is not None
                
                # 온보딩 완료 여부 판단 (user_settings 외래키 방식과 직접 확인 방식 모두 체크)
                has_voice_setting = voice_exists or (user_setting and user_setting.voice_id is not None)
                has_caregiver_info = caregiver_exists or (user_setting and user_setting.caregiver_id is not None)  
                has_footstep_info = footstep_exists or (user_setting and user_setting.step_id is not None)
                has_user_name = user.user_name is not None and len(user.user_name.strip()) > 0
                
                # 디버깅 로그 추가
                print(f"[DEBUG] 온보딩 상태 체크 - user_id: {user_id}")
                print(f"  - user_setting 존재: {user_setting is not None}")
                if user_setting:
                    print(f"  - user_settings.voice_id: {user_setting.voice_id}")
                    print(f"  - user_settings.caregiver_id: {user_setting.caregiver_id}")
                    print(f"  - user_settings.step_id: {user_setting.step_id}")
                print(f"  - voice 테이블에 데이터 존재: {voice_exists}")
                print(f"  - caregiver 테이블에 데이터 존재: {caregiver_exists}")
                print(f"  - footstep 테이블에 데이터 존재: {footstep_exists}")
                print(f"  - user_name: '{user.user_name}'")
                print(f"  - has_voice_setting: {has_voice_setting}")
                print(f"  - has_caregiver_info: {has_caregiver_info}")
                print(f"  - has_footstep_info: {has_footstep_info}")
                print(f"  - has_user_name: {has_user_name}")
                
                # 모든 설정이 완료되면 온보딩 완료로 판단
                onboarding_complete = all([has_voice_setting, has_caregiver_info, has_footstep_info, has_user_name])
                
                if onboarding_complete:
                    # 온보딩 완료 - 일반 모드로 설정
                    self.current_mode = AppMode.NORMAL
                    self.current_setup_step = SetupStep.COMPLETE
                    print(f"[DEBUG] 온보딩 완료된 사용자 - 일반 모드로 설정")
                else:
                    # 온보딩 미완료 - SETUP 모드로 설정하고 해당 단계부터 시작
                    self.current_mode = AppMode.SETUP
                    if not has_user_name:
                        self.current_setup_step = SetupStep.START
                    elif not has_footstep_info:
                        self.current_setup_step = SetupStep.STEP_LENGTH
                    elif not has_voice_setting:
                        self.current_setup_step = SetupStep.VOICE_GENDER
                    elif not has_caregiver_info:
                        self.current_setup_step = SetupStep.CAREGIVER_INFO
                    else:
                        self.current_setup_step = SetupStep.MODE_SELECTION
                    
                    print(f"[DEBUG] 온보딩 미완료 - SETUP 모드, 단계: {self.current_setup_step.value}")
                    
        except Exception as e:
            print(f"[ERROR] 사용자 상태 로드 실패: {e}")
            # 오류 발생 시 기본 상태 유지

    def _save_user_state(self):
        """사용자 기본 정보 생성 (상태는 코드로 관리)"""
        if not self.user_id:
            return
            
        try:
            with get_sync_session() as session:
                # 사용자가 존재하지 않으면 생성
                user = session.query(User).filter(User.user_id == self.user_id).first()
                if not user:
                    user = User(user_id=self.user_id)
                    session.add(user)
                    session.commit()
                    print(f"[DEBUG] 새 사용자 생성 완료 - user_id: {self.user_id}")
                
        except Exception as e:
            print(f"[ERROR] 사용자 생성 실패: {e}")
        
        # 보폭 계산을 위한 데이터 수집
        self.processed_frames = []  # For UnifiedStepCalculator
        self.total_distance_traveled = 0.0  # Accumulated distance in meters
        self.last_position = None  # Last known foot position
        
        # 새로운 IMU 통합 시스템 사용 (unified calculator 제거됨)

        
    async def execute_command(
        self, 
        recognition_result: SpeechRecognitionResponse
    ) -> CommandExecutionResult:
        """
        인식된 음성 명령을 실제로 실행
        
        Args:
            recognition_result: 음성 인식 및 분석 결과
            
        Returns:
            CommandExecutionResult: 실행 결과
        """
        intent = recognition_result.intent
        entities = recognition_result.entities
        
        
        try:
            # 설정 모드인 경우 설정 단계별 처리
            if self.current_mode == AppMode.SETUP:
                result = await self._handle_setup_mode(intent, entities, recognition_result.command_text)
            else:
                # 일반 모드 명령 처리
                result = await self._handle_normal_mode(intent, entities)
            
            # 실행 기록 저장
            self._save_execution_history(intent, entities, result)
            
            return result
            
        except Exception as e:
            logger.error(f"명령 실행 중 오류: {e}")
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"명령 실행 중 오류가 발생했습니다: {str(e)}"
            )

    async def _handle_setup_mode(self, intent: str, entities: Dict[str, Any], command_text: str) -> CommandExecutionResult:
        """설정 모드 처리"""
        print(f"[DEBUG] 설정 모드 처리 - 현재 단계: {self.current_setup_step.value}, 의도: {intent}")
        
        if self.current_setup_step == SetupStep.START:
            return await self._setup_start()

        elif self.current_setup_step == SetupStep.USER_NAME:
            return await self._setup_user_name(command_text)

        elif self.current_setup_step == SetupStep.STEP_LENGTH:
            return await self._setup_step_length(intent, entities)  

        elif self.current_setup_step == SetupStep.VOICE_GENDER:
            return await self._setup_voice_gender(command_text)

        elif self.current_setup_step == SetupStep.VOICE_SPEED:
            return await self._setup_voice_speed(command_text)

        elif self.current_setup_step == SetupStep.CAREGIVER_INFO:
            return await self._setup_caregiver_info(command_text)

        elif self.current_setup_step == SetupStep.MODE_SELECTION:
            return await self._setup_mode_selection(intent)

        else:
            return await self._setup_complete()
    
    async def _setup_start(self) -> CommandExecutionResult:
        """설정 시작"""
        self.current_setup_step = SetupStep.USER_NAME

        return CommandExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message="안녕하세요! A:Eye 앱에 오신 것을 환영합니다. 먼저 사용자 이름을 알려주세요.",
            data={
                "setup_step": "user_name",
                "progress": "1/6"
            },
            actions=["tts_announce", "setup_progress_show"]
        )

    async def _setup_user_name(self, command_text: str) -> CommandExecutionResult:
        """사용자 이름 설정"""
        # 이름 추출 (더 정교한 처리)
        name = command_text.replace("내 이름은", "").replace("이름은", "").replace("저는", "").replace("입니다", "").replace("예요", "").replace("에요", "").strip()
        
        if len(name) > 1:
            self.user_settings["user_name"] = name
            self.current_setup_step = SetupStep.STEP_LENGTH
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"{name}님, 반갑습니다! 이제 보폭 측정을 시작하겠습니다. '보폭 측정 시작'이라고 말씀해주세요.",
                data={
                    "setup_step": "step_length",
                    "user_name": name,
                    "progress": "2/6"
                },
                actions=["tts_announce", "setup_progress_show"]
            )
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="이름을 정확히 들을 수 없었습니다. 다시 이름을 말씀해주세요.",
                data={"setup_step": "user_name"},
                actions=["tts_announce"]
            )

    async def _setup_step_length(self, intent: str, entities: Dict[str, Any]) -> CommandExecutionResult:
        """보폭 측정(칼만 필터 사용)"""
        # 실시간 칼만 필터 측정 요청
        if intent in ["FOOTSTEP_MEASUREMENT_START", "FOOTSTEP_MEASUREMENT_START_REALTIME"] or "보폭 측정" in intent or "측정 시작" in intent:
            return await self._execute_footstep_measurement_start(entities)

        # 측정 완료 요청
        elif intent == "FOOTSTEP_MEASURMENT_COMPLETE" or "측정 완료" in intent or "완료" in intent:
            result = await self._execute_footstep_measurement_complete(entities)
            if result.status == ExecutionStatus.SUCCESS:
                # 설정 다음 단계로 진행
                self.current_setup_step = SetupStep.VOICE_GENDER
                result.message += "보폭 측정이 완료되었습니다. 이제 음성 성별을 설정하겠습니다."
                result.data.update({
                    "setup_step": "voice_gender",
                    "progress": "3/6"
                })
                # result.actions.append("tts_announce")
                result.actions.append("setup_progress_show")
            return result
        # 측정 취소 요청
        elif intent == "FOOTSTEP_MEASUREMENT_CANCEL" or "취소" in intent or "중단" in intent:
            await self._execute_footstep_measurement_cancel(entities)
            
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="보폭 측정이 취소되었습니다. 다시 측정하시려면 '보폭 측정 시작'이라고 말씀해주세요.",
                data={"setup_step": "step_length"},
                actions=["tts_announce"]
            )
        
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="보폭 측정을 시작하려면 '보폭 측정 시작'이라고 말씀해주세요.",
                data={"setup_step": "step_length"},
                actions=["tts_announce"]
            )

    # ===== 칼만 필터 기반 보폭 측정 메서드 =====
    
    async def _execute_footstep_measurement_start(self, _entities: Dict[str, Any]) -> CommandExecutionResult:
        """칼만 필터 기반 보폭 측정 시작 - 통합 메서드 사용"""        
        try:
            print("[CommandExecutor] 보폭 측정 시작 요청")
            
            # 통합 측정 시작 메서드 사용
            success = self.start_step_measurement()
            if not success:
                return CommandExecutionResult(
                    status=ExecutionStatus.FAILED,
                    message="이미 보폭 측정이 진행 중입니다. 먼저 측정을 완료하거나 취소해주세요."
                )
            
            print("[CommandExecutor] 보폭 측정 시작 완료")
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="정밀 보폭 측정을 시작합니다! 자연스럽게 걸어주세요. '측정 완료'라고 말하시면 종료됩니다.",
                data={
                    "mode": "footstep_measurement",
                    "measurement_type": "kalman_filter",
                    "measurement_status": "active",
                    "session_id": self.session_id,
                    "start_time": self.measurement_start_time,
                    "tracking_active": True
                },
                actions=["footstep_measurement_ready", "tts_announce", "fastdepth_activate"]
            )
            
        except Exception as e:
            print(f"[CommandExecutor] 보폭 측정 시작 실패: {e}")
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"보폭 측정 시작 실패: {str(e)}"
            )

    async def _execute_footstep_measurement_begin(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """보폭 측정 진행 상태 확인 (칼만 필터)"""
        try:
            if not self.measurement_active or self.step_tracker is None:
                return CommandExecutionResult(
                    status=ExecutionStatus.FAILED,
                    message="보폭 측정이 시작되지 않았습니다. '보폭 측정 시작'이라고 말씀해주세요."
                )
            
            # 현재 측정 상태 반환 (CommandExecutor 상태를 전달)
            step_result = self.step_tracker.get_current_step_result()
            performance_metrics = self.step_tracker.get_performance_metrics(
                frame_count=self.frame_count,
                start_time=self.measurement_start_time or time.time()
            )
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"측정이 진행 중입니다. 현재까지 {step_result.step_count}걸음 측정되었습니다. 계속 걸어주세요.",
                data={
                    "mode": "footstep_walking",
                    "measurement_status": "측정중",
                    "measurement_type": "kalman_filter",
                    "current_step_cm": step_result.step_length_cm,
                    "step_count": step_result.step_count,
                    "confidence": step_result.confidence,
                    "tracking_quality": step_result.tracking_quality,
                    "measurement_duration": round(time.time() - self.measurement_start_time if self.measurement_start_time else 0, 1),
                    "fps": performance_metrics["fps"]
                },
                actions=["footstep_walking_start", "tts_announce"]
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"측정 상태 확인 실패: {str(e)}"
            )

    async def _execute_footstep_measurement_complete(self, _entities: Dict[str, Any]) -> CommandExecutionResult:
        """칼만 필터 기반 보폭 측정 완료 - 통합 메서드 사용"""
        try:
            if not self.measurement_active:
                return CommandExecutionResult(
                    status=ExecutionStatus.FAILED,
                    message="진행 중인 보폭 측정이 없습니다."
                )
            
            # 통합 측정 중지 메서드 사용
            result = self.stop_step_measurement()
            
            # 측정된 보폭이 없는 경우
            if result is None:
                return CommandExecutionResult(
                    status=ExecutionStatus.FAILED,
                    message="측정된 보폭이 없습니다. 더 오래 걸어보시거나 다시 시도해주세요.",
                    data={
                        "mode": "footstep_no_result",
                        "measurement_duration": 0,
                        "frame_count": self.frame_count
                    },
                    actions=["footstep_measurement_failed", "tts_announce", "fastdepth_deactivate"]
                )
            
            # 품질에 따른 메시지 생성
            quality_messages = {
                StepTrackingQuality.EXCELLENT: "매우 정확하게 측정되었습니다!",
                StepTrackingQuality.GOOD: "정확하게 측정되었습니다!",
                StepTrackingQuality.FAIR: "측정이 완료되었습니다. 더 긴 거리에서 재측정하면 정확도가 향상됩니다.",
                StepTrackingQuality.POOR: "측정이 완료되었지만 정확도가 낮습니다. 재측정을 권장합니다."
            }
            
            quality_msg = quality_messages.get(result.tracking_quality, "")
            
            print(f"[CommandExecutor] 보폭 측정 완료")
            print(f"  - 측정된 보폭: {result.step_length_cm}cm")
            print(f"  - 걸음 수: {result.step_count}")
            print(f"  - 추적 품질: {result.tracking_quality}")
            print(f"  - 신뢰도: {result.confidence:.2f}")
            print(f"  - 처리 시간: {result.processing_time_ms or 0:.1f}ms")
            print(f"  - 측정 방식: {result.measurement_method}")
            
            # API 호출로 보폭 저장 (기존 API 호환성)
            try:
                response = requests.post(
                    "http://localhost:8000/api/users/footstep/measurements",
                    json={
                        "measurement_type": result.measurement_method.value,
                        "step_length_cm": result.step_length_cm,
                        "step_count": result.step_count,
                        "confidence": result.confidence,
                        "tracking_quality": result.tracking_quality.value,
                        "measurement_duration": result.processing_time_ms or 0,
                        "user_id": self.user_settings.get("user_name")
                    },
                    timeout=5
                )
                print(f"[CommandExecutor] API 저장 결과: {response.status_code}")
            except Exception as api_error:
                print(f"[CommandExecutor] API 저장 실패 (무시): {api_error}")
            
            # 다음 단계(음성 설정)로 자동 진행
            self.current_setup_step = SetupStep.VOICE_GENDER
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"보폭 측정이 완료되었습니다! 측정된 보폭은 {result.step_length_cm}cm입니다. {quality_msg} 이제 다음 단계로 진행하겠습니다.",
                data={
                    "mode": "footstep_complete_next_step",
                    "measurement_type": result.measurement_method.value,
                    "step_length": result.step_length_cm,
                    "step_count": result.step_count,
                    "confidence": result.confidence,
                    "tracking_quality": result.tracking_quality.value,
                    "measurement_duration": round((result.processing_time_ms or 0) / 1000, 1),
                    "frame_count": result.step_count,
                    "fps": 0.0,
                    "measurement_status": "완료",
                    "session_id": result.source_data.get("session_id"),
                    "next_step": {
                        "action": "show_result_and_proceed",
                        "screen": "measurement_result_with_button", 
                        "next_process": "voice_settings",
                        "button_text": "다음 단계로",
                        "setup_step": "voice_gender"
                    }
                },
                actions=["footstep_measurement_complete", "show_result_screen", "tts_announce", "timer_stop", "fastdepth_deactivate"]
            )
            
        except Exception as e:
            print(f"[CommandExecutor] 보폭 측정 완료 실패: {e}")
            self.cancel_step_measurement()  # 안전하게 상태 리셋
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"보폭 측정 완료 실패: {str(e)}"
            )

    async def _execute_footstep_measurement_cancel(self, _entities: Dict[str, Any]) -> CommandExecutionResult:
        """보폭 측정 취소 - 통합 메서드 사용"""
        try:
            if not self.measurement_active:
                return CommandExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    message="현재 진행 중인 보폭 측정이 없습니다."
                )
            
            # 통합 측정 취소 메서드 사용
            success = self.cancel_step_measurement()
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="보폭 측정이 취소되었습니다.",
                data={
                    "mode": "footstep_cancelled",
                    "measurement_status": "cancelled",
                    "cancel_success": success
                },
                actions=["footstep_measurement_cancel", "tts_announce", "fastdepth_deactivate"]
            )
            
        except Exception as e:
            print(f"[CommandExecutor] 보폭 측정 취소 실패: {e}")
            self.cancel_step_measurement()  # 강제 취소
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,  # 취소는 항상 성공으로 처리
                message="측정이 취소되었습니다.",
                data={"error": str(e)}
            )

    # ===== FastDepth 프레임 처리 메서드 =====
    
    async def process_fastdepth_frame(self, foot_data: Dict[str, Any]) -> Optional[CommandExecutionResult]:
        """
        FastDepth 프레임 데이터 처리 (외부에서 호출) 
        
        이 메서드는 더 이상 프레임 변환을 하지 않고, 이미 변환된 데이터만 받아서
        통합된 process_step_frame 메서드로 위임합니다.
        실제 프레임 변환은 FastDepthProcessor에서 수행되어야 합니다.
        """
        try:
            # 통합 프레임 처리 메서드 위임 (변환은 이미 완료된 상태)
            result = await self.process_step_frame(foot_data)
            
            if result is None:
                return None  # 측정이 비활성화되었거나 결과가 없음
            
            # 30프레임마다 중간 결과 업데이트 (1초마다, 30fps 기준)
            should_announce = self.frame_count % 30 == 0
            
            if should_announce and result.step_count > 0:
                return CommandExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    message=f"측정 중... 현재 보폭: {result.step_length_cm}cm (걸음수: {result.step_count})",
                    data={
                        "mode": "footstep_frame_update",
                        "current_step_cm": result.step_length_cm,
                        "step_count": result.step_count,
                        "confidence": result.confidence,
                        "tracking_quality": result.tracking_quality.value,
                        "frame_count": result.step_count,  # 걸음 수를 프레임 수 대신 사용
                        "fps": 0.0,  # FPS 정보는 없음
                        "measurement_result": result.model_dump()
                    },
                    actions=["footstep_frame_update"]
                )
            else:
                # 무음 업데이트 (로그만)
                return CommandExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    message="",  # 무음
                    data={
                        "mode": "footstep_frame_silent_update",
                        "frame_count": self.frame_count,
                        "measurement_result": result.model_dump() if result else None
                    },
                    actions=[]
                )
                
        except Exception as e:
            print(f"[CommandExecutor] 프레임 처리 오류: {e}")
            # 프레임 처리 오류는 무시하고 계속 진행
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="",
                data={"mode": "footstep_frame_error", "error": str(e)},
                actions=[]
            )

    # ===== 통합 Step Measurement 메서드들 - Single Source of Truth =====
    
    def start_step_measurement(self, session_id: Optional[str] = None) -> bool:
        """보폭 측정 시작 - 모든 컴포넌트에서 사용하는 단일 진입점"""
        try:
            if self.measurement_active:
                logger.warning("이미 측정이 활성화되어 있습니다")
                return False
            
            # 레거시 시스템 정리
            if self.step_tracker:
                logger.debug("레거시 step_tracker 정리")
                self.step_tracker = None
            
            # 레거시 계산기 준비 (호환성)
            logger.info("레거시 시스템 준비 완료")
            
            
            self.fastdepth_processor = get_fastdepth_processor()
            
            # 상태 설정
            self.measurement_active = True
            self.measurement_status = MeasurementStatus.ACTIVE
            self.measurement_start_time = time.time()
            self.frame_count = 0
            self.session_id = session_id or f"session_{int(time.time())}"
            
            # 측정 데이터 초기화
            self.processed_frames.clear()
            self.total_distance_traveled = 0.0
            self.last_position = None
            self.step_tracker = None  # 레거시 필드 호환성 유지
            
            return True
            
        except Exception as e:
            logger.error(f"보폭 측정 시작 실패: {e}")
            self.measurement_active = False
            self.measurement_status = MeasurementStatus.INACTIVE
            return False
    
    def stop_step_measurement(self) -> Optional[StepResult]:
        """보폭 측정 중지 - 최종 결과 반환 (새로운 IMU 시스템 사용)"""
        try:
            if not self.measurement_active:
                logger.warning("활성화된 측정이 없습니다")
                return None
            
            # 레거시 fallback
            logger.warning("IMU 시스템 없음 - 기본값 사용")
            final_result = StepResult(
                step_length_cm=self.user_settings.get("step_length", 65.0),
                confidence=0.6,
                step_count=1,
                tracking_quality=AccuracyConverter.confidence_to_quality(0.6),
                accuracy_level=AccuracyConverter.confidence_to_korean_level(0.6),
                measurement_method=StepMeasurementMethod.DISTANCE_BASED,
                consistency_score=0.6,
                processing_time_ms=500.0,
                source_data={
                    "method": "fallback_measurement"
                }
            )
            
            # 상태 리셋
            self.measurement_active = False
            self.measurement_status = MeasurementStatus.COMPLETED
            
            # 결과가 유효한지 확인
            if final_result is None or final_result.step_count == 0:
                self.measurement_status = MeasurementStatus.CANCELLED
                logger.warning("측정된 보폭이 없음")
                return None
            
            # 사용자 설정에 보폭 저장
            self.user_settings["step_length"] = final_result.step_length_cm
            
            # CRITICAL: 측정 완료 후 step_tracker 완전 정리
            logger.info("측정 완료 - step_tracker 및 관련 데이터 정리 중...")
            if self.step_tracker:
                self.step_tracker = None
            
            # 측정 관련 데이터 완전 정리
            self.measurement_start_time = None
            self.frame_count = 0
            self.session_id = None
            self.processed_frames.clear()
            self.total_distance_traveled = 0.0
            self.last_position = None
            
            return final_result
            
        except Exception as e:
            logger.error(f"보폭 측정 중지 실패: {e}")
            self.measurement_active = False
            self.measurement_status = MeasurementStatus.CANCELLED
            return None
    
    def cancel_step_measurement(self) -> bool:
        """보폭 측정 취소"""
        try:
            if not self.measurement_active:
                return True
            
            # 상태 리셋
            self.measurement_active = False
            self.measurement_status = MeasurementStatus.CANCELLED
            self.measurement_start_time = None
            self.frame_count = 0
            self.session_id = None
            
            if self.step_tracker:
                self.step_tracker = None
            
            # UnifiedStepCalculator 데이터 리셋
            self.processed_frames.clear()
            self.total_distance_traveled = 0.0
            self.last_position = None
            
            return True
            
        except Exception as e:
            logger.error(f"보폭 측정 취소 실패: {e}")
            return False
    
    async def process_step_frame(self, frame_data: Dict[str, Any]) -> Optional[StepResult]:
        """FastDepth 프레임 처리 - 통합 진입점"""
        try:
            if not self.measurement_active or self.step_tracker is None:
                return None
            
            # 새로운 IMU 시스템 사용 (프레임 처리)
            if hasattr(self, 'fastdepth_processor') and self.fastdepth_processor:
                # 프레임 데이터에서 이미지가 있다면 새로운 시스템으로 처리
                if frame_data.get("cv_image") is not None:
                    try:
                        # 새로운 통합 측정 수행
                        measurement_result = await self.fastdepth_processor.process_frame_for_measurement(
                            cv_image=frame_data["cv_image"],
                            user_id=f"command_executor_{self.session_id}"
                        )
                        
                        if measurement_result:
                            # 보폭이 측정되면 사용자 설정 업데이트
                            self.user_settings["step_length"] = measurement_result.step_length_cm
                            logger.info(f"새로운 보폭 측정: {measurement_result.step_length_cm}cm")
                        
                    except Exception as e:
                        logger.error(f"새로운 시스템 프레임 처리 오류: {e}")
                
            # 레거시 호환성 로깅
            logger.debug("프레임 처리 완료 (새로운 IMU 시스템 사용)")
            
            self.frame_count += 1
            
            # 프레임 데이터를 UnifiedStepCalculator용으로 저장
            self._collect_frame_data_for_calculation(frame_data)
            
            # 현재 보폭 결과 반환 (CommandExecutor 상태를 전달)
            step_result = self.step_tracker.get_current_step_result()
            
            if step_result.step_count > 0:
                return step_result
            
            return None
                
        except Exception as e:
            logger.error(f"프레임 처리 오류: {e}")
            return None
    
    def _collect_frame_data_for_calculation(self, frame_data: Dict[str, Any]):
        """UnifiedStepCalculator를 위한 프레임 데이터 수집"""
        try:
            # 프레임 데이터 저장 (최근 100개만 유지)
            self.processed_frames.append(frame_data.copy())
            if len(self.processed_frames) > 100:
                self.processed_frames = self.processed_frames[-100:]
            
            # 거리 계산을 위한 위치 추적
            current_position = self._extract_best_foot_position(frame_data)
            if current_position and self.last_position:
                # 이전 위치와의 거리 계산 (3D 유클리드 거리)
                distance = np.sqrt(
                    (current_position[0] - self.last_position[0])**2 +
                    (current_position[1] - self.last_position[1])**2 +
                    (current_position[2] - self.last_position[2])**2
                )
                
                # 유효한 이동 거리인지 확인 (노이즈 필터링)
                if 0.01 <= distance <= 0.5:  # 1cm ~ 50cm 사이의 이동만 유효
                    self.total_distance_traveled += distance
            
            if current_position:
                self.last_position = current_position
                
        except Exception as e:
            logger.warning(f"프레임 데이터 수집 중 오류: {e}")
    
    def _extract_best_foot_position(self, frame_data: Dict[str, Any]) -> Optional[tuple]:
        """프레임에서 가장 신뢰할 수 있는 발 위치 추출"""
        try:
            left_foot = frame_data.get("left_foot")
            right_foot = frame_data.get("right_foot")
            
            if not left_foot and not right_foot:
                return None
            
            # 신뢰도가 높은 발 선택
            if left_foot and right_foot:
                left_conf = left_foot.get("confidence", 0)
                right_conf = right_foot.get("confidence", 0)
                best_foot = left_foot if left_conf >= right_conf else right_foot
            else:
                best_foot = left_foot or right_foot
            
            if best_foot and best_foot.get("confidence", 0) >= 0.3:
                return (best_foot["x"], best_foot["y"], best_foot["z"])
            
            return None
            
        except Exception as e:
            logger.warning(f"발 위치 추출 중 오류: {e}")
            return None
    
    def _calculate_final_step_result(
        self, 
        kalman_result: StepResult, 
        performance_metrics: Dict[str, Any]
    ) -> Optional[StepResult]:
        """UnifiedStepCalculator를 사용한 최종 보폭 계산"""
        try:
            # Kalman 결과가 충분히 신뢰할 수 있으면 그대로 사용
            if kalman_result.confidence >= 0.7 and kalman_result.step_count >= 5:
                logger.info(f"Kalman 결과 사용: 신뢰도 {kalman_result.confidence:.2f}")
                return kalman_result
            
            # UnifiedStepCalculator로 향상된 계산 시도
            logger.info(f"UnifiedStepCalculator로 향상된 계산 시도 (Kalman 신뢰도: {kalman_result.confidence:.2f})")
            
            # 1순위: 프레임 시퀀스 기반 계산
            if len(self.processed_frames) >= 10:
                try:
                    calculation_input = StepCalculationInput(
                        distance_meters=self.total_distance_traveled,
                        step_count=len(self.processed_frames),
                        confidence=kalman_result.confidence,
                        timestamp=time.time()
                    )
                    
                    logger.info("프레임 기반 계산")
                        
                except Exception as e:
                    logger.warning(f"프레임 기반 계산 실패: {e}")
            
            # 2순위: 거리 및 스텝 수 기반 계산
            if self.total_distance_traveled > 0 and kalman_result.step_count > 0:
                try:
                    calculation_input = StepCalculationInput(
                        distance_meters=self.total_distance_traveled,
                        step_count=kalman_result.step_count,
                        confidence=kalman_result.confidence,
                        timestamp=time.time()
                    )
                    
                    # 새로운 IMU 통합 시스템으로 거리 기반 계산 통합됨
                    logger.info(f"거리 기반 계산은 새로운 IMU 융합 시스템으로 통합됨 (거리: {self.total_distance_traveled:.2f}m)")
                    # 거리 기반 계산도 새로운 시스템으로 통합됨
                            
                except Exception as e:
                    logger.warning(f"거리 기반 계산 실패: {e}")
            
            # 3순위: Kalman 결과 그대로 사용 (최소한의 데이터라도 있으면)
            if kalman_result.step_count > 0:
                logger.info(f"Kalman 결과 사용 (대안 없음): {kalman_result.step_length_cm}cm")
                return kalman_result
            
            # 모든 계산 실패
            logger.warning("모든 보폭 계산 방법 실패")
            return None
            
        except Exception as e:
            logger.error(f"최종 보폭 계산 실패: {e}")
            # 응급 상황에서는 Kalman 결과라도 반환
            if kalman_result and kalman_result.step_count > 0:
                return kalman_result
            return None
    
    def _is_result_valid(self, result: StepResult) -> bool:
        """계산 결과 유효성 검증"""
        return (
            result is not None and
            30 <= result.step_length_cm <= 150 and  # 합리적인 보폭 범위
            result.step_count > 0 and
            result.confidence >= 0.1  # 최소 신뢰도
        )
    
    def _compare_and_select_result(self, kalman_result: StepResult, distance_result: StepResult) -> bool:
        """두 결과를 비교하여 거리 기반 결과 선택 여부 결정"""
        # 신뢰도 차이
        confidence_diff = distance_result.confidence - kalman_result.confidence
        
        # 보폭 차이 (상대적)
        step_diff_ratio = abs(distance_result.step_length_cm - kalman_result.step_length_cm) / kalman_result.step_length_cm
        
        # 거리 기반 결과 선택 조건:
        # 1. 신뢰도가 0.2 이상 높거나
        # 2. 보폭 차이가 20% 이내이고 신뢰도가 더 높은 경우
        return (
            confidence_diff >= 0.2 or
            (step_diff_ratio <= 0.2 and confidence_diff > 0)
        )

    def get_step_measurement_status(self) -> RealTimeMeasurementStatus:
        """현재 보폭 측정 상태 반환 - 통합 상태 API"""
        return SchemaConverter.create_measurement_status_from_executor(self)
    
    # ===== 기존 호환성 메서드들 =====
    
    def is_measurement_active(self) -> bool:
        """보폭 측정 활성 상태 확인 (기존 호환성)"""
        return self.measurement_active
    
    def is_realtime_measurement_active(self) -> bool:
        """실시간 측정 활성 상태 확인 (기존 호환성)"""
        return self.measurement_active
    
    def get_measurement_progress(self) -> Dict[str, Any]:
        """측정 진행 상황 반환 (기존 호환성)"""
        if not self.measurement_active:
            return {"active": False}
        
        return {
            "active": True,
            "start_time": self.measurement_start_time,
            "duration": time.time() - self.measurement_start_time if self.measurement_start_time else 0,
            "frame_count": self.frame_count,
            "tracker_status": {
                "current_step": self.step_tracker.get_current_step_result() if self.step_tracker else None,
                "performance": (
                    self.step_tracker.get_performance_metrics(
                        frame_count=self.frame_count,
                        start_time=self.measurement_start_time or time.time()
                    ) if self.step_tracker else None
                )
            }
        }

    async def _setup_voice_gender(self, command_text: str) -> CommandExecutionResult:
        """음성 성별 설정"""
        if "여성" in command_text:
            self.user_settings["voice_gender"] = "F"
            gender_kr = "여성"
        elif "남성" in command_text:
            self.user_settings["voice_gender"] = "M"
            gender_kr = "남성"
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="여성 또는 남성 목소리를 선택해주세요.",
                data={"setup_step": "voice_gender"},
                actions=["tts_announce"]
            )

        self.current_setup_step = SetupStep.VOICE_SPEED

        return CommandExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message=f"{gender_kr} 목소리를 선택했습니다. 이제 음성 속도를 설정하겠습니다. '느리게', '보통', '빠르게' 중 하나를 말씀해주세요.",
            data={
                "setup_step": "voice_speed",
                "voice_gender": self.user_settings["voice_gender"],
                "progress": "4/6"
            },
            actions=["voice_gender_complete", "tts_announce", "setup_progress_show"]
        )

    async def _setup_voice_speed(self, command_text: str) -> CommandExecutionResult:
        """음성 속도 설정"""
        if "느리게" in command_text or "천천히" in command_text:
            speed = convert_to_google_tts_speed(0.7, 'multiplier')
            speed_kr = "느리게"
        elif "빠르게" in command_text:
            speed = convert_to_google_tts_speed(1.3, 'multiplier')
            speed_kr = "빠르게"
        elif "보통" in command_text or "기본" in command_text:
            speed = convert_to_google_tts_speed(1.0, 'multiplier')
            speed_kr = "보통"
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="음성 속도를 선택해주세요. '느리게', '빠르게', 또는 '보통'이라고 말씀해주세요.",
                data={"setup_step": "voice_speed"},
                actions=["tts_announce"]
            )

        self.user_settings["voice_speed"] = speed
        self.current_setup_step = SetupStep.CAREGIVER_INFO

        return CommandExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message=f"{speed_kr} 속도로 설정되었습니다. 이제 보호자 정보를 입력하겠습니다. 보호자의 이름을 말씀해주세요.",
            data={
                "setup_step": "caregiver_info",
                "voice_speed": speed,
                "progress": "5/6"
            },
            actions=["voice_speed_complete", "tts_announce", "setup_progress_show"]
        )
        
    async def _setup_caregiver_info(self, command_text: str) -> CommandExecutionResult:
        """보호자 정보 설정"""
        if not self.user_settings["caregiver_name"]:
            # 이름 입력 단계
            caregiver_name = command_text.strip()
            self.user_settings["caregiver_name"] = caregiver_name
            
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message=f"보호자 이름을 '{caregiver_name}'으로 저장했습니다. 이제 전화번호를 말씀해주세요.",
                data={
                    "setup_step": "caregiver_info_phone_number",
                    "caregiver_name": caregiver_name
                },
                actions=["tts_announce"]
            )
        else:
            # 전화번호 입력 단계
            phone_number = command_text.strip()
            self.user_settings["caregiver_phone"] = phone_number
            self.current_setup_step = SetupStep.MODE_SELECTION
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="보호자 정보가 저장되었습니다. 마지막으로 주로 사용할 모드를 선택해주세요. '카메라 모드' 또는 '길찾기 모드' 중 하나를 말씀해주세요.",
                data={
                    "setup_step": "mode_selection",
                    "caregiver_name": self.user_settings["caregiver_name"],
                    "caregiver_phone": phone_number,
                    "progress": "6/6"
                },
                actions=["caregiver_info_saved","tts_announce", "setup_progress_show"]
            )

    async def _setup_mode_selection(self, intent: str) -> CommandExecutionResult:
        """모드 선택"""
        if intent == "CAMERA":
            self.user_settings["preferred_mode"] = "camera"
            mode_kr = "카메라 모드"
            self.current_mode = AppMode.CAMERA
        elif intent == "NAVIGATION":
            self.user_settings["preferred_mode"] = "navigation"
            mode_kr = "길찾기 모드"
            self.current_mode = AppMode.NAVIGATION
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="'카메라 모드' 또는 '길찾기 모드' 중 하나를 선택해주세요.",
                data={"setup_step": "mode_selection"},
                actions=["tts_announce"]
            )
        
        # 중요: 설정 완료 상태로 변경
        self.current_setup_step = SetupStep.COMPLETE
        
        print(f"[DEBUG] 설정 완료 - 모드: {self.current_mode.value}, 단계: {self.current_setup_step.value}")
        
        return CommandExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message=f"설정이 완료되었습니다! {mode_kr}로 시작합니다. {self.user_settings['user_name']}님, 음성 명령을 말씀해주세요.",
            data={
                "setup_complete": True,
                "current_mode": self.current_mode.value,
                "user_settings": self.user_settings
            },
            actions=["setup_complete", "mode_activate", "tts_announce"]
        )

    async def _setup_complete(self) -> CommandExecutionResult:
        """설정 완료"""
        # 온보딩 완료 - 모드 변경
        self.current_mode = AppMode.NORMAL
        self.current_setup_step = SetupStep.COMPLETE
        
        return CommandExecutionResult(
            status=ExecutionStatus.SUCCESS,
            message="모든 설정이 완료되었습니다!",
            data={
                "setup_complete": True,
                "user_settings": self.user_settings
            },
            actions=["setup_complete"]
        )

    async def _handle_normal_mode(self, intent: str, entities: Dict[str, Any]) -> CommandExecutionResult:
        """일반 모드 명령 처리"""
        execution_map = {
            "CAMERA": self._execute_camera,
            "NAVIGATION": self._execute_navigation,
            "EMERGENCY_CALL": self._execute_emergency_call,
            "SETTINGS": self._execute_settings,
            "HELP": self._execute_help,
            "STOP_LISTENING": self._execute_stop_listening,
            "START_LISTENING": self._execute_start_listening,
            "DESCRIBE_SCENE": self._execute_describe_scene,
            'FOOTSTEP_MEASUREMENT_START': self._execute_footstep_measurement_start,
            'FOOTSTEP_MEASUREMENT_BEGIN': self._execute_footstep_measurement_begin,
            'FOOTSTEP_MEASUREMENT_COMPLETE': self._execute_footstep_measurement_complete,
            'FOOTSTEP_MEASUREMENT_CANCEL': self._execute_footstep_measurement_cancel,
        }

        if intent in execution_map:
            return await execution_map[intent](entities)
        else:
            return self._execute_unknown(intent, entities)

    async def _execute_camera(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """카메라 모드 실행"""
        try:
            self.current_mode = AppMode.CAMERA
            
            # 카메라 초기화 시뮬레이션
            await asyncio.sleep(0.5)
            
            actions = [
                "camera_module_init",
                "preview_start",
                "focus_enable",
                "capture_ready"
            ]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="카메라 모드가 활성화되었습니다. 화면을 터치하여 주변을 감지해보세요.",
                data={
                    "mode": "camera",
                    "preview_enabled": True,
                    "auto_focus": True,
                    "flash_mode": "auto",
                    "user_settings": self.user_settings
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"카메라 모드 활성화 실패: {str(e)}"
            )
    
    async def _execute_navigation(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """네비게이션 모드 실행"""
        try:
            self.current_mode = AppMode.NAVIGATION
            destination = entities.get('destination', '목적지')
            
            # GPS 및 네비게이션 초기화 시뮬레이션
            await asyncio.sleep(1.0)
            
            actions = [
                "gps_enable",
                "location_acquire",
                "route_calculate",
                "navigation_start"
            ]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"{destination}까지의 길찾기를 시작합니다. GPS를 확인하고 있습니다.",
                data={
                    "mode": "navigation",
                    "destination": destination,
                    "gps_enabled": True,
                    "voice_guidance": True,
                    "step_length": self.user_settings["step_length"],
                    "user_settings": self.user_settings
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"네비게이션 시작 실패: {str(e)}"
            )
    
    async def _execute_emergency_call(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """긴급 전화 실행"""
        try:
            # 긴급 호출 시뮬레이션
            await asyncio.sleep(0.3)

            caregiver_name = self.user_settings.get("caregiver_name", "보호자")
            caregiver_phone = self.user_settings.get("caregiver_phone", "")
            
            actions = [
                "emergency_alert_show",
                "contact_retrieve",
                "call_initiate",
                "location_share"
            ]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"긴급 상황이 감지되었습니다. {caregiver_name}님에게 연락 중입니다.",
                data={
                    "emergency_mode": True,
                    "contact_type": "caregiver",
                    "location_sharing": True,
                    "auto_message": True,
                    "caregiver_name": caregiver_name,
                    "caregiver_phone": caregiver_phone
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"긴급 전화 실행 실패: {str(e)}"
            )
    
    async def _execute_settings(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """설정 메뉴 실행"""
        try:
            self.current_mode = AppMode.SETTINGS
            
            actions = [
                "settings_menu_open",
                "accessibility_options_load"
            ]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="설정 메뉴를 열었습니다. 음성 안내를 듣고 설정을 변경하세요.",
                data={
                    "mode": "settings",
                    "available_options": [
                        "보폭 재설정",
                        "음성 설정 변경", 
                        "보호자 정보 수정",
                    ],
                    "user_settings": self.user_settings
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"설정 메뉴 열기 실패: {str(e)}"
            )
    
    async def _execute_help(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """도움말 실행"""
        try:
            help_commands = [
                "카메라 - 카메라 모드 실행",
                "길찾기 - 네비게이션 시작", 
                "보호자 호출 - 긴급 전화",
                "설정 - 설정 메뉴 열기",
                "주변 안내 - 주변 환경 설명",
            ]
            
            actions = ["help_menu_display", "tts_help_start"]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="사용 가능한 음성 명령어를 안내해드립니다.",
                data={
                    "help_commands": help_commands,
                    "current_mode": self.current_mode.value,
                    "listening_status": self.is_listening
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"도움말 표시 실패: {str(e)}"
            )
    
    async def _execute_stop_listening(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """음성 인식 중단"""
        try:
            self.is_listening = False
            
            actions = ["voice_recognition_stop", "mic_disable"]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="음성 인식을 중단했습니다. 다시 시작하려면 화면을 터치하세요.",
                data={
                    "listening": False,
                    "mic_enabled": False
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"음성 인식 중단 실패: {str(e)}"
            )
    
    async def _execute_start_listening(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """음성 인식 시작"""
        try:
            self.is_listening = True
            
            actions = ["voice_recognition_start", "mic_enable"]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="음성 인식을 시작했습니다. 명령어를 말씀해주세요.",
                data={
                    "listening": True,
                    "mic_enabled": True
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"음성 인식 시작 실패: {str(e)}"
            )
    
    async def _execute_describe_scene(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """주변 환경 설명"""
        try:
            self.current_mode = AppMode.SCENE_DESCRIPTION
            
            # AI 비전 분석 시뮬레이션
            await asyncio.sleep(2.0)
            
            actions = [
                "camera_capture",
                "ai_vision_analyze", 
                "scene_description_generate",
                "tts_announce"
            ]
            
            # 샘플 설명 (실제로는 AI 비전 API 결과)
            description = "앞쪽에 보도가 있고, 오른쪽으로 상점들이 보입니다. 직진 방향에 횡단보도가 있습니다."
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"주변 환경을 분석했습니다: {description}",
                data={
                    "mode": "scene_description",
                    "description": description,
                    "objects_detected": ["보도", "상점", "횡단보도"],
                    "safety_level": "안전"
                },
                actions=actions
            )
            
        except Exception as e:
            return CommandExecutionResult(
                status=ExecutionStatus.FAILED,
                message=f"주변 환경 분석 실패: {str(e)}"
            )
    
    def _execute_unknown(self, intent: str, entities: Dict[str, Any]) -> CommandExecutionResult:
        """알 수 없는 명령 처리"""
        return CommandExecutionResult(
            status=ExecutionStatus.NOT_SUPPORTED,
            message=f"'{intent}' 명령은 지원되지 않습니다. '도움말'이라고 말씀하시면 사용 가능한 명령어를 안내해드립니다.",
            data={"unsupported_intent": intent}
        )
    
    def _save_execution_history(
        self, 
        intent: str, 
        entities: Dict[str, Any], 
        result: CommandExecutionResult
    ):
        """실행 기록 저장"""
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "intent": intent,
            "entities": entities,
            "status": result.status.value,
            "message": result.message,
            "actions": result.actions,
            "mode": self.current_mode.value,
            "setup_step": self.current_setup_step.value if self.current_mode == AppMode.SETUP else None,
        }
        
        self.execution_history.append(history_entry)
        
        # 최근 100개만 보관
        if len(self.execution_history) > 100:
            self.execution_history = self.execution_history[-100:]
    
    def get_current_status(self) -> Dict[str, Any]:
        """현재 상태 반환 - 데이터베이스 기반 온보딩 완료 판단"""
        # 데이터베이스에서 실제 설정 완료 여부를 확인
        setup_complete = self._check_onboarding_complete()
        
        print(f"[DEBUG] 상태 확인 - 모드: {self.current_mode.value}, 단계: {self.current_setup_step.value}, 완료: {setup_complete}")
        
        return {
            "is_listening": self.is_listening,
            "current_mode": self.current_mode.value,
            "setup_step": self.current_setup_step.value if self.current_mode == AppMode.SETUP else None,
            "user_settings": self.user_settings,
            "setup_complete": setup_complete,
            "last_execution": self.execution_history[-1] if self.execution_history else None,
            "total_commands": len(self.execution_history),
            "measurement_active": self.measurement_active,
            "measurement_progress": self.get_measurement_progress()
        }
    
    def _check_onboarding_complete(self) -> bool:
        """데이터베이스를 확인하여 온보딩 완료 여부 판단"""
        if not self.user_id:
            return False
            
        try:
            with get_sync_session() as session:
                # 사용자 정보 조회
                user = session.query(User).filter(User.user_id == self.user_id).first()
                if not user:
                    return False
                
                # 관련 설정 조회
                user_setting = session.query(UserSetting).filter(UserSetting.user_id == self.user_id).first()
                
                # 온보딩 완료 여부를 데이터 존재 여부로 판단
                has_voice_setting = user_setting and user_setting.voice_id is not None
                has_caregiver_info = user_setting and user_setting.caregiver_id is not None  
                has_footstep_info = user_setting and user_setting.step_id is not None
                has_user_name = user.user_name is not None and len(user.user_name.strip()) > 0
                
                return all([has_voice_setting, has_caregiver_info, has_footstep_info, has_user_name])
                
        except Exception as e:
            print(f"[ERROR] 온보딩 상태 확인 실패: {e}")
            return False
    
    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """실행 기록 반환"""
        return self.execution_history[-limit:] if self.execution_history else []

    def reset_setup(self):
        """설정 초기화 (재설정용)"""
        self.current_mode = AppMode.SETUP
        self.current_setup_step = SetupStep.START
        self.user_settings = {
            "user_name": None,
            "step_length": None,
            "voice_gender": "F",
            "voice_speed": 1.0,
            "caregiver_name": None,
            "caregiver_phone": None,
        }
         # 측정 상태도 리셋
        self.measurement_active = False
        self.measurement_start_time = None
        self.frame_count = 0
        if self.step_tracker:
            self.step_tracker = None
        
        # UnifiedStepCalculator 데이터도 리셋
        self.processed_frames.clear()
        self.total_distance_traveled = 0.0
        self.last_position = Noner()
        self.total_distance_traveled = 0.0
        self.last_position = None