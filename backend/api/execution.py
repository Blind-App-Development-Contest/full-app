from fastapi import APIRouter, HTTPException
from models.common_models import (
    SystemStatusResponse,
    ExecutionHistoryResponse
)

router = APIRouter()

# 싱글톤 서비스 인스턴스 사용 (setup endpoints only)
from services.singleton import service_manager
command_executor = service_manager.get_command_executor()

@router.get("", response_model=SystemStatusResponse)
@router.get("/", response_model=SystemStatusResponse)
def get_execution_status():
    """
    현재 시스템 실행 상태 조회 - StatusService 통합
    
    Returns:
        SystemStatusResponse: 시스템 현재 상태
    """
    try:
        from services.status_service import get_status_service
        
        status_service = get_status_service()
        result = status_service.get_execution_status()
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 오류: {str(e)}")

@router.get("/history", response_model=ExecutionHistoryResponse)
def get_commands_history(limit: int = 10):
    """
    명령 실행 기록 조회
    
    Args:
        limit: 조회할 기록 수 (기본값: 10)
        
    Returns:
        ExecutionHistoryResponse: 실행 기록
    """
    try:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=400, detail="limit은 1-100 사이여야 합니다")
        
        history_data = command_executor.get_execution_history(limit)
        total_count = len(command_executor.execution_history)
        
        # Dict를 ExecutionHistoryEntry로 변환
        from models.common_models import ExecutionHistoryEntry, CommandExecutionResponse, ExecutionStatus
        from datetime import datetime
        
        history_entries = []
        for entry in history_data:
            # 기본값 설정
            execution_response = CommandExecutionResponse(
                status=ExecutionStatus.SUCCESS,
                message=entry.get("message", "실행 완료"),
                data=entry.get("data", {}),
                actions=entry.get("actions", []),
                timestamp=datetime.now()
            )
            
            history_entry = ExecutionHistoryEntry(
                command_text=entry.get("command_text", ""),
                intent=entry.get("intent", "UNKNOWN"),
                execution_result=execution_response,
                user_id=entry.get("user_id")
            )
            history_entries.append(history_entry)
        
        return ExecutionHistoryResponse(
            history=history_entries,
            total_count=total_count,
            page=1,
            page_size=limit
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 기록 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"기록 조회 오류: {str(e)}")

@router.get("/setup", tags=["Setup Management"])
def get_setup_configuration():
    """
    설정 진행 상황 조회
    
    Returns:
        설정 상태 및 진행률
    """
    try:
        status = command_executor.get_current_status()
        
        return {
            "setup_complete": status["setup_complete"],
            "current_step": status.get("setup_step"),
            "current_mode": status["current_mode"],
            "user_settings": status["user_settings"],
            "is_listening": status["is_listening"]
        }
        
    except Exception as e:
        print(f"[오류] 설정 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 오류: {str(e)}")

@router.delete("/setup", tags=["Setup Management"])
def delete_setup_configuration():
    """
    설정 초기화 (재설정)
    
    Returns:
        초기화 결과
    """
    try:
        command_executor.reset_setup()
        
        return {
            "message": "설정이 초기화되었습니다.",
            "current_step": "start",
            "current_mode": "setup",
            "progress": "0/6",
            "success": True
        }
        
    except Exception as e:
        print(f"[오류] 설정 초기화 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"초기화 오류: {str(e)}")
