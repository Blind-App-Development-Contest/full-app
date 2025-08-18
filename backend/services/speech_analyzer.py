from typing import Dict, List, Any
from models.schemas import SpeechRecognitionResponse
from config.settings import get_settings

settings = get_settings()

class SpeechAnalyzer:
    """음성 명령 분석 클래스"""
    
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
    
    def __init__(self):
        self.poi_types = ['병원', '약국', '은행', '마트', '편의점', '지하철역', '버스정류장', '카페', '식당']
        self.destinations = ['집', '회사', '학교', '병원', '역', '공항']
    
    def analyze_command(self, text: str) -> SpeechRecognitionResponse:
        """
        음성 텍스트를 분석하여 의도와 엔티티를 추출
        
        Args:
            text: 분석할 음성 텍스트
            
        Returns:
            SpeechRecognitionResponse: 분석 결과
        """
        text = text.lower().strip()
        
        print(f"[DEBUG] 분석할 텍스트: '{text}'")
        
        # 각 의도별 키워드 매칭
        for intent, keywords in self.KEYWORD_MAPPING.items():
            for keyword in keywords:
                if keyword in text:
                    entities = self._extract_entities(intent, text)
                    
                    print(f"[DEBUG] 매칭된 의도: {intent}, 키워드: {keyword}")
                    return SpeechRecognitionResponse(
                        intent=intent,
                        entities=entities,
                        confidence=0.9
                    )
        
        # 매칭되지 않은 경우 컨텍스트 추론
        inferred = self._infer_from_context(text)
        print(f"[DEBUG] 추론 결과: {inferred}")
        return inferred
    
    def _extract_entities(self, intent: str, text: str) -> Dict[str, Any]:
        """의도에 따른 엔티티 추출"""
        if intent == 'FIND_POI':
            return self._extract_poi_entities(text)
        elif intent == 'NAVIGATION':
            return self._extract_destination(text)
        else:
            return {}
    
    def _extract_poi_entities(self, text: str) -> Dict[str, Any]:
        """POI 관련 엔티티 추출"""
        for poi in self.poi_types:
            if poi in text:
                return {
                    'poi_name': poi, 
                    'search_radius': settings.POI_SEARCH_RADIUS
                }
        
        return {
            'poi_name': '가까운 장소', 
            'search_radius': settings.DEFAULT_SEARCH_RADIUS
        }
    
    def _extract_destination(self, text: str) -> Dict[str, Any]:
        """목적지 추출"""
        for dest in self.destinations:
            if dest in text:
                return {'destination': dest}
        
        return {'destination': '목적지'}
    
    def _infer_from_context(self, text: str) -> SpeechRecognitionResponse:
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
    
    def get_supported_intents(self) -> List[str]:
        """지원하는 의도 목록 반환"""
        return list(self.KEYWORD_MAPPING.keys())
    
    def test_various_commands(self) -> List[Dict[str, Any]]:
        """다양한 명령어 테스트"""
        test_commands = [
            "다음 단계",
            "보폭 측정 시작", 
            "카메라 모드",
            "길찾기 모드",
            "보호자 호출",
            "설정",
            "도움말",
            "주변 안내",
        ]
        
        results = []
        for cmd in test_commands:
            result = self.analyze_command(cmd)
            results.append({
                "command": cmd,
                "intent": result.intent,
                "entities": result.entities,
                "confidence": result.confidence
            })
        
        return results