"""통합 상태 관리 서비스

이 모듈은 시스템의 모든 상태 조회 기능을 중앙화합니다:
- 실행 상태 조회
- 측정 상태 조회  
- 전체 시스템 상태 조회
- 통합 응답 형식 및 오류 처리
- 일관된 상태 데이터 구조
"""

import logging
from typing import Dict, Any, Optional, Union
from datetime import datetime
from dataclasses import dataclass

from models.common_models import (
    MeasurementStatusResponse, 
    SystemStatusResponse,
    MeasurementProgress,
    AppMode,
    UserSettings,
    RealTimeMeasurementStatus,
    MeasurementStatus
)
from models.common_models import SystemStatusResponse as ExecutionStatusResponse
from services.singleton import service_manager

logger = logging.getLogger(__name__)

@dataclass
class StatusServiceResult:
    """상태 서비스 결과"""
    success: bool
    data: Optional[Union[Dict[str, Any], object]] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class StatusService:
    """통합 상태 관리 서비스 클래스"""
    
    def __init__(self):
        self.command_executor = service_manager.get_command_executor()
        self.status_cache = {}
        self.cache_timeout = 1.0  # 1초 캐시 타임아웃
        
    def get_execution_status(self) -> StatusServiceResult:
        """
        현재 시스템 실행 상태 조회
        
        Returns:
            StatusServiceResult: 실행 상태 결과
        """
        try:
            logger.debug("[StatusService] 실행 상태 조회 시작")
            
            # CommandExecutor에서 상태 조회
            status_data = self.command_executor.get_current_status()
            
            # 필수 필드 검증
            required_fields = ["is_listening", "current_mode", "last_execution", "total_commands"]
            missing_fields = [field for field in required_fields if field not in status_data]
            
            if missing_fields:
                warning_msg = f"일부 필드가 누락됨: {missing_fields}"
                logger.warning(f"[StatusService] {warning_msg}")
            
            # SystemStatusResponse 생성 (모든 필수 필드 포함)
            
            execution_status = SystemStatusResponse(
                current_mode=AppMode.NORMAL,  # 기본 모드
                setup_complete=True,  # 기본값
                is_listening=status_data.get("is_listening", True),
                measurement_status=RealTimeMeasurementStatus(
                    measurement_active=False,
                    measurement_status=MeasurementStatus.INACTIVE,
                    measurement_type=None,
                    progress=MeasurementProgress(
                        frame_count=0,
                        elapsed_time=0.0,
                        fps=0.0,
                        step_count=0,
                        current_step_length_cm=None
                    ),
                    current_result=None,
                    session_id=None,
                    start_time=None
                ),
                user_settings=UserSettings(
                    user_name="기본 사용자",
                    step_length_cm=75.0,
                    voice_gender="female",
                    voice_speed=1.0
                ),
                last_execution=status_data.get("last_execution"),
                total_commands=status_data.get("total_commands", 0)
            )
            
            logger.debug(f"[StatusService] 실행 상태 조회 완료: {execution_status.current_mode}")
            
            return StatusServiceResult(
                success=True,
                data=execution_status,
                warning=f"일부 필드 누락: {missing_fields}" if missing_fields else None
            )
            
        except Exception as e:
            error_msg = f"실행 상태 조회 실패: {str(e)}"
            logger.error(f"[StatusService] {error_msg}")
            return StatusServiceResult(
                success=False,
                error=error_msg
            )
    
    def get_measurement_status(self) -> StatusServiceResult:
        """
        현재 보폭 측정 상태 조회
        
        Returns:
            StatusServiceResult: 측정 상태 결과
        """
        try:
            logger.debug("[StatusService] 측정 상태 조회 시작")
            
            # 통합된 상태/진행률 조회 메서드 사용
            status_data, progress_data = self._get_unified_status_data()
            
            # 측정 상태 구성
            measurement_status = self._build_measurement_status(status_data, progress_data)
            
            logger.debug(f"[StatusService] 측정 상태 조회 완료: active={measurement_status.measurement_active}")
            
            return StatusServiceResult(
                success=True,
                data=measurement_status
            )
            
        except Exception as e:
            error_msg = f"측정 상태 조회 실패: {str(e)}"
            logger.error(f"[StatusService] {error_msg}")
            return StatusServiceResult(
                success=False,
                error=error_msg
            )
    
    def get_system_status(self) -> StatusServiceResult:
        """
        전체 시스템 상태 조회
        
        Returns:
            StatusServiceResult: 시스템 상태 결과
        """
        try:
            logger.debug("[StatusService] 시스템 상태 조회 시작")
            
            # 통합된 상태/진행률 조회 메서드 사용
            status_data, progress_data = self._get_unified_status_data()
            
            # 측정 상태 정보 구성
            measurement_status = self._build_measurement_status(status_data, progress_data)
            
            # 사용자 설정 안전하게 처리
            user_settings = self._build_user_settings(status_data)
            
            # 전체 시스템 상태 구성
            system_status = SystemStatusResponse(
                current_mode=AppMode(status_data.get("current_mode", "normal")),
                setup_complete=status_data.get("setup_complete", False),
                is_listening=status_data.get("is_listening", True),
                measurement_status=measurement_status,
                user_settings=user_settings,
                last_execution=status_data.get("last_execution"),
                total_commands=status_data.get("total_commands", 0)
            )
            
            logger.debug(f"[StatusService] 시스템 상태 조회 완료: mode={system_status.current_mode.value}")
            
            return StatusServiceResult(
                success=True,
                data=system_status
            )
            
        except Exception as e:
            error_msg = f"시스템 상태 조회 실패: {str(e)}"
            logger.error(f"[StatusService] {error_msg}")
            return StatusServiceResult(
                success=False,
                error=error_msg
            )
    
    def get_cached_status(self, status_type: str) -> Optional[StatusServiceResult]:
        """
        캐시된 상태 조회
        
        Args:
            status_type: 상태 타입 ("execution", "measurement", "system")
            
        Returns:
            캐시된 상태 또는 None
        """
        if status_type not in self.status_cache:
            return None
        
        cached_data = self.status_cache[status_type]
        cache_age = (datetime.now() - cached_data["timestamp"]).total_seconds()
        
        if cache_age > self.cache_timeout:
            del self.status_cache[status_type]
            return None
        
        logger.debug(f"[StatusService] 캐시된 {status_type} 상태 반환 (age: {cache_age:.2f}s)")
        return cached_data["result"]
    
    def set_cached_status(self, status_type: str, result: StatusServiceResult):
        """상태를 캐시에 저장"""
        self.status_cache[status_type] = {
            "result": result,
            "timestamp": datetime.now()
        }
    
    def get_execution_status_cached(self) -> StatusServiceResult:
        """캐시 지원 실행 상태 조회"""
        cached = self.get_cached_status("execution")
        if cached:
            return cached
        
        result = self.get_execution_status()
        if result.success:
            self.set_cached_status("execution", result)
        
        return result
    
    def get_measurement_status_cached(self) -> StatusServiceResult:
        """캐시 지원 측정 상태 조회"""
        cached = self.get_cached_status("measurement")
        if cached:
            return cached
        
        result = self.get_measurement_status()
        if result.success:
            self.set_cached_status("measurement", result)
        
        return result
    
    def get_system_status_cached(self) -> StatusServiceResult:
        """캐시 지원 시스템 상태 조회"""
        cached = self.get_cached_status("system")
        if cached:
            return cached
        
        result = self.get_system_status()
        if result.success:
            self.set_cached_status("system", result)
        
        return result
    
    def get_all_statuses(self) -> Dict[str, StatusServiceResult]:
        """
        모든 상태를 한 번에 조회
        
        Returns:
            모든 상태 딕셔너리
        """
        try:
            logger.debug("[StatusService] 전체 상태 조회 시작")
            
            results = {
                "execution": self.get_execution_status(),
                "measurement": self.get_measurement_status(),
                "system": self.get_system_status()
            }
            
            # 성공한 조회 수 계산
            successful = sum(1 for result in results.values() if result.success)
            logger.info(f"[StatusService] 전체 상태 조회 완료: {successful}/3 성공")
            
            return results
            
        except Exception as e:
            logger.error(f"[StatusService] 전체 상태 조회 실패: {e}")
            return {
                "execution": StatusServiceResult(False, error=str(e)),
                "measurement": StatusServiceResult(False, error=str(e)),
                "system": StatusServiceResult(False, error=str(e))
            }
    
    def clear_cache(self):
        """상태 캐시 전체 지우기"""
        cache_size = len(self.status_cache)
        self.status_cache.clear()
        logger.debug(f"[StatusService] 캐시 지워짐: {cache_size}개 항목")
    
    # ===== 통합 헬퍼 메서드들 - 코드 중복 제거 =====
    
    def _get_unified_status_data(self) -> tuple:
        """
        CommandExecutor에서 상태와 진행률 데이터를 한 번에 조회
        
        Returns:
            tuple: (status_data, progress_data)
        """
        status_data = self.command_executor.get_current_status()
        progress_data = self.command_executor.get_measurement_progress()
        return status_data, progress_data
    
    def _build_measurement_status(self, status_data: Dict[str, Any], progress_data: Dict[str, Any]) -> MeasurementStatusResponse:
        """
        측정 상태 응답 객체 구성 - 중복 제거된 통합 메서드
        
        Args:
            status_data: CommandExecutor 상태 데이터
            progress_data: CommandExecutor 진행률 데이터
            
        Returns:
            MeasurementStatusResponse: 구성된 측정 상태
        """
        measurement_status = MeasurementStatusResponse(
            measurement_active=status_data.get("measurement_active", False),
            measurement_type="kalman_filter" if status_data.get("measurement_active") else None,
            progress=MeasurementProgress(
                frame_count=progress_data.get("frame_count", 0),
                elapsed_time=progress_data.get("elapsed_time", 0.0),
                fps=progress_data.get("fps", 0.0),
                step_count=progress_data.get("step_count", 0)
            ),
            current_step=None
        )
        
        # 추적기 상태가 있는 경우 세부 정보 추가
        if (progress_data.get("tracker_status") and 
            progress_data["tracker_status"].get("current_step")):
            step_result = progress_data["tracker_status"]["current_step"]
            measurement_status.current_step = step_result
            logger.debug("[StatusService] 현재 스텝 정보 추가됨")
        
        return measurement_status
    
    def _build_user_settings(self, status_data: Dict[str, Any]) -> UserSettings:
        """
        사용자 설정 객체 안전하게 구성
        
        Args:
            status_data: CommandExecutor 상태 데이터
            
        Returns:
            UserSettings: 구성된 사용자 설정
        """
        user_settings_data = status_data.get("user_settings", {})
        try:
            return UserSettings(**user_settings_data)
        except Exception as settings_error:
            logger.warning(f"[StatusService] 사용자 설정 파싱 오류: {settings_error}")
            return UserSettings()  # 기본값 사용
    
    def get_cache_info(self) -> Dict[str, Any]:
        """캐시 정보 조회"""
        now = datetime.now()
        cache_info = {}
        
        for status_type, cached_data in self.status_cache.items():
            age = (now - cached_data["timestamp"]).total_seconds()
            cache_info[status_type] = {
                "cached": True,
                "age_seconds": age,
                "valid": age <= self.cache_timeout,
                "timestamp": cached_data["timestamp"].isoformat()
            }
        
        return {
            "cache_count": len(self.status_cache),
            "timeout_seconds": self.cache_timeout,
            "entries": cache_info
        }
    
    def validate_status_data(self, status_data: Dict[str, Any]) -> Dict[str, Any]:
        """상태 데이터 유효성 검증"""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "missing_fields": []
        }
        
        # 필수 필드 검증
        required_fields = [
            "is_listening", "current_mode", "setup_complete", 
            "measurement_active", "user_settings"
        ]
        
        for field in required_fields:
            if field not in status_data:
                validation_result["missing_fields"].append(field)
                validation_result["warnings"].append(f"필수 필드 누락: {field}")
        
        # 데이터 타입 검증
        type_checks = {
            "is_listening": bool,
            "setup_complete": bool,
            "measurement_active": bool,
            "total_commands": int
        }
        
        for field, expected_type in type_checks.items():
            if field in status_data and not isinstance(status_data[field], expected_type):
                validation_result["errors"].append(
                    f"필드 타입 불일치: {field} (예상: {expected_type.__name__})"
                )
                validation_result["valid"] = False
        
        return validation_result
    
    def get_status_summary(self) -> Dict[str, Any]:
        """상태 요약 정보 조회"""
        try:
            all_statuses = self.get_all_statuses()
            
            summary = {
                "timestamp": datetime.now().isoformat(),
                "overall_healthy": all(result.success for result in all_statuses.values()),
                "services": {},
                "alerts": []
            }
            
            for service_name, result in all_statuses.items():
                summary["services"][service_name] = {
                    "status": "healthy" if result.success else "error",
                    "error": result.error if not result.success else None,
                    "warning": result.warning
                }
                
                if not result.success:
                    summary["alerts"].append(f"{service_name} 서비스 오류: {result.error}")
                elif result.warning:
                    summary["alerts"].append(f"{service_name} 서비스 경고: {result.warning}")
            
            return summary
            
        except Exception as e:
            logger.error(f"[StatusService] 상태 요약 생성 실패: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "overall_healthy": False,
                "error": str(e),
                "alerts": [f"상태 요약 생성 실패: {str(e)}"]
            }

# 싱글톤 인스턴스
_status_service = None

def get_status_service() -> StatusService:
    """StatusService 싱글톤 인스턴스 반환"""
    global _status_service
    if _status_service is None:
        _status_service = StatusService()
        logger.info("[StatusService] 싱글톤 인스턴스 생성됨")
    return _status_service