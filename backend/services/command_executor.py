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
        self.current_mode = "standby"
        self.execution_history = []
        
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
        
        logger.info(f"명령 실행 시작: {intent}, 엔티티: {entities}")
        
        try:
            # 의도별 실행 함수 매핑
            execution_map = {
                'CAMERA': self._execute_camera,
                'NAVIGATION': self._execute_navigation,
                'EMERGENCY_CALL': self._execute_emergency_call,
                'SETTINGS': self._execute_settings,
                'HELP': self._execute_help,
                'STOP_LISTENING': self._execute_stop_listening,
                'START_LISTENING': self._execute_start_listening,
                'DESCRIBE_SCENE': self._execute_describe_scene,
            }
            
            # 해당 의도의 실행 함수 호출
            if intent in execution_map:
                result = await execution_map[intent](entities)
            else:
                result = self._execute_unknown(intent, entities)
            
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
    
    async def _execute_camera(self, entities: Dict[str, Any]) -> CommandExecutionResult:
        """카메라 모드 실행"""
        try:
            self.current_mode = "camera"
            
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
                message="카메라 모드가 활성화되었습니다. 화면을 터치하여 촬영하세요.",
                data={
                    "mode": "camera",
                    "preview_enabled": True,
                    "auto_focus": True,
                    "flash_mode": "auto"
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
            self.current_mode = "navigation"
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
                    "voice_guidance": True
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
            
            actions = [
                "emergency_alert_show",
                "contact_retrieve",
                "call_initiate",
                "location_share"
            ]
            
            return CommandExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message="긴급 상황이 감지되었습니다. 보호자에게 연락 중입니다.",
                data={
                    "emergency_mode": True,
                    "contact_type": "guardian",
                    "location_sharing": True,
                    "auto_message": True
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
            self.current_mode = "settings"
            
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
                        "음성 인식 설정",
                        "TTS 설정", 
                        "진동 설정",
                        "긴급 연락처 설정",
                    ]
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
                    "current_mode": self.current_mode,
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
            self.current_mode = "scene_description"
            
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
            "actions": result.actions
        }
        
        self.execution_history.append(history_entry)
        
        # 최근 100개만 보관
        if len(self.execution_history) > 100:
            self.execution_history = self.execution_history[-100:]
    
    def get_current_status(self) -> Dict[str, Any]:
        """현재 상태 반환"""
        return {
            "is_listening": self.is_listening,
            "current_mode": self.current_mode,
            "last_execution": self.execution_history[-1] if self.execution_history else None,
            "total_commands": len(self.execution_history)
        }
    
    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """실행 기록 반환"""
        return self.execution_history[-limit:] if self.execution_history else []