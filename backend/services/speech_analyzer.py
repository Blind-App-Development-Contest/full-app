import re
from typing import Dict, List, Any, Tuple
from models.recognition_schemas import SpeechRecognitionResponse
from config.settings import get_settings

settings = get_settings()

class SpeechAnalyzer:
    """음성 명령 분석 클래스"""
    
    # 키워드 매핑 테이블 (칼만 필터 명령어 추가)
    KEYWORD_MAPPING = {
        'CAMERA': ['카메라', '사진', '촬영', '찍어', '보여', '카메라모드'],
        'NAVIGATION': ['길찾기', '길', '가는법', '방향', '찾아', '네비', '길찾기모드'],
        'EMERGENCY_CALL': ['보호자', '긴급', '도움', '전화', '연락'],
        'SETTINGS': ['설정', '환경설정', '옵션', '보폭설정', '음성설정', '보호자설정'],
        'HELP': ['도움말', '도움', '헬프', '사용법', '명령어'],
        'STOP_LISTENING': ['중단', '멈춰', '그만', '중지', '끝'],
        'START_LISTENING': ['시작', '듣기', '음성인식', '다시'],
        'DESCRIBE_SCENE': ['주변', '앞', '보이는', '설명', '묘사', '주변 안내'],
        'FIND_POI': ['찾아', '어디', '위치', '장소'],
        
        # ===== 칼만 필터 기반 보폭 측정 명령어들 =====
        'FOOTSTEP_MEASUREMENT_START': [
            '보폭 측정 시작', '보폭측정시작', '보폭 측정', '보폭측정',
            '측정 시작', '측정시작', '보폭 재측정', '보폭재측정',
            '정밀 측정 시작', '정밀측정', '실시간 측정 시작', '실시간측정',
            '칼만 측정', '칼만 필터 측정', '걸음 측정'
        ],
        'FOOTSTEP_MEASUREMENT_BEGIN': [
            '측정 시작', '걷기 시작', '출발', '측정 진행'
        ],
        'FOOTSTEP_MEASUREMENT_COMPLETE': [
            '측정 완료', '측정완료', '보폭 측정 완료', '보폭측정완료',
            '완료', '끝', '측정 끝', '측정끝', '도착', '그만', '스톱'
        ],
        'FOOTSTEP_MEASUREMENT_CANCEL': [
            '측정 취소', '측정취소', '보폭 측정 취소', '보폭측정취소',
            '취소', '중단', '측정 중단', '측정중단', '그만둬', '멈춰', '중지'
        ],
        'FOOTSTEP_STATUS_CHECK': [
            '보폭 상태', '보폭상태', '현재 보폭', '현재보폭',
            '측정 상태', '측정상태', '보폭 확인', '보폭확인',
            '진행 상황', '진행상황', '얼마나', '상태', '어떻게'
        ],
        'FOOTSTEP_SETTINGS': [
            '보폭 설정', '보폭설정', '보폭 변경', '보폭변경', 
            '걸음 설정', '걸음설정'
        ],
        'FOOTSTEP_HISTORY': [
            '보폭 기록', '보폭기록', '측정 기록', '측정기록',
            '이전 보폭', '이전보폭', '기록', '히스토리'
        ],
        'FOOTSTEP_RESET': [
            '측정 리셋', '측정리셋', '보폭 리셋', '보폭리셋',
            '초기화', '리셋', '다시', '새로'
        ]
    }
    
    # 컨텍스트별 우선순위 매핑
    CONTEXT_PRIORITY = {
        'measurement_active': [
            'FOOTSTEP_MEASUREMENT_COMPLETE',
            'FOOTSTEP_MEASUREMENT_CANCEL',
            'FOOTSTEP_STATUS_CHECK'
        ],
        'setup_step_length': [
            'FOOTSTEP_MEASUREMENT_START'
        ],
        'default': [
            'FOOTSTEP_MEASUREMENT_START',
            'FOOTSTEP_STATUS_CHECK',
            'CAMERA', 'NAVIGATION', 'HELP'
        ]
    }
    
    # 동의어 확장 매핑
    SYNONYM_EXPANSION = {
        '시작': ['시작', '시작해', '시작해줘', '해줘'],
        '완료': ['완료', '완료해', '완료해줘', '끝', '끝내', '끝내줘'],
        '취소': ['취소', '취소해', '취소해줘', '중단', '중단해', '중단해줘'],
        '상태': ['상태', '상황', '어때', '어떻게'],
        '측정': ['측정', '재기', '재어', '계산']
    }
    
    def __init__(self):
        self.poi_types = ['병원', '약국', '은행', '마트', '편의점', '지하철역', '버스정류장', '카페', '식당']
        self.destinations = ['집', '회사', '학교', '병원', '역', '공항']
        self.setup_steps = ['보폭 측정 시작', '다음 단계', '음성 설정 변경', '보호자 정보 수정', '보폭 설정', '음성 설정', '설정 완료']
        self.voice_keywords = {
            'female': ['여성', '여자', '여자목소리'],
            'male': ['남성', '남자', '남자목소리']
        }
        
        self.speed_keywords = {
            'slow': ['느리게', '천천히', '느림'],
            'normal': ['보통', '일반', '평소'],
            'fast': ['빠르게', '빨리', '빠름']
        }
    
    def analyze_command(self, text: str, context: str = "default") -> SpeechRecognitionResponse:
        """
        음성 텍스트를 분석하여 의도와 엔티티를 추출 (칼만 필터 지원)
        
        Args:
            text: 분석할 음성 텍스트
            context: 현재 컨텍스트 (선택적)
            
        Returns:
            SpeechRecognitionResponse: 분석 결과
        """
        if not text or not text.strip():
            return SpeechRecognitionResponse(
                intent='unknown',
                entities={},
                confidence=0.0,
                command_text=text
            )
        
        # 텍스트 전처리
        normalized_text = self._normalize_text(text)
        print(f"[DEBUG] 분석할 텍스트: '{text}' → 정규화: '{normalized_text}'")
        
        # 1단계: 컨텍스트 기반 우선 분석
        if context:
            context_result = self._analyze_with_context(normalized_text, text, context)
            if context_result and context_result.confidence > 0.8:
                print(f"[DEBUG] 컨텍스트 기반 매칭: {context_result.intent}")
                return context_result
        
        # 2단계: 키워드 매칭 분석
        keyword_result = self._analyze_with_keywords(normalized_text, text)
        if keyword_result.confidence > 0.7:
            print(f"[DEBUG] 키워드 매칭: {keyword_result.intent}")
            return keyword_result
        
        # 3단계: 패턴 기반 분석
        pattern_result = self._analyze_with_patterns(normalized_text, text)
        if pattern_result.confidence > 0.6:
            print(f"[DEBUG] 패턴 매칭: {pattern_result.intent}")
            return pattern_result
        
        # 4단계: 컨텍스트 추론
        inferred = self._infer_from_context(text)
        print(f"[DEBUG] 추론 결과: {inferred.intent}")
        return inferred
    
    def _normalize_text(self, text: str) -> str:
        """텍스트 정규화"""
        # 소문자 변환 및 공백 정리
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        
        # 특수문자 제거 (한글, 영문, 숫자만 유지)
        text = re.sub(r'[^\w\s가-힣]', ' ', text)
        
        # 동의어 확장
        for base_word, synonyms in self.SYNONYM_EXPANSION.items():
            for synonym in synonyms:
                if synonym in text:
                    text = text.replace(synonym, base_word)
        
        return text.strip()
    
    def _analyze_with_context(self, normalized_text: str, original_text: str, context: str) -> SpeechRecognitionResponse:
        """컨텍스트 기반 분석"""
        context_key = self._map_context_to_key(context)
        priority_intents = self.CONTEXT_PRIORITY.get(context_key, [])
        
        for intent in priority_intents:
            if intent in self.KEYWORD_MAPPING:
                keywords = self.KEYWORD_MAPPING[intent]
                confidence = self._calculate_keyword_confidence(normalized_text, keywords)
                
                if confidence > 0.6:  # 컨텍스트에서는 낮은 임계값 사용
                    entities = self._extract_entities(intent, original_text)
                    return SpeechRecognitionResponse(
                        intent=intent,
                        entities=entities,
                        confidence=min(confidence + 0.3, 1.0),  # 컨텍스트 보너스
                        command_text=original_text
                    )
        
        # 기본 응답 반환
        return SpeechRecognitionResponse(
            intent="UNKNOWN",
            entities={},
            confidence=0.1,
            command_text=original_text
        )
    
    def _analyze_with_keywords(self, normalized_text: str, original_text: str) -> SpeechRecognitionResponse:
        """키워드 매칭 기반 분석"""
        best_match = {
            'intent': 'unknown',
            'confidence': 0.0,
            'entities': {}
        }
        
        # 각 의도별 키워드 매칭
        for intent, keywords in self.KEYWORD_MAPPING.items():
            confidence = self._calculate_keyword_confidence(normalized_text, keywords)
            
            # 보폭 측정 관련 의도는 우선순위 부여
            if intent.startswith('FOOTSTEP_'):
                confidence += 0.1  # 보폭 측정 관련 보너스
            
            if confidence > best_match['confidence']:
                best_match = {
                    'intent': intent,
                    'confidence': min(confidence, 1.0),
                    'entities': self._extract_entities(intent, original_text)
                }
        
        return SpeechRecognitionResponse(
            intent=best_match['intent'],
            entities=best_match['entities'],
            confidence=best_match['confidence'],
            command_text=original_text
        )
    
    def _analyze_with_patterns(self, normalized_text: str, original_text: str) -> SpeechRecognitionResponse:
        """패턴 기반 분석"""
        # 보폭 측정 패턴들
        footstep_patterns = [
            (r'보폭.*측정.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.95),
            (r'측정.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'보폭.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'정밀.*측정', 'FOOTSTEP_MEASUREMENT_START', 0.90),
            (r'실시간.*측정', 'FOOTSTEP_MEASUREMENT_START', 0.90),
            (r'칼만.*측정', 'FOOTSTEP_MEASUREMENT_START', 0.90),
            
            (r'측정.*완료', 'FOOTSTEP_MEASUREMENT_COMPLETE', 0.95),
            (r'보폭.*완료', 'FOOTSTEP_MEASUREMENT_COMPLETE', 0.95),
            (r'^완료$', 'FOOTSTEP_MEASUREMENT_COMPLETE', 0.80),
            (r'^끝$', 'FOOTSTEP_MEASUREMENT_COMPLETE', 0.75),
            
            (r'측정.*취소', 'FOOTSTEP_MEASUREMENT_CANCEL', 0.95),
            (r'보폭.*취소', 'FOOTSTEP_MEASUREMENT_CANCEL', 0.95),
            (r'^취소$', 'FOOTSTEP_MEASUREMENT_CANCEL', 0.80),
            (r'^중단$', 'FOOTSTEP_MEASUREMENT_CANCEL', 0.75),
            
            (r'보폭.*상태', 'FOOTSTEP_STATUS_CHECK', 0.90),
            (r'측정.*상태', 'FOOTSTEP_STATUS_CHECK', 0.90),
            (r'현재.*보폭', 'FOOTSTEP_STATUS_CHECK', 0.85),
            (r'^상태$', 'FOOTSTEP_STATUS_CHECK', 0.70),
        ]
        
        # 기타 패턴들
        other_patterns = [
            (r'카메라|사진|촬영', 'CAMERA', 0.85),
            (r'길찾기|네비게이션|목적지', 'NAVIGATION', 0.85),
            (r'긴급|도움|위험|보호자', 'EMERGENCY_CALL', 0.85),
            (r'설정|환경설정', 'SETTINGS', 0.80),
            (r'도움말|사용법|명령어', 'HELP', 0.80),
            (r'주변.*설명|환경.*설명', 'DESCRIBE_SCENE', 0.80),
        ]
        
        all_patterns = footstep_patterns + other_patterns
        
        for pattern, intent, base_confidence in all_patterns:
            if re.search(pattern, normalized_text):
                entities = self._extract_entities(intent, original_text)
                return SpeechRecognitionResponse(
                    intent=intent,
                    entities=entities,
                    confidence=base_confidence,
                    command_text=original_text
                )
        
        return SpeechRecognitionResponse(
            intent='unknown',
            entities={},
            confidence=0.0,
            command_text=original_text
        )
    
    def _calculate_keyword_confidence(self, text: str, keywords: List[str]) -> float:
        """키워드 매칭 신뢰도 계산"""
        max_confidence = 0.0
        text_words = set(text.lower().split())
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 완전 매칭
            if keyword_lower in text.lower():
                max_confidence = max(max_confidence, 1.0)
                continue
            
            # 단어별 매칭
            keyword_words = set(keyword_lower.split())
            if len(keyword_words) == 1:
                # 단일 단어는 포함 여부만 확인
                if keyword_words.issubset(text_words):
                    max_confidence = max(max_confidence, 0.9)
            else:
                # 복합 단어는 포함된 단어 비율 계산
                intersection = keyword_words & text_words
                if len(intersection) > 0:
                    word_confidence = len(intersection) / len(keyword_words)
                    if word_confidence >= 0.5:  # 50% 이상 매칭 시만 인정
                        max_confidence = max(max_confidence, word_confidence * 0.9)
        
        return max_confidence
    
    def _map_context_to_key(self, context: str) -> str:
        """컨텍스트를 키로 매핑"""
        context_mapping = {
            'measurement_active': 'measurement_active',
            'realtime_footstep_measurement': 'measurement_active',
            'footstep_walking': 'measurement_active',
            'step_length': 'setup_step_length',
            'setup': 'setup_step_length'
        }
        return context_mapping.get(context, 'default')
    
    def _extract_entities(self, intent: str, text: str) -> Dict[str, Any]:
        """의도에 따른 엔티티 추출"""
        entities = {'raw_text': text}
        
        # 보폭 측정 관련 엔티티
        if intent.startswith('FOOTSTEP_'):
            entities.update({
                'measurement_type': 'kalman_filter',
                'category': 'footstep_measurement'
            })
            
            if intent == 'FOOTSTEP_MEASUREMENT_START':
                entities['action'] = 'start_measurement'
                
                # 측정 방식 키워드 감지
                if any(keyword in text for keyword in ['정밀', '실시간', '칼만']):
                    entities['precision_mode'] = "true"
                    
            elif intent == 'FOOTSTEP_MEASUREMENT_COMPLETE':
                entities['action'] = 'complete_measurement'
                
            elif intent == 'FOOTSTEP_MEASUREMENT_CANCEL':
                entities['action'] = 'cancel_measurement'
                
            elif intent == 'FOOTSTEP_STATUS_CHECK':
                entities['action'] = 'check_status'
                
                # 구체적인 정보 요청 감지
                if any(keyword in text for keyword in ['얼마나', '몇', '현재']):
                    entities['detail_requested'] = "true"
        
        # 기존 엔티티 추출 로직들
        elif intent == 'FIND_POI':
            entities.update(self._extract_poi_entities(text))
        elif intent == 'NAVIGATION':
            entities.update(self._extract_destination(text))
        elif intent == 'SETTINGS':
            entities.update(self._extract_settings_entities(text))
        
        return entities
    
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

    def _extract_settings_entities(self, text: str) -> Dict[str, Any]:
        """설정 관련 엔티티 추출"""
        entities = {}
        
        # 음성 타입 체크
        for voice_gender, keywords in self.voice_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    entities['voice_gender'] = voice_gender
                    break
        
        # 음성 속도 체크
        for speed_type, keywords in self.speed_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    entities['voice_speed'] = speed_type
                    break
        
        # 설정 타입 체크
        if '보폭' in text:
            entities['setting_type'] = 'step_length'
        elif '음성' in text:
            entities['setting_type'] = 'voice'
        elif '보호자' in text:
            entities['setting_type'] = 'caregiver'
        
        return entities
    
    def _infer_from_context(self, text: str) -> SpeechRecognitionResponse:
        """컨텍스트 기반 추론"""
        
        # 인사말
        if any(word in text for word in ['안녕', '시작', '처음']):
            return SpeechRecognitionResponse(
                intent='START_LISTENING',
                entities={},
                confidence=0.7,
                command_text=text
            )
        
        # 감사 인사
        if any(word in text for word in ['고마워', '감사', '좋아']):
            return SpeechRecognitionResponse(
                intent='HELP',
                entities={},
                confidence=0.6,
                command_text=text
            )
        
        # 질문 형태
        if '?' in text or any(word in text for word in ['뭐', '어떻게', '무엇']):
            return SpeechRecognitionResponse(
                intent='HELP',
                entities={},
                confidence=0.5, 
                command_text=text
            )
        
        # 기본값
        return SpeechRecognitionResponse(
            intent='unknown',
            entities={},
            confidence=0.0,
            command_text=text
        )
    
    def get_supported_intents(self) -> Dict[str, Any]:
        """지원하는 의도 목록 반환 (상세 정보 포함)"""
        supported = {}
        for intent, keywords in self.KEYWORD_MAPPING.items():
            supported[intent] = {
                'keywords': keywords[:3],  # 처음 3개만 표시
                'total_keywords': len(keywords),
                'category': 'footstep_measurement' if intent.startswith('FOOTSTEP_') else 'general',
                'measurement_type': 'kalman_filter' if intent.startswith('FOOTSTEP_') else None
            }
        return supported
    
    def test_various_commands(self) -> List[Dict[str, Any]]:
        """다양한 명령어 테스트"""
        test_commands = [
            # 기존 명령어들
            "다음 단계",
            "카메라 모드",
            "길찾기 모드", 
            "보호자 호출",
            "설정",
            "도움말",
            "주변 안내",
            "여성 목소리로 해주세요",
            "느리게 말해주세요",
            
            # 칼만 필터 보폭 측정 명령어들
            "보폭 측정 시작",
            "보폭측정시작", 
            "측정 시작",
            "정밀 측정 시작",
            "실시간 측정 시작",
            "칼만 측정",
            "측정 완료",
            "측정완료",
            "완료",
            "끝",
            "측정 취소",
            "취소",
            "중단",
            "보폭 상태",
            "현재 보폭",
            "측정 상태",
            "상태",
            
            # 복합/모호한 명령어들
            "보폭 재측정해줘",
            "정밀하게 측정 시작",
            "이제 완료",
            "그만 측정",
            "지금 상태 어때",
        ]
        
        results = []
        for cmd in test_commands:
            result = self.analyze_command(cmd)
            results.append({
                "command": cmd,
                "intent": result.intent,
                "entities": result.entities,
                "confidence": result.confidence,
                "success": result.confidence > 0.5
            })
        
        return results
    
    def get_commands_for_context(self, context: str) -> List[str]:
        """특정 컨텍스트에서 사용 가능한 명령어들 반환"""
        context_key = self._map_context_to_key(context)
        priority_intents = self.CONTEXT_PRIORITY.get(context_key, [])
        
        commands = []
        for intent in priority_intents:
            if intent in self.KEYWORD_MAPPING:
                # 각 의도의 대표 키워드들 반환
                keywords = self.KEYWORD_MAPPING[intent]
                commands.extend(keywords[:2])  # 처음 2개만
        
        return commands
    
    def analyze_command_batch(self, commands: List[str], context: str = "default") -> List[SpeechRecognitionResponse]:
        """여러 명령어 배치 분석"""
        return [self.analyze_command(cmd, context) for cmd in commands]
    
    def get_intent_statistics(self) -> Dict[str, Any]:
        """의도 분석 통계"""
        total_intents = len(self.KEYWORD_MAPPING)
        footstep_intents = len([k for k in self.KEYWORD_MAPPING.keys() if k.startswith('FOOTSTEP_')])
        
        return {
            'total_intents': total_intents,
            'footstep_intents': footstep_intents,
            'general_intents': total_intents - footstep_intents,
            'total_keywords': sum(len(v) for v in self.KEYWORD_MAPPING.values()),
            'kalman_filter_support': True,
            'context_support': len(self.CONTEXT_PRIORITY)
        }