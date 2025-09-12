"""
음성 속도 변환 유틸리티 모듈
다양한 형식의 속도 값을 구글 TTS의 speaking_rate(0.25 ~ 4.0)로 통일하여 변환
전체 시스템에서 일관된 음성 속도 처리를 위한 단일 소스
"""

from typing import Union, Literal
import logging

logger = logging.getLogger(__name__)

# Google TTS API의 speaking_rate 유효 범위
GOOGLE_TTS_MIN_RATE = 0.25
GOOGLE_TTS_MAX_RATE = 4.0

# 기본 속도 설정
DEFAULT_SPEED = 1.0

# 입력 타입 정의
SpeedInputType = Literal['multiplier', 'percentage', 'level', 'db_percent']


def convert_to_google_tts_speed(
    speed_value: Union[int, float, str],
    input_type: SpeedInputType = 'multiplier',
    default_speed: float = DEFAULT_SPEED
) -> float:
    """
    다양한 형식의 속도 값을 구글 TTS의 speaking_rate(0.25 ~ 4.0)로 변환합니다.

    Args:
        speed_value: 변환할 속도 값 (int, float, 또는 str).
        input_type: 입력 값의 종류.
                   - 'multiplier': 배속 (예: 1.5)
                   - 'percentage': 퍼센트 (예: 150)
                   - 'level': 1-10 단계 (예: 7)
                   - 'db_percent': DB에 저장된 퍼센트 정수값 (예: 120)
        default_speed: 변환 실패 시 반환할 기본 속도.

    Returns:
        float: 구글 TTS API의 speaking_rate로 변환된 값 (0.25-4.0 범위).

    Examples:
        >>> convert_to_google_tts_speed(1.5, 'multiplier')
        1.5
        >>> convert_to_google_tts_speed(150, 'percentage') 
        1.5
        >>> convert_to_google_tts_speed(5, 'level')
        1.17
        >>> convert_to_google_tts_speed(120, 'db_percent')
        1.2
    """
    try:
        # 입력 타입에 따라 배속(rate)으로 변환
        if input_type == 'multiplier':
            # 입력값이 이미 배속인 경우
            rate = float(speed_value)
            
        elif input_type == 'percentage':
            # 입력값이 퍼센트(%)인 경우 (예: 150 -> 1.5)
            rate = float(speed_value) / 100.0
            
        elif input_type == 'db_percent':
            # DB에 저장된 퍼센트 정수값인 경우 (voice.py에서 사용)
            rate = float(speed_value) / 100.0
            
        elif input_type == 'level':
            # 입력값이 1~10 단계인 경우 (선형적으로 0.5x ~ 2.0x에 매핑)
            level = int(speed_value)
            if not (1 <= level <= 10):
                logger.warning(f"단계(level) '{level}'이 유효 범위(1~10)를 벗어남")
                # 범위 밖이면 최소/최대값으로 고정
                level = max(1, min(10, level))
            
            # 1단계 -> 0.5배속, 10단계 -> 2.0배속으로 선형 변환
            min_rate_for_level = 0.5
            max_rate_for_level = 2.0
            rate = min_rate_for_level + (level - 1) * (max_rate_for_level - min_rate_for_level) / 9.0

        else:
            logger.error(f"지원하지 않는 입력 타입: '{input_type}'")
            return default_speed

        # 최종적으로 구글 TTS의 유효 범위(0.25 ~ 4.0) 내에 있는지 확인하고 조정
        final_rate = max(GOOGLE_TTS_MIN_RATE, min(GOOGLE_TTS_MAX_RATE, rate))
        
        if abs(rate - final_rate) > 0.01:  # 부동소수점 비교
            logger.info(f"계산된 속도 {rate:.2f}x가 유효 범위를 벗어나 {final_rate:.2f}x로 조정됨")

        return round(final_rate, 2)  # 소수점 2자리까지 반올림하여 반환

    except (ValueError, TypeError) as e:
        logger.error(f"숫자 변환 불가능한 값: '{speed_value}', 오류: {e}")
        return default_speed
    except Exception as e:
        logger.error(f"음성 속도 변환 중 예상치 못한 오류: {e}")
        return default_speed


def validate_google_tts_speed(speed: float) -> bool:
    """
    Google TTS speaking_rate 값이 유효한지 확인합니다.
    
    Args:
        speed: 검증할 속도 값
        
    Returns:
        bool: 유효한 범위(0.25-4.0) 내에 있으면 True
    """
    return GOOGLE_TTS_MIN_RATE <= speed <= GOOGLE_TTS_MAX_RATE


def normalize_speed_for_frontend(speed: float) -> float:
    """
    백엔드 속도값을 프론트엔드에서 사용할 수 있는 범위로 정규화합니다.
    현재는 동일한 범위를 사용하므로 그대로 반환하되, 향후 확장성을 위해 함수로 분리.
    
    Args:
        speed: 정규화할 속도 값
        
    Returns:
        float: 프론트엔드용으로 정규화된 속도 값
    """
    return max(GOOGLE_TTS_MIN_RATE, min(GOOGLE_TTS_MAX_RATE, speed))


def get_speed_level_from_multiplier(speed: float) -> int:
    """
    배속 값을 1-10 단계로 변환합니다.
    
    Args:
        speed: 배속 값 (0.25-4.0)
        
    Returns:
        int: 1-10 단계 값
    """
    # 0.5-2.0 범위를 1-10 단계로 역변환
    # 범위를 0.5-2.0으로 제한 후 단계 계산
    clamped_speed = max(0.5, min(2.0, speed))
    level = round(1 + (clamped_speed - 0.5) * 9.0 / (2.0 - 0.5))
    return max(1, min(10, level))


# 하위 호환성을 위한 레거시 함수들
def speed_float_to_int_percent(speed: float) -> int:
    """
    배속을 DB 저장용 정수 퍼센트로 변환 (voice.py 호환성)
    
    Args:
        speed: 배속 값
        
    Returns:
        int: 퍼센트 정수 (예: 1.5 -> 150)
    """
    return int(round(speed * 100))


def int_percent_to_speed_float(percent: Union[int, None]) -> float:
    """
    DB의 퍼센트 정수를 배속으로 변환 (voice.py 호환성)
    
    Args:
        percent: 퍼센트 정수값 (None이면 100%로 간주)
        
    Returns:
        float: 배속 값
    """
    return (percent if percent is not None else 100) / 100.0


# 시스템 전체에서 사용할 수 있는 편의 함수들
def get_default_speed() -> float:
    """시스템 기본 음성 속도를 반환합니다."""
    return DEFAULT_SPEED


def get_speed_range() -> tuple[float, float]:
    """시스템에서 지원하는 음성 속도 범위를 반환합니다."""
    return (GOOGLE_TTS_MIN_RATE, GOOGLE_TTS_MAX_RATE)


if __name__ == "__main__":
    # 함수 사용 예제 및 테스트
    
    print("=== 음성 속도 변환 유틸리티 테스트 ===\n")
    
    # 1. 배속(multiplier) 값을 직접 변환
    speed_1 = convert_to_google_tts_speed(1.5, 'multiplier')
    print(f"입력 (배속: 1.5) -> 변환 결과: {speed_1}x")
    
    speed_2 = convert_to_google_tts_speed(5.0, 'multiplier')  # 범위를 벗어나는 경우
    print(f"입력 (배속: 5.0) -> 변환 결과: {speed_2}x")
    
    # 2. 퍼센트(percentage) 값을 변환
    speed_3 = convert_to_google_tts_speed(80, 'percentage')
    print(f"입력 (퍼센트: 80%) -> 변환 결과: {speed_3}x")
    
    # 3. 1~10 단계(level) 값을 변환
    speed_4 = convert_to_google_tts_speed(1, 'level')  # 가장 느린 단계
    print(f"입력 (단계: 1) -> 변환 결과: {speed_4}x")
    
    speed_5 = convert_to_google_tts_speed(10, 'level')  # 가장 빠른 단계
    print(f"입력 (단계: 10) -> 변환 결과: {speed_5}x")
    
    speed_6 = convert_to_google_tts_speed(5, 'level')  # 중간 단계
    print(f"입력 (단계: 5) -> 변환 결과: {speed_6}x")
    
    # 4. DB 퍼센트 값을 변환
    speed_7 = convert_to_google_tts_speed(120, 'db_percent')
    print(f"입력 (DB 퍼센트: 120) -> 변환 결과: {speed_7}x")
    
    # 5. 잘못된 입력값 처리
    speed_8 = convert_to_google_tts_speed('느리게', 'multiplier')
    print(f"입력 (잘못된 값) -> 변환 결과: {speed_8}x (기본값)")
    
    # 6. 유효성 검증
    print(f"\n속도 1.5 유효성: {validate_google_tts_speed(1.5)}")
    print(f"속도 5.0 유효성: {validate_google_tts_speed(5.0)}")
    
    # 7. 단계 역변환
    level = get_speed_level_from_multiplier(1.5)
    print(f"\n배속 1.5 -> 단계: {level}")