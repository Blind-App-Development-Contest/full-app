import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# from api import users
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uvicorn
import re
from services.speech_service import SpeechService

# FastAPI 앱 생성
app = FastAPI(title="음성 명령 인식 테스트 API", version="1.0.0")

# CORS 설정 (Flutter 앱에서 호출 가능하도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 요청 모델
class SpeechRecognitionRequest(BaseModel):
    command_text: str

# 응답 모델
class SpeechRecognitionResponse(BaseModel):
    intent: str
    entities: dict
    confidence: float = 1.0

speech_service = SpeechService()

# 키워드 매핑 테이블
KEYWORD_MAPPING = {
    'CAMERA': ['카메라', '사진', '촬영', '찍어', '보여'],
    'NAVIGATION': ['길찾기', '길', '가는법', '방향', '찾아', '네비'],
    'EMERGENCY_CALL': ['보호자', '긴급', '도움', '전화', '연락'],
    'SETTINGS': ['설정', '환경설정', '옵션'],
    'HELP': ['도움말', '도움', '헬프', '사용법', '명령어'],
    'STOP_LISTENING': ['중단', '멈춰', '그만', '중지', '끝'],
    'START_LISTENING': ['시작', '듣기', '음성인식', '다시'],
    'DESCRIBE_SCENE': ['주변', '앞', '보이는', '설명', '묘사'],
    'FIND_POI': ['찾아', '어디', '위치', '장소'],
}

def analyze_command(text: str) -> SpeechRecognitionResponse:
    """
    음성 텍스트를 분석하여 의도와 엔티티를 추출
    """
    text = text.lower().strip()
    
    print(f"[DEBUG] 분석할 텍스트: '{text}'")
    
    # 각 의도별 키워드 매칭
    for intent, keywords in KEYWORD_MAPPING.items():
        for keyword in keywords:
            if keyword in text:
                entities = {}
                
                # 특별한 엔티티 추출
                if intent == 'FIND_POI':
                    entities = extract_poi_entities(text)
                elif intent == 'NAVIGATION':
                    entities = extract_destination(text)
                
                print(f"[DEBUG] 매칭된 의도: {intent}, 키워드: {keyword}")
                return SpeechRecognitionResponse(
                    intent=intent,
                    entities=entities,
                    confidence=0.9
                )
    
    # 매칭되지 않은 경우 컨텍스트 추론
    inferred = infer_from_context(text)
    print(f"[DEBUG] 추론 결과: {inferred}")
    return inferred

def extract_poi_entities(text: str) -> dict:
    """POI 관련 엔티티 추출"""
    poi_types = ['병원', '약국', '은행', '마트', '편의점', '지하철역', '버스정류장', '카페', '식당']
    
    for poi in poi_types:
        if poi in text:
            return {'poi_name': poi, 'search_radius': 1000}
    
    return {'poi_name': '가까운 장소', 'search_radius': 500}

def extract_destination(text: str) -> dict:
    """목적지 추출"""
    # 간단한 목적지 패턴 매칭
    destinations = ['집', '회사', '학교', '병원', '역', '공항']
    
    for dest in destinations:
        if dest in text:
            return {'destination': dest}
    
    return {'destination': '목적지'}

def infer_from_context(text: str) -> SpeechRecognitionResponse:
    """컨텍스트 기반 추론"""
    
    # 인사말
    if any(word in text for word in ['안녕', '시작', '처음']):
        return SpeechRecognitionResponse(
            intent='START_LISTENING',
            entities={},
            confidence=0.7
        )
    
    # 감사 인사
    if any(word in text for word in ['고마워', '감사', '좋아']):
        return SpeechRecognitionResponse(
            intent='HELP',
            entities={},
            confidence=0.6
        )
    
    # 질문 형태
    if '?' in text or any(word in text for word in ['뭐', '어떻게', '무엇']):
        return SpeechRecognitionResponse(
            intent='HELP',
            entities={},
            confidence=0.5
        )
    
    # 기본값
    return SpeechRecognitionResponse(
        intent='unknown',
        entities={},
        confidence=0.0
    )

@app.get("/")
def root():
    """서버 상태 확인"""
    return {
        "message": "음성 명령 인식 테스트 서버가 실행 중입니다",
        "endpoint": "/api/users/speech/recognition",
        "supported_intents": list(KEYWORD_MAPPING.keys())
    }


# ===== STT 테스트용 엔드포인트 =====
@app.post("/api/users/speech/transcribe")
async def test_stt_only(file: UploadFile = File(...)):
    """
    STT 기능 테스트용 - DB 저장 없이 성공/실패 여부만 확인
    """
    print(f"[STT 테스트] 파일 수신: {file.filename}, 타입: {file.content_type}")
    
    # iPhone에서는 content_type이 다를 수 있으므로 더 유연하게 처리
    allowed_types = ["audio/", "application/octet-stream"]
    if not any(file.content_type.startswith(t) for t in allowed_types):
        print(f"[STT 테스트] 지원하지 않는 파일 타입: {file.content_type}")
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 타입: {file.content_type}")
        
    audio_bytes = await file.read()
    print(f"[STT 테스트] 파일 크기: {len(audio_bytes)} bytes")
    
    try:
        # SpeechService로 STT 변환
        transcribed_text = await speech_service.transcribe_audio(audio_bytes)
        print(f"[STT 테스트] 변환 결과: '{transcribed_text}'")
        
        return {
            "text": transcribed_text,
            "success": bool(transcribed_text),
            "message": "STT 성공" if transcribed_text else "STT 실패 - 빈 결과",
            "file_size_bytes": len(audio_bytes)
        }
    except Exception as e:
        print(f"[STT 테스트] 오류 발생: {e}")
        return {
            "text": "",
            "success": False,
            "message": f"STT 오류: {str(e)}",
            "file_size_bytes": len(audio_bytes)
        }

@app.post("/api/users/speech/recognition", response_model=SpeechRecognitionResponse)
async def recognize_speech_command(request: SpeechRecognitionRequest):
    """
    음성으로 인식된 텍스트를 받아서 명령의 의도와 엔티티를 분석
    
    Args:
        request: command_text를 포함한 요청
        
    Returns:
        intent: 명령의 의도 (TEXT_READ, CAMERA, NAVIGATION 등)
        entities: 추출된 엔티티 정보
        confidence: 분석 신뢰도
    """
    try:
        if not request.command_text or not request.command_text.strip():
            raise HTTPException(status_code=400, detail="command_text는 필수입니다")
        
        print(f"\n[API 호출] 받은 명령: '{request.command_text}'")
        
        # 명령 분석
        result = analyze_command(request.command_text)
        
        print(f"[API 응답] 의도: {result.intent}, 엔티티: {result.entities}")
        
        return result
        
    except Exception as e:
        print(f"[오류] 명령 분석 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")

@app.get("/api/users/speech/recognition/test")
def test_various_commands():
    """다양한 명령어 테스트"""
    test_commands = [
        "다음 단계",
        "보폭 측정 시작",
        "카메라 모드", 
        "길찾기 모드 ",
        "보호자 호출",
        "설정",
        "도움말",
        "주변 안내",
    ]
    
    results = []
    for cmd in test_commands:
        result = analyze_command(cmd)
        results.append({
            "command": cmd,
            "intent": result.intent,
            "entities": result.entities,
            "confidence": result.confidence
        })
    
    return {"test_results": results}

if __name__ == "__main__":
    print("🚀 음성 명령 인식 테스트 서버 시작")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=False  # 개발용 자동 리로드
    )