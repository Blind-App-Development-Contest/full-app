import re
import logging
from typing import Dict, List, Any, Tuple, Optional
from models.recognition_schemas import SpeechRecognitionResponse
from config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class SpeechAnalyzer:
    """음성 명령 분석 클래스"""
    
    # 키워드 매핑 테이블 (사용자 친화적 명령어)
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
        
        # ===== 사용자 친화적 보폭 측정 명령어들 =====
        'FOOTSTEP_MEASUREMENT_START': [
            '보폭 측정 시작', '보폭측정시작', '보폭 측정', '보폭측정',
            '측정 시작', '측정시작', '보폭 재측정', '보폭재측정',
            '거리 측정', '거리측정', '걸음 측정', '걸음측정',
            '내 보폭 알고 싶어', '보폭 알아보자', '보폭 다시 재어줘'
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
        ],
        
        # ===== 음성 안내 응답 패턴 =====
        'DISTANCE_RESPONSE': [
            # "거리를 알려주세요" 안내에 대한 응답
            '5미터', '10미터', '거리는 8미터', '3미터 정도',
            '대충 6미터', '약 12미터', '한 15미터 정도',
            '7미터 걸었어', '미터를 재보니까 9미터',
            '얼마나 걸었을까 20미터', '거리는 대략 11미터'
        ],
        'STEP_COUNT_RESPONSE': [
            # "걸음 수를 알려주세요" 안내에 대한 응답
            '15걸음', '20걸음', '걸음은 12걸음', '8걸음 정도',
            '대충 25걸음', '약 18걸음', '한 30걸음 정도',
            '22걸음 걸었어', '걸음을 세보니까 16걸음',
            '14번 걷기', '걸음 수는 대략 19걸음'
        ],
        'CONFIRMATION_RESPONSE': [
            # "맞습니까?" 안내에 대한 응답
            '맞아', '맞습니다', '맞아요', '맞가요', '예',
            '그렇습니다', '그래요', '그래', '맞다', '맞을거야',
            '그렇지', '응', '어', '응 맞아', '응 그래',
            '좋아', '좋습니다', '좋아요', '맞네요'
        ],
        'CORRECTION_RESPONSE': [
            # "맞습니까?" 안내에 대한 수정 응답
            '아니야', '아니어', '아니예요', '아닙니다',
            '틀렸어', '틀렸어요', '틀렸습니다', '틀린 것 같아',
            '다시', '다시 해줘', '다시 말할게', '아니 다르다',
            '다른데', '그게 아니야', '바꿔줄게', '수정'
        ],
        'READY_RESPONSE': [
            # "준비되셨습니까?" 안내에 대한 응답
            '준비됐어', '준비됐어요', '준비됐습니다', '됐어',
            '됐어요', '됐습니다', '좋아', '좋습니다',
            '시작해', '시작해요', '가자', '가요',
            '준비 완료', '준비 끝', '다 됐어'
        ],
        'REPEAT_REQUEST': [
            # 재생 요청 패턴
            '다시', '다시 말해줘', '다시 들려줘', '한번 더',
            '못 들었어', '못 들었어요', '잘 안 들려',
            '뭐라고?', '뭐?', '어?', '예?',
            '다시 한번', '다시 말씀드려주세요',
            '지금 말슴한 거 다시'
        ],
        'HELP_REQUEST': [
            # 도움 요청 패턴
            '도움말', '도움', '도와줘', '도와주세요',
            '어떻게 해', '어떻게 하는 거야', '어떻게 하면 돼',
            '모르겠어', '모르겠어요', '모르겠습니다',
            '사용법', '사용법 알려주세요', '명령어',
            '헬프', '헤프', '도움말 지원'
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
        'awaiting_distance': [
            'DISTANCE_RESPONSE',
            'FOOTSTEP_MEASUREMENT_CANCEL',
            'HELP_REQUEST',
            'REPEAT_REQUEST'
        ],
        'awaiting_step_count': [
            'STEP_COUNT_RESPONSE',
            'FOOTSTEP_MEASUREMENT_CANCEL',
            'HELP_REQUEST',
            'REPEAT_REQUEST'
        ],
        'awaiting_confirmation': [
            'CONFIRMATION_RESPONSE',
            'CORRECTION_RESPONSE',
            'HELP_REQUEST',
            'REPEAT_REQUEST'
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
        음성 텍스트를 분석하여 의도와 엔티티를 추출 (거리 기반 측정 지원)
        
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
        # 음성 안내 응답 패턴들 (높은 우선순위)
        voice_guidance_patterns = [
            # 이름만 입력하는 경우 (최우선 처리)
            (r'^[가-힣]{1,10}$', 'NAME_INPUT', 0.99),  # 한글 1-10자만
            (r'^[가-힣]+\s+[가-힣]+$', 'NAME_INPUT', 0.98),  # 성+이름 형태
            
            # 거리 입력 응답
            (r'^\d+\s*미터(?!.*걸음)', 'DISTANCE_RESPONSE', 0.95),
            (r'거리는.*\d+.*미터', 'DISTANCE_RESPONSE', 0.90),
            (r'대충.*\d+.*미터', 'DISTANCE_RESPONSE', 0.88),
            (r'약.*\d+.*미터', 'DISTANCE_RESPONSE', 0.88),
            (r'한.*\d+.*미터.*정도', 'DISTANCE_RESPONSE', 0.85),
            
            # 걸음수 입력 응답
            (r'^\d+\s*걸음(?!.*미터)', 'STEP_COUNT_RESPONSE', 0.95),
            (r'걸음은.*\d+', 'STEP_COUNT_RESPONSE', 0.90),
            (r'대충.*\d+.*걸음', 'STEP_COUNT_RESPONSE', 0.88),
            (r'약.*\d+.*걸음', 'STEP_COUNT_RESPONSE', 0.88),
            (r'\d+번.*걷기', 'STEP_COUNT_RESPONSE', 0.85),
            # 숫자만 입력하는 경우 (걸음수 컨텍스트에서)
            (r'^\d+$', 'STEP_COUNT_RESPONSE', 0.92),  # "15", "20" 등 순수 숫자
            # 한국어 숫자 표현
            (r'^(하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열|십|스무|서른|마흔|쉰)$', 'STEP_COUNT_RESPONSE', 0.90),
            (r'^(일|이|삼|사|오|육|칠|팔|구|십)$', 'STEP_COUNT_RESPONSE', 0.88),  # 한자어 숫자
            
            # 확인 응답
            (r'^맞아$|^맞습니다$|^예$', 'CONFIRMATION_RESPONSE', 0.95),
            (r'그렇습니다|그래요|맞아요', 'CONFIRMATION_RESPONSE', 0.90),
            (r'좋아|좋습니다|응.*맞아', 'CONFIRMATION_RESPONSE', 0.85),
            
            # 수정 요청
            (r'^아니$|^아니야$|^아니어$', 'CORRECTION_RESPONSE', 0.95),
            (r'틀렸어|틀렸습니다|아닙니다', 'CORRECTION_RESPONSE', 0.90),
            (r'다시.*해|다시.*말할게', 'CORRECTION_RESPONSE', 0.88),
            
            # 준비 완료
            (r'준비.*됐|됐어|됐습니다', 'READY_RESPONSE', 0.95),
            (r'시작해|가자|가요', 'READY_RESPONSE', 0.90),
            (r'준비.*완료|준비.*끝', 'READY_RESPONSE', 0.85),
            
            # 재생 요청
            (r'^다시$|다시.*말해', 'REPEAT_REQUEST', 0.95),
            (r'못.*들었|잘.*안.*들려', 'REPEAT_REQUEST', 0.90),
            (r'^뭐\?$|^예\?$|^어\?$', 'REPEAT_REQUEST', 0.85),
            
            # 도움 요청
            (r'도움말|도와줘|도움', 'HELP_REQUEST', 0.95),
            (r'어떻게.*해|모르겠', 'HELP_REQUEST', 0.88),
            (r'사용법|명령어|헬프', 'HELP_REQUEST', 0.85),
        ]
        
        # 보폭 측정 패턴들
        footstep_patterns = [
            (r'보폭.*측정.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.95),
            (r'측정.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'보폭.*시작', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'거리.*측정', 'FOOTSTEP_MEASUREMENT_START', 0.90),
            (r'걸음.*측정', 'FOOTSTEP_MEASUREMENT_START', 0.90),
            (r'내.*보폭.*알고.*싶', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'보폭.*알아보', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            (r'보폭.*다시.*재', 'FOOTSTEP_MEASUREMENT_START', 0.85),
            
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
        
        all_patterns = voice_guidance_patterns + footstep_patterns + other_patterns
        
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
            'setup': 'setup_step_length',
            'awaiting_distance': 'awaiting_distance',
            'awaiting_step_count': 'awaiting_step_count',
            'awaiting_confirmation': 'awaiting_confirmation',
            'distance_input_mode': 'awaiting_distance',
            'step_count_input_mode': 'awaiting_step_count'
        }
        return context_mapping.get(context, 'default')
    
    def _extract_entities(self, intent: str, text: str) -> Dict[str, Any]:
        """의도에 따른 엔티티 추출"""
        entities = {'raw_text': text}
        
        # 이름 입력 엔티티 처리 (최우선)
        if intent == 'NAME_INPUT':
            # 이름 정리 (불필요한 단어 제거)
            cleaned_name = text.replace("내 이름은", "").replace("이름은", "").replace("저는", "").replace("입니다", "").replace("예요", "").replace("이에요", "").strip()
            entities.update({
                'user_name': cleaned_name,
                'response_type': 'name_input',
                'category': 'user_setup',
                'action': 'set_user_name'
            })
        
        # 음성 안내 응답 엔티티 처리
        elif intent in ['DISTANCE_RESPONSE', 'STEP_COUNT_RESPONSE']:
            entities.update({
                'response_type': 'measurement_input',
                'category': 'voice_guidance_response'
            })

            # 숫자 추출
            import re
            numbers = re.findall(r'\d+(?:\.\d+)?', text)

            if intent == 'DISTANCE_RESPONSE':
                if numbers:
                    try:
                        distance_value = float(numbers[0])
                        entities['distance_meters'] = distance_value
                        entities['action'] = 'input_distance'
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Distance 숫자 변환 실패: {numbers[0]}, 오류: {e}")
                else:
                    # 한국어 숫자 변환 시도
                    korean_number = self._convert_korean_to_number(text)
                    if korean_number is not None:
                        entities['distance_meters'] = float(korean_number)
                        entities['action'] = 'input_distance'

            elif intent == 'STEP_COUNT_RESPONSE':
                if numbers:
                    try:
                        step_count_value = int(numbers[0])
                        entities['step_count'] = step_count_value
                        entities['action'] = 'input_step_count'
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Step count 숫자 변환 실패: {numbers[0]}, 오류: {e}")
                else:
                    # 한국어 숫자 변환 시도
                    korean_number = self._convert_korean_to_number(text)
                    if korean_number is not None:
                        entities['step_count'] = korean_number
                        entities['action'] = 'input_step_count'
                    else:
                        # 걸음수를 추출할 수 없는 경우 에러 처리
                        logger.warning(f"걸음수 추출 실패: '{text}' - 숫자나 한국어 숫자를 찾을 수 없음")
                        entities['action'] = 'input_step_count_failed'
                        entities['error'] = 'step_count_extraction_failed'
                
        elif intent in ['CONFIRMATION_RESPONSE', 'CORRECTION_RESPONSE', 'READY_RESPONSE']:
            entities.update({
                'response_type': 'user_feedback',
                'category': 'voice_guidance_response'
            })
            
            if intent == 'CONFIRMATION_RESPONSE':
                entities['action'] = 'confirm'
            elif intent == 'CORRECTION_RESPONSE':
                entities['action'] = 'correct'
            elif intent == 'READY_RESPONSE':
                entities['action'] = 'ready'
                
        elif intent in ['REPEAT_REQUEST', 'HELP_REQUEST']:
            entities.update({
                'response_type': 'assistance_request',
                'category': 'voice_guidance_response'
            })
            
            if intent == 'REPEAT_REQUEST':
                entities['action'] = 'repeat'
            elif intent == 'HELP_REQUEST':
                entities['action'] = 'help'
        
        # 보폭 측정 관련 엔티티
        elif intent.startswith('FOOTSTEP_'):
            entities.update({
                'measurement_type': 'distance_based',
                'category': 'footstep_measurement'
            })
            
            if intent == 'FOOTSTEP_MEASUREMENT_START':
                entities['action'] = 'start_measurement'
                
                # 사용자 의도 감지
                if any(keyword in text for keyword in ['다시', '재측정', '알고 싶', '알아보']):
                    entities['remeasurement_intent'] = "true"
                    
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
                'measurement_type': 'distance_based' if intent.startswith('FOOTSTEP_') else None
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
            
            # 음성 안내 응답 테스트
            "거리는 5미터",
            "10미터 걸었어",
            "거리를 재보니까 8미터",
            "걸음은 15걸음",
            "20걸음 걸었어",
            "걸음을 세보니까 12걸음",
            "맞아",
            "맞습니다",
            "그래요",
            "아니야",
            "틀렸어",
            "다시 해줘",
            "준비됐어",
            "시작해",
            "다시 말해줘",
            "못 들었어",
            "도움말",
            "어떻게 해",
            
            # 거리 기반 보폭 측정 명령어들
            "보폭 측정 시작",
            "보폭측정시작", 
            "측정 시작",
            "거리 측정",
            "걸음 측정",
            "5미터 걸었어",
            "10걸음 걸었어",
            "거리는 3미터",
            "걸음은 8걸음",
            "계산해줘",
            "보폭 계산",
            "보폭은 65센티",
            "70cm야",
            "측정 완료",
            "입력 완료",
            "완료",
            "끝",
            "측정 취소",
            "취소",
            "중단",
            "보폭 상태",
            "현재 보폭",
            "상태",
            
            # 복합/모호한 명령어들
            "5미터에 12걸음 걸었어",
            "거리 10미터 걸음수 18",
            "보폭은 72센티미터야",
            "계산 결과 알려줘",
            "얼마나 나와?",
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
            'distance_based_measurement': True,
            'context_support': len(self.CONTEXT_PRIORITY)
        }
    
    def _convert_korean_to_number(self, text: str) -> Optional[int]:
        """한국어 숫자를 아라비아 숫자로 변환"""
        # 한국어 숫자 매핑 (순우리말)
        korean_numbers = {
            '하나': 1, '둘': 2, '셋': 3, '넷': 4, '다섯': 5,
            '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
            '스무': 20, '서른': 30, '마흔': 40, '쉰': 50
        }
        
        # 한자어 숫자 매핑
        chinese_numbers = {
            '일': 1, '이': 2, '삼': 3, '사': 4, '오': 5,
            '육': 6, '칠': 7, '팔': 8, '구': 9, '십': 10
        }
        
        # 전체 텍스트 정리
        text = text.strip()
        
        # 순우리말 숫자 검사
        if text in korean_numbers:
            return korean_numbers[text]
        
        # 한자어 숫자 검사
        if text in chinese_numbers:
            return chinese_numbers[text]
        
        # 복합 한자어 숫자 처리 (예: 십오, 이십, 삼십)
        if '십' in text and len(text) <= 3:
            if text == '십':
                return 10
            elif text.startswith('십'):
                # 십일, 십이, 십삼 등
                suffix = text[1:]
                if suffix in chinese_numbers:
                    return 10 + chinese_numbers[suffix]
            elif text.endswith('십'):
                # 이십, 삼십 등
                prefix = text[:-1]
                if prefix in chinese_numbers:
                    return chinese_numbers[prefix] * 10
        
        return None