"""
싱글톤 서비스 관리자
"""

from services.command_executor import CommandExecutor
from services.speech_analyzer import SpeechAnalyzer
from services.speech_service import SpeechService

class ServiceManager:
    """서비스 인스턴스를 싱글톤으로 관리"""
    _instance = None
    _command_executors = {}  # 사용자별 CommandExecutor 관리
    _speech_analyzer = None
    _speech_service = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceManager, cls).__new__(cls)
        return cls._instance
    
    def get_command_executor(self, user_id: str = None) -> CommandExecutor:
        """사용자별 CommandExecutor 인스턴스 반환"""
        if user_id is None:
            user_id = "default"
        
        if user_id not in self._command_executors:
            self._command_executors[user_id] = CommandExecutor(user_id=user_id)
            print(f"[DEBUG] CommandExecutor 새 인스턴스 생성 (user_id: {user_id})")
        
        return self._command_executors[user_id]
    
    def get_speech_analyzer(self) -> SpeechAnalyzer:
        """SpeechAnalyzer 싱글톤 인스턴스 반환"""
        if self._speech_analyzer is None:
            self._speech_analyzer = SpeechAnalyzer()
        return self._speech_analyzer
    
    def get_speech_service(self) -> SpeechService:
        """SpeechService 싱글톤 인스턴스 반환"""
        if self._speech_service is None:
            self._speech_service = SpeechService()
        return self._speech_service

# 글로벌 서비스 매니저 인스턴스
service_manager = ServiceManager()
