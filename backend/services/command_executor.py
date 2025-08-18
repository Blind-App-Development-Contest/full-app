import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from models.recognition_schemas import SpeechRecognitionResponse 
from config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class ExecutionStatus(Enum):
    """명령 실행 상태"""
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    NOT_SUPPORTED = "not_supported"

class AppMode(Enum):
    """앱 모드"""
    SETUP = "setup"
    STANDBY = "standby"
    CAMERA = "camera"
    NAVIGATION = "navigation"
    SETTINGS = "settings"
    EMERGENCY_CALL = "emergency_call"
    SCENE_DESCRIPTION = "scene_description"

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
    
    def __init__(self):
        self.is_listening = True
        self.current_mode = AppMode.SETUP
        self.current_setup_step = SetupStep.START
        self.execution_history = []

        # 사용자 설정 정보 (변수명 통일)
        self.user_settings = {
            "user_name": None,
            "step_length": None,
            "voice_gender": "F", 
            "voice_speed": 1.0, # 0.5 ~ 2.0 배속
            "caregiver_name": None,
            "caregiver_phone": None,
            "preferred_mode": None
        }
        
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
        
        logger.info(f"명령 실행 시작: {intent}, 현재 모드: {self.current_mode.value}")
        
        try:
            # 설정 모드인 경우 설정 단계별 처리
            if self.current_mode == AppMode.SETUP:
                result = await self._handle_setup_mode(intent, entities, recognition_result.command_text)
            else:
                # 일반 모드 명령 처리
                result = await self._handle_normal_mode(intent, entities)
            
            # 실행 기록 저장
            self._save_execution_history(intent, entities, result)
            
            logger.info(f"명령 실행 완료: {result.status.value}")
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
            return await self._setup_step_length(command_text)  

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

    async def _setup_step_length(self, command_text: str) -> CommandExecutionResult:
        """보폭 측정"""
        if "보폭" in command_text or "측정" in command_text or "시작" in command_text:
            # 보폭 측정 시뮬레이션
            await asyncio.sleep(3.0)
            
            step_length = 65  # cm (시뮬레이션 값)
            self.user_settings["step_length"] = step_length
            self.current_setup_step = SetupStep.VOICE_GENDER
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"보폭 측정이 완료되었습니다. 평균 보폭은 {step_length}cm입니다. 이제 음성 설정을 진행하겠습니다. 여성 목소리를 원하시면 '여성', 남성 목소리를 원하시면 '남성'이라고 말씀해주세요.",
                data={
                    "setup_step": "voice_gender",
                    "step_length": step_length,
                    "progress": "3/6"
                },
                actions=["step_length_complete", "tts_announce", "setup_progress_show"]
            )
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="'보폭 측정 시작'이라고 말씀해주세요.",
                data={"setup_step": "step_length"},
                actions=["tts_announce"]
            )

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
            speed = 0.7
            speed_kr = "느리게"
        elif "빠르게" in command_text:
            speed = 1.3
            speed_kr = "빠르게"
        elif "보통" in command_text or "기본" in command_text:
            speed = 1.0
            speed_kr = "보통"
        else:
            return CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="음성 속도를 선택해주세요. '느리게', '빠르게', 또는 '보통'이라고 말씀해주세요.",
                data={"setup_step": "voice_speed"},
                actions=["tts_announce"]
            )

        self.user_settings["voice_speed"] = speed  # 변수명 수정
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
        """현재 상태 반환"""
        # 설정 완료 조건: 모드가 SETUP이 아니거나 설정 단계가 COMPLETE인 경우
        setup_complete = (self.current_mode != AppMode.SETUP) or (self.current_setup_step == SetupStep.COMPLETE)
        
        print(f"[DEBUG] 상태 확인 - 모드: {self.current_mode.value}, 단계: {self.current_setup_step.value}, 완료: {setup_complete}")
        
        return {
            "is_listening": self.is_listening,
            "current_mode": self.current_mode.value,
            "setup_step": self.current_setup_step.value if self.current_mode == AppMode.SETUP else None,
            "user_settings": self.user_settings,
            "setup_complete": setup_complete,
            "last_execution": self.execution_history[-1] if self.execution_history else None,
            "total_commands": len(self.execution_history)
        }
    
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
            "preferred_mode": None
        }