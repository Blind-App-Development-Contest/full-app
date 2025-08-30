"""음성 처리 전용 라우터"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Optional, Dict, Any
import logging

from models.recognition_schemas import (
    SpeechRecognitionRequest, 
    SpeechRecognitionResponse, 
    STTResponse
)
from models.execution_schemas import (
    FullCommandRequest,
    FullCommandResponse,
    CommandExecutionResponse
)
from models.common_models import (
    ExecutionStatus, UnifiedCommandResponse, SchemaConverter
)
from models.fastdepth_models import SpeechCommandRequest
from services.command_executor import CommandExecutionResult
from config.settings import get_settings
from api.measurement import (
    get_current_context,
    execute_command_conditionally
)
from services.speech_analyzer import SpeechAnalyzer

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

@router.get("")
@router.get("/")
async def speech_status():
    """음성 처리 서비스 상태 확인"""
    return {
        "service": "Speech Processing",
        "status": "active",
        "endpoints": {
            "transcribe": "POST /transcribe - 음성을 텍스트로 변환",
            "recognition": "POST /recognition - 음성 명령 인식",
            "commands": "POST /commands - 음성 명령 처리",
            "intents": "GET /intents - 지원하는 의도 목록"
        }
    }

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager

speech_service = service_manager.get_speech_service()
speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()

@router.post("/transcribe", response_model=STTResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    """
    STT 기능 - 오디오 파일을 텍스트로 변환 (통합된 음성 서비스 사용)
    """
    try:
        # 통합된 음성 서비스로 전체 처리 (검증 + 전처리 + 음성인식)
        transcribed_text = await speech_service.transcribe_from_file(file)
        
        # 파일 크기 정보 (로깅용)
        file.file.seek(0, 2)  # 파일 끝으로 이동
        file_size_bytes = file.file.tell()
        file.file.seek(0)  # 파일 처음으로 복원
        
        print(f"[STT] 변환 결과: '{transcribed_text}'")
        
        return STTResponse(
            text=transcribed_text,
            success=bool(transcribed_text),
            message="STT 성공" if transcribed_text else "STT 실패 - 빈 결과",
            file_size_bytes=file_size_bytes
        )
        
    except HTTPException:
        # SpeechService에서 이미 처리된 HTTP 예외는 그대로 전달
        raise
    except Exception as e:
        print(f"[STT] 예상치 못한 오류 발생: {e}")
        return STTResponse(
            text="",
            success=False,
            message=f"STT 처리 오류: {str(e)}",
            file_size_bytes=0
        )

@router.get("/recognition")
async def get_recognition_info():
    """음성 인식 서비스 정보 조회"""
    return {
        "service": "Speech Recognition",
        "status": "active",
        "supported_languages": ["ko-KR"],
        "usage": "POST /recognition with command_text to analyze speech intent"
    }

@router.post("/recognition", response_model=SpeechRecognitionResponse)
async def analyze_speech_recognition(request: SpeechRecognitionRequest):
    """
    음성으로 인식된 텍스트를 받아서 명령의 의도와 엔티티를 분석 - 통합 헬퍼 사용
    """
    try:
        print(f"\n[명령 분석] 받은 명령: '{request.command_text}'")
        
        # speech_analyzer 서비스 사용 - 컨텍스트 감지와 분석을 한번에 처리
        context = get_current_context()
        result = speech_analyzer.analyze_command(request.command_text, context)
        
        print(f"[분석 결과] 의도: {result.intent}, 신뢰도: {result.confidence}")
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[오류] 명령 분석 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@router.post("/commands", response_model=UnifiedCommandResponse)
async def execute_unified_speech_commands(request: SpeechCommandRequest):
    """
    통합 음성 명령 처리 엔드포인트 - 모든 사용자 명령의 주 진입점
    
    이 엔드포인트는:
    1. 텍스트 분석 및 의도 파악
    2. CommandExecutor로 위임하여 실행
    3. 프레임 데이터 직접 처리하지 않음 (realtime router 분리)
    4. 측정 상태 포함한 통합 응답 제공
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        logger.info(f"통합 음성 명령 처리 시작: '{request.command_text}'")
        
        # 1단계: 음성 명령 분석 - speech_analyzer 서비스 사용 (컨텍스트 자동 감지 포함)
        context = get_current_context()
        recognition_result = speech_analyzer.analyze_command(request.command_text, context)
        logger.info(f"명령 분석 완료 - 의도: {recognition_result.intent}, 신뢰도: {recognition_result.confidence}")
        
        # 2단계: CommandExecutor로 실행 위임 (Single Source of Truth) - 통합 실행 로직 사용
        execution_result = await execute_command_conditionally(
            recognition_result, 
            request.execute_immediately
        )
        if request.execute_immediately:
            logger.info(f"명령 실행 완료 - 상태: {execution_result.status.value}")
        
        # 3단계: 현재 측정 상태 조회 (통합 상태)
        measurement_status = None
        try:
            measurement_status = command_executor.get_step_measurement_status()
        except Exception as status_error:
            logger.warning(f"측정 상태 조회 실패: {status_error}")
        
        # 4단계: 통합 응답 생성
        execution_response = SchemaConverter.command_execution_result_to_response(execution_result)
        
        response = UnifiedCommandResponse(
            intent=recognition_result.intent,
            entities=recognition_result.entities,
            confidence=recognition_result.confidence,
            execution=execution_response,
            measurement_status=measurement_status
        )
        
        logger.debug(f"통합 응답 생성 완료 - 측정 활성: {measurement_status.measurement_active if measurement_status else 'N/A'}")
        
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"통합 음성 명령 처리 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@router.post("/commands/legacy", response_model=FullCommandResponse)
async def execute_speech_commands_legacy(request: FullCommandRequest):
    """
    기존 호환성을 위한 음성 명령 엔드포인트 (deprecated)
    
    새로운 클라이언트는 /commands를 사용해주세요.
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        print(f"\n[레거시 명령 실행] 시작: '{request.command_text}'")
        
        # 1단계: 음성 명령 분석 - speech_analyzer 서비스 사용 (컨텍스트 자동 감지 포함)
        context = get_current_context()
        recognition_result = speech_analyzer.analyze_command(request.command_text, context)
        print(f"[인식 완료] 의도: {recognition_result.intent}, 신뢰도: {recognition_result.confidence}")
        
        # 2단계: 명령 실행 - 통합 실행 로직 사용
        execution_result = await execute_command_conditionally(
            recognition_result, 
            request.execute_immediately
        )
        if request.execute_immediately:
            print(f"[실행 완료] 상태: {execution_result.status.value}")
        
        # 응답 생성
        response = FullCommandResponse(
            intent=recognition_result.intent,
            entities=recognition_result.entities,
            confidence=recognition_result.confidence,
            execution=CommandExecutionResponse(
                status=execution_result.status,
                message=execution_result.message,
                data=execution_result.data,
                actions=execution_result.actions,
                timestamp=execution_result.timestamp
            )
        )
        
        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 레거시 음성 액션 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@router.get("/intents", tags=["Speech Intents"])
def get_speech_intents():
    """
    지원하는 의도 목록 반환 (칼만 필터 의도 포함)
    """
    base_intents = speech_analyzer.get_supported_intents()
    return {
        "supported_intents": base_intents,
        "keyword_mapping": speech_analyzer.KEYWORD_MAPPING,
        "measurement_active": command_executor.is_measurement_active(),
        "total_intents": len(base_intents)
    }