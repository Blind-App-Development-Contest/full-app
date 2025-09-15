"""음성 처리 전용 라우터"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Optional, Dict, Any
import logging

from models.recognition_schemas import (
    SpeechRecognitionRequest, 
    SpeechRecognitionResponse, 
    STTResponse
)

from models.common_models import (
    UnifiedCommandResponse, SchemaConverter
)
from models.fastdepth_models import SpeechCommandRequest
# CommandExecutionResult는 singleton을 통해 접근
from config.settings import get_settings
from middleware.error_handler import ErrorLogger
# SpeechAnalyzer는 singleton을 통해 접근

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

@router.get("")
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

        # 후처리: 블랙리스트/패턴 필터 (광고/자막 고정문구 등)
        blacklist_patterns = [
            r"http[s]?://", r"www\.", r"uptitle", r"자막", r"subtitles?",
            r"뉴스", r"mbc\s*뉴스", r"광고", r"channel",
            r"youtube", r"유튜브", r"subscribe", r"구독", r"좋아요", r"알림",
            r"댓글", r"공유", r"bell", r"notification"
        ]
        import re
        is_blacklisted = any(re.search(pat, transcribed_text, flags=re.IGNORECASE) for pat in blacklist_patterns)
        if is_blacklisted:
            print("[STT] 블랙리스트 패턴 감지 - 결과 필터링")
            return STTResponse(
                text="",
                success=False,
                message="STT 필터링: 신뢰도 낮은 고정 문구/URL 감지",
                file_size_bytes=file_size_bytes
            )
        
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
        ErrorLogger.log_api_error("Speech", "음성 파일 변환", e)
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
        
        # speech_analyzer 서비스 사용 - 기본 컨텍스트로 분석
        result = speech_analyzer.analyze_command(request.command_text)
        
        print(f"[분석 결과] 의도: {result.intent}, 신뢰도: {result.confidence}")
        
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        ErrorLogger.log_api_error("Speech", "명령 분석", e)
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
        
        # 1단계: 음성 명령 분석 - speech_analyzer 서비스 사용
        recognition_result = speech_analyzer.analyze_command(request.command_text)
        logger.info(f"명령 분석 완료 - 의도: {recognition_result.intent}, 신뢰도: {recognition_result.confidence}")
        
        # 2단계: CommandExecutor로 실행 위임
        executor = service_manager.get_command_executor(request.user_id)
        execution_result = await executor.execute_command(
            recognition_result.intent,
            recognition_result.entities,
            execute_immediately=request.execute_immediately
        )
        if request.execute_immediately:
            logger.info(f"명령 실행 완료 - 상태: {execution_result.status.value}")
        
        # 3단계: 현재 측정 상태 조회 (통합 상태)
        measurement_status = None
        try:
            measurement_status = command_executor.get_step_measurement_status()
        except Exception as status_error:
            ErrorLogger.log_api_error("Speech", "측정 상태 조회", status_error)
        
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
        ErrorLogger.log_api_error("Speech", "통합 음성 명령 처리", e)
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

# Legacy 엔드포인트 제거됨 - /commands 엔드포인트 사용

@router.get("/intents", tags=["Speech Processing"])
def get_speech_intents():
    """
    지원하는 의도 목록 반환 - 프론트엔드에서 사용 가능한 모든 명령어
    """
    base_intents = speech_analyzer.get_supported_intents()
    return {
        "supported_intents": base_intents,
        "keyword_mapping": speech_analyzer.KEYWORD_MAPPING,
        "measurement_active": command_executor.is_measurement_active(),
        "total_intents": len(base_intents),
        "advanced_commands": {
            "footstep_measurement": {
                "start": speech_analyzer.KEYWORD_MAPPING.get('FOOTSTEP_MEASUREMENT_START', []),
                "complete": speech_analyzer.KEYWORD_MAPPING.get('FOOTSTEP_MEASUREMENT_COMPLETE', []),
                "cancel": speech_analyzer.KEYWORD_MAPPING.get('FOOTSTEP_MEASUREMENT_CANCEL', []),
                "status": speech_analyzer.KEYWORD_MAPPING.get('FOOTSTEP_STATUS_CHECK', [])
            },
            "navigation": speech_analyzer.KEYWORD_MAPPING.get('NAVIGATION', []),
            "camera": speech_analyzer.KEYWORD_MAPPING.get('CAMERA', []),
            "emergency": speech_analyzer.KEYWORD_MAPPING.get('EMERGENCY_CALL', []),
            "settings": speech_analyzer.KEYWORD_MAPPING.get('SETTINGS', []),
            "scene_description": speech_analyzer.KEYWORD_MAPPING.get('DESCRIBE_SCENE', [])
        }
    }

@router.post("/advanced-command", response_model=UnifiedCommandResponse)
async def execute_advanced_command(request: SpeechCommandRequest):
    """
    고급 음성 명령 처리 - 프론트엔드에서 고급 기능 활용
    
    지원하는 고급 명령:
    - 보폭 측정 전체 플로우 (시작/완료/취소/상태확인)
    - 네비게이션 및 길찾기
    - 카메라 모드 전환
    - 긴급 상황 처리
    - 주변 환경 설명
    - 설정 변경
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        logger.info(f"고급 음성 명령 처리: '{request.command_text}'")
        
        # 1단계: 고급 명령 분석
        recognition_result = speech_analyzer.analyze_command(request.command_text)
        logger.info(f"고급 명령 분석: {recognition_result.intent} (신뢰도: {recognition_result.confidence})")
        
        # 2단계: 고급 명령별 특별 처리
        executor = service_manager.get_command_executor(request.user_id)
        
        # 보폭 측정 관련 고급 처리
        if recognition_result.intent.startswith('FOOTSTEP_'):
            execution_result = await _handle_advanced_footstep_command(
                executor, recognition_result, request.execute_immediately
            )
        # 네비게이션 관련 고급 처리
        elif recognition_result.intent == 'NAVIGATION':
            execution_result = await _handle_navigation_command(
                executor, recognition_result, request.execute_immediately
            )
        # 카메라 관련 고급 처리
        elif recognition_result.intent == 'CAMERA':
            execution_result = await _handle_camera_command(
                executor, recognition_result, request.execute_immediately
            )
        # 긴급 상황 처리
        elif recognition_result.intent == 'EMERGENCY_CALL':
            execution_result = await _handle_emergency_command(
                executor, recognition_result, request.execute_immediately
            )
        # 주변 설명 요청
        elif recognition_result.intent == 'DESCRIBE_SCENE':
            execution_result = await _handle_scene_description_command(
                executor, recognition_result, request.execute_immediately
            )
        # 기본 명령 처리
        else:
            execution_result = await executor.execute_command(
                recognition_result.intent,
                recognition_result.entities,
                execute_immediately=request.execute_immediately
            )
        
        # 3단계: 통합 응답 생성
        current_state = executor.get_current_measurement_status()
        
        # 고급 명령 처리 결과를 UnifiedCommandResponse로 변환
        unified_response = SchemaConverter.to_unified_command_response(
            recognition_result=recognition_result,
            execution_result=execution_result,
            measurement_status=current_state,
            user_id=str(request.user_id),
            advanced_features_enabled=True
        )
        
        logger.info(f"고급 명령 처리 완료: {execution_result.status.value}")
        return unified_response
        
    except HTTPException:
        raise
    except Exception as e:
        ErrorLogger.log_api_error("Speech", "고급 명령 처리", e)
        raise HTTPException(status_code=500, detail=f"고급 명령 처리 오류: {str(e)}")

# 고급 명령 처리 헬퍼 함수들 - 기존 CommandExecutor 메서드 활용
async def _handle_advanced_footstep_command(executor, recognition_result, execute_immediately):
    """보폭 측정 관련 고급 명령 처리 - 기존 메서드 활용"""
    intent = recognition_result.intent
    
    # 기존 CommandExecutor의 보폭 측정 메서드들 직접 호출
    if intent == 'FOOTSTEP_MEASUREMENT_START':
        return await executor._execute_footstep_measurement_start(recognition_result.entities)
    elif intent == 'FOOTSTEP_MEASUREMENT_COMPLETE':
        return await executor._execute_footstep_measurement_complete(recognition_result.entities)
    elif intent == 'FOOTSTEP_MEASUREMENT_CANCEL':
        return await executor._execute_footstep_measurement_cancel(recognition_result.entities)
    elif intent == 'FOOTSTEP_STATUS_CHECK':
        # 현재 측정 상태 반환
        status = executor.get_measurement_progress()
        return executor.CommandExecutionResult(
            status=executor.ExecutionStatus.SUCCESS,
            message=f"측정 상태: {'진행 중' if status['active'] else '비활성'}",
            data=status,
            actions=["status_check", "tts_announce"]
        )
    else:
        # 기본 명령 처리
        return await executor.execute_command(
            intent, recognition_result.entities, execute_immediately
        )

async def _handle_navigation_command(executor, recognition_result, execute_immediately):
    """네비게이션 명령 고급 처리 - 기존 메서드 활용"""
    # 기존 네비게이션 실행 메서드 호출
    return await executor._execute_navigation(recognition_result.entities)

async def _handle_camera_command(executor, recognition_result, execute_immediately):
    """카메라 명령 고급 처리 - 기존 메서드 활용"""
    # 기존 카메라 실행 메서드 호출
    return await executor._execute_camera(recognition_result.entities)

async def _handle_emergency_command(executor, recognition_result, execute_immediately):
    """긴급 상황 명령 고급 처리 - 기존 메서드 활용"""
    # 기존 긴급 전화 실행 메서드 호출
    return await executor._execute_emergency_call(recognition_result.entities)

async def _handle_scene_description_command(executor, recognition_result, execute_immediately):
    """주변 환경 설명 명령 고급 처리 - 기존 메서드 활용"""
    # 기존 주변 설명 실행 메서드 호출
    return await executor._execute_describe_scene(recognition_result.entities)
