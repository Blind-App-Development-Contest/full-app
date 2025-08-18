from fastapi import APIRouter, HTTPException, UploadFile, File
from models.schemas import (
    SpeechRecognitionRequest, 
    SpeechRecognitionResponse, 
    STTResponse,
    CommandTestResponse
)
from services.speech_service import SpeechService
from services.speech_analyzer import SpeechAnalyzer
from config.settings import get_settings

settings = get_settings()
router = APIRouter()

# 서비스 인스턴스 생성
speech_service = SpeechService()
speech_analyzer = SpeechAnalyzer()

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
