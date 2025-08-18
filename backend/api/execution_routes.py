from fastapi import APIRouter, HTTPException
from models.execution_schemas import (
    SystemStatusResponse,
    ExecutionHistoryResponse
)
from services.command_executor import CommandExecutor

router = APIRouter()

# 서비스 인스턴스 생성 (싱글톤으로 관리)
command_executor = CommandExecutor()

@router.get("/status", response_model=SystemStatusResponse)
def get_system_status():
    """
    현재 시스템 상태 조회
    
    Returns:
        SystemStatusResponse: 시스템 현재 상태
    """
    try:
        status = command_executor.get_current_status()
        
        return SystemStatusResponse(
            is_listening=status["is_listening"],
            current_mode=status["current_mode"], 
            last_execution=status["last_execution"],
            total_commands=status["total_commands"]
        )
        
    except Exception as e:
        print(f"[오류] 상태 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 오류: {str(e)}")

@router.get("/history", response_model=ExecutionHistoryResponse)
def get_execution_history(limit: int = 10):
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
        
        history = command_executor.get_execution_history(limit)
        total_count = len(command_executor.execution_history)
        
        return ExecutionHistoryResponse(
            history=history,
            total_count=total_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 기록 조회 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"기록 조회 오류: {str(e)}")