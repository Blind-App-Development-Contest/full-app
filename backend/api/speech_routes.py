from fastapi import APIRouter, HTTPException, UploadFile, File
from models.recognition_schemas import (
    SpeechRecognitionRequest, 
    SpeechRecognitionResponse, 
    STTResponse,
    CommandTestResponse
)
from models.execution_schemas import (
    FullCommandRequest,
    FullCommandResponse,
    CommandExecutionResponse
)
from services.speech_service import SpeechService
from services.speech_analyzer import SpeechAnalyzer
from services.command_executor import CommandExecutor, CommandExecutionResult, ExecutionStatus
from config.settings import get_settings

settings = get_settings()
router = APIRouter()

# 싱글톤 서비스 인스턴스 사용
from services.singleton import service_manager

speech_service = service_manager.get_speech_service()
speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()

@router.post("/transcribe", response_model=STTResponse)
async def test_stt_only(file: UploadFile = File(...)):
    """
    STT 기능 테스트용 - DB 저장 없이 성공/실패 여부만 확인
    
    Args:
        file: 업로드할 오디오 파일
        
    Returns:
        STTResponse: STT 변환 결과
    """
    print(f"[STT 테스트] 파일 수신: {file.filename}, 타입: {file.content_type}")
    
    # iPhone에서는 content_type이 다를 수 있으므로 더 유연하게 처리
    if not any(file.content_type.startswith(t) for t in settings.SUPPORTED_AUDIO_TYPES):
        print(f"[STT 테스트] 지원하지 않는 파일 타입: {file.content_type}")
        raise HTTPException(
            status_code=400, 
            detail=f"지원하지 않는 파일 타입: {file.content_type}"
        )
    
    # 파일 크기 검증
    audio_bytes = await file.read()
    file_size_mb = len(audio_bytes) / (1024 * 1024)
    
    if file_size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 너무 큽니다. 최대 {settings.MAX_FILE_SIZE_MB}MB"
        )
    
    print(f"[STT 테스트] 파일 크기: {len(audio_bytes)} bytes ({file_size_mb:.2f}MB)")
    
    try:
        # SpeechService로 STT 변환
        transcribed_text = await speech_service.transcribe_audio(audio_bytes)
        print(f"[STT 테스트] 변환 결과: '{transcribed_text}'")
        
        return STTResponse(
            text=transcribed_text,
            success=bool(transcribed_text),
            message="STT 성공" if transcribed_text else "STT 실패 - 빈 결과",
            file_size_bytes=len(audio_bytes)
        )
    except Exception as e:
        print(f"[STT 테스트] 오류 발생: {e}")
        return STTResponse(
            text="",
            success=False,
            message=f"STT 오류: {str(e)}",
            file_size_bytes=len(audio_bytes)
        )

@router.post("/recognition", response_model=SpeechRecognitionResponse)
async def recognize_speech_command(request: SpeechRecognitionRequest):
    """
    음성으로 인식된 텍스트를 받아서 명령의 의도와 엔티티를 분석
    
    Args:
        request: command_text를 포함한 요청
        
    Returns:
        SpeechRecognitionResponse: 분석 결과 (intent, entities, confidence)
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        print(f"\n[API 호출] 받은 명령: '{request.command_text}'")
        
        # 명령 분석
        result = speech_analyzer.analyze_command(request.command_text)
        
        print(f"[API 응답] 의도: {result.intent}, 엔티티: {result.entities}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 명령 분석 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@router.get("/recognition/test", response_model=CommandTestResponse)
def test_various_commands():
    """
    다양한 명령어 테스트
    
    Returns:
        CommandTestResponse: 테스트 결과 목록
    """
    try:
        results = speech_analyzer.test_various_commands()
        return CommandTestResponse(test_results=results)
    except Exception as e:
        print(f"[오류] 테스트 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"테스트 오류: {str(e)}")

@router.get("/intents")
def get_supported_intents():
    """
    지원하는 의도 목록 반환
    
    Returns:
        dict: 지원하는 의도 목록과 키워드 매핑
    """
    return {
        "supported_intents": speech_analyzer.get_supported_intents(),
        "keyword_mapping": speech_analyzer.KEYWORD_MAPPING
    }

@router.post("/action", response_model=FullCommandResponse)
async def handle_speech_command(request: FullCommandRequest):
    """
    음성 인식 결과를 받아서 명령 처리 및 실행

    Args:
        request: 음성 텍스트와 실행 옵션

    Returns:
        FullCommandResponse: 인식 및 실행 결과
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        print(f"\n[음성 액션] 시작: '{request.command_text}'")
        
        # 1단계: 음성 명령 분석
        recognition_result = speech_analyzer.analyze_command(request.command_text)
        print(f"[인식 완료] 의도: {recognition_result.intent}")
        
        # 2단계: 명령 실행
        if request.execute_immediately:
            execution_result = await command_executor.execute_command(recognition_result)
            print(f"[실행 완료] 상태: {execution_result.status.value}")
        else:
            execution_result = CommandExecutionResult(
                status=ExecutionStatus.PENDING,
                message="명령이 분석되었습니다.",
                data={"execute_immediately": False},
                actions=["analyze_command"]
            )
        
        # 응답 생성
        from models.execution_schemas import CommandExecutionResponse, FullCommandResponse
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[오류] 음성 액션 처리 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")
        