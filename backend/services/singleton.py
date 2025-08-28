"""
싱글톤 서비스 관리자
"""

from services.command_executor import CommandExecutor
from services.speech_analyzer import SpeechAnalyzer
from services.speech_service import SpeechService

class ServiceManager:
    """서비스 인스턴스를 싱글톤으로 관리"""
    _instance = None
    _command_executor = None
    _speech_analyzer = None
    _speech_service = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceManager, cls).__new__(cls)
        return cls._instance
    
    def get_command_executor(self) -> CommandExecutor:
        """CommandExecutor 싱글톤 인스턴스 반환"""
        if self._command_executor is None:
            self._command_executor = CommandExecutor()
            print("[DEBUG] CommandExecutor 새 인스턴스 생성")
        return self._command_executor
    
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
