#!/usr/bin/env python3
"""
음성 설정 시스템 자동 테스트 스크립트
"""

import requests
import json
import time
import sys
from typing import Dict, Any

# 설정
BASE_URL = "http://localhost:8000"
DELAY_BETWEEN_REQUESTS = 0.5  # 요청 간 대기 시간 (초)

class Colors:
    """터미널 색상"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text: str):
    """헤더 출력"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE} {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")

def print_step(step: str, text: str):
    """단계별 출력"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}[{step}]{Colors.END} {text}")

def print_success(text: str):
    """성공 메시지"""
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_error(text: str):
    """에러 메시지"""
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_warning(text: str):
    """경고 메시지"""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def check_server_connection():
    """서버 연결 확인"""
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        if response.status_code == 200:
            print_success("서버 연결 성공")
            return True
        else:
            print_error(f"서버 응답 오류: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print_error("서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
        print(f"{Colors.YELLOW}서버 실행 명령: python main.py{Colors.END}")
        return False
    except Exception as e:
        print_error(f"연결 확인 중 오류: {e}")
        return False

def test_speech_action(command_text: str, step_name: str = None) -> Dict[str, Any]:
    """음성 명령 테스트"""
    print_step("음성 명령", f"'{command_text}'")
    
    url = f"{BASE_URL}/api/users/speech/action"
    data = {
        "command_text": command_text,
        "execute_immediately": True
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # 응답 정보 출력
        intent = result.get('intent', 'Unknown')
        execution = result.get('execution', {})
        status = execution.get('status', 'Unknown')
        message = execution.get('message', 'No message')
        
        print(f"   🎯 의도: {Colors.PURPLE}{intent}{Colors.END}")
        print(f"   📋 상태: {Colors.GREEN if status == 'success' else Colors.RED}{status}{Colors.END}")
        print(f"   💬 응답: {message}")
        
        # 설정 데이터가 있으면 출력
        data_info = execution.get('data', {})
        if 'setup_step' in data_info:
            print(f"   📍 다음 단계: {Colors.CYAN}{data_info['setup_step']}{Colors.END}")
        if 'progress' in data_info:
            print(f"   📈 진행률: {Colors.YELLOW}{data_info['progress']}{Colors.END}")
        
        if status == 'success':
            print_success(f"단계 완료: {step_name or command_text}")
        else:
            print_warning(f"단계 대기 중: {message}")
        
        return result
        
    except requests.exceptions.RequestException as e:
        print_error(f"요청 실패: {e}")
        return {}
    except json.JSONDecodeError as e:
        print_error(f"JSON 파싱 실패: {e}")
        return {}

def test_setup_status() -> Dict[str, Any]:
    """설정 상태 확인"""
    url = f"{BASE_URL}/api/users/action/setup/status"
    
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        result = response.json()
        
        print_step("설정 상태", "현재 상태 확인")
        print(f"   🔧 설정 완료: {Colors.GREEN if result['setup_complete'] else Colors.YELLOW}{result['setup_complete']}{Colors.END}")
        print(f"   📍 현재 단계: {Colors.CYAN}{result.get('current_step', 'Unknown')}{Colors.END}")
        print(f"   🎮 현재 모드: {Colors.PURPLE}{result.get('current_mode', 'Unknown')}{Colors.END}")
        print(f"   📈 진행률: {Colors.YELLOW}{result.get('progress', 'Unknown')}{Colors.END}")
        
        # 사용자 설정 출력
        user_settings = result.get('user_settings', {})
        if any(value for value in user_settings.values() if value):
            print(f"   👤 사용자 설정:")
            for key, value in user_settings.items():
                if value:
                    print(f"      • {key}: {Colors.WHITE}{value}{Colors.END}")
        
        return result
        
    except Exception as e:
        print_error(f"상태 확인 실패: {e}")
        return {}

def test_setup_reset():
    """설정 초기화 테스트"""
    print_step("설정 초기화", "설정을 초기 상태로 리셋")
    
    url = f"{BASE_URL}/api/users/action/setup/reset"
    
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        result = response.json()
        
        if result.get('success', False):
            print_success("설정 초기화 완료")
        else:
            print_error("설정 초기화 실패")
        
        return result
        
    except Exception as e:
        print_error(f"초기화 실패: {e}")
        return {}

def run_full_setup_test():
    """전체 설정 테스트 실행"""
    print_header("🚀 음성 설정 시스템 자동 테스트")
    
    # 서버 연결 확인
    if not check_server_connection():
        return False
    
    # 설정 초기화
    test_setup_reset()
    time.sleep(DELAY_BETWEEN_REQUESTS)
    
    # 초기 상태 확인
    print_header("📋 초기 상태 확인")
    test_setup_status()
    
    # 설정 단계별 테스트
    setup_commands = [
        ("시작", "설정 시작"),
        ("내 이름은 김철수입니다", "사용자 이름 입력"),
        ("보폭 측정 시작", "보폭 측정"),
        ("여성", "음성 종류 선택"),
        ("보통", "음성 속도 선택"),
        ("어머니", "보호자 이름 입력"),
        ("010-1234-5678", "보호자 전화번호 입력"),
        ("카메라 모드", "모드 선택")
    ]
    
    print_header("🎤 단계별 음성 명령 테스트")
    
    for i, (command, description) in enumerate(setup_commands, 1):
        print(f"\n{Colors.BOLD}--- {i}단계: {description} ---{Colors.END}")
        result = test_speech_action(command, description)
        
        if not result:
            print_error(f"{i}단계에서 실패. 테스트를 중단합니다.")
            return False
        
        time.sleep(DELAY_BETWEEN_REQUESTS)
    
    # 최종 상태 확인
    print_header("🎯 최종 설정 상태 확인")
    final_status = test_setup_status()
    
    # 테스트 결과 요약
    print_header("📊 테스트 결과 요약")
    
    if final_status.get('setup_complete', False):
        print_success("✨ 전체 설정 테스트 성공!")
        print(f"{Colors.GREEN}사용자: {final_status['user_settings'].get('user_name', 'Unknown')}{Colors.END}")
        print(f"{Colors.GREEN}모드: {final_status.get('current_mode', 'Unknown')}{Colors.END}")
        return True
    else:
        print_error("❌ 설정이 완료되지 않았습니다.")
        return False

def test_error_scenarios():
    """에러 시나리오 테스트"""
    print_header("🧪 에러 처리 테스트")
    
    error_tests = [
        ("", "빈 명령어"),
        ("알 수 없는 명령", "지원하지 않는 명령"),
        ("123456789", "숫자만 입력"),
        ("!@#$%^&*()", "특수문자만 입력")
    ]
    
    for command, description in error_tests:
        print_step("에러 테스트", f"{description}: '{command}'")
        result = test_speech_action(command, description)
        time.sleep(DELAY_BETWEEN_REQUESTS * 0.5)

def test_various_input_patterns():
    """다양한 입력 패턴 테스트"""
    print_header("🔄 다양한 입력 패턴 테스트")
    
    # 설정 초기화
    test_setup_reset()
    time.sleep(DELAY_BETWEEN_REQUESTS)
    
    pattern_tests = [
        # 이름 입력 다양한 패턴
        ("시작", "설정 시작"),
        ("저는 이영희입니다", "이름 패턴 1"),
        ("이름은 박민수에요", "이름 패턴 2"),
        ("내 이름 홍길동", "이름 패턴 3"),
    ]
    
    for command, description in pattern_tests:
        print_step("패턴 테스트", f"{description}: '{command}'")
        test_speech_action(command, description)
        time.sleep(DELAY_BETWEEN_REQUESTS * 0.5)

def test_api_endpoints():
    """API 엔드포인트 테스트"""
    print_header("🔌 API 엔드포인트 테스트")
    
    endpoints = [
        ("GET", "/", "메인 페이지"),
        ("GET", "/api/users/action/setup/status", "설정 상태"),
        ("GET", "/api/users/action/setup/progress", "설정 진행률"),
        ("GET", "/api/users/action/status", "시스템 상태"),
        ("GET", "/api/users/action/history", "실행 기록"),
        ("GET", "/api/users/speech/intents", "지원 명령어")
    ]
    
    for method, endpoint, description in endpoints:
        print_step("API 테스트", f"{method} {endpoint} - {description}")
        
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
            else:
                response = requests.post(f"{BASE_URL}{endpoint}", timeout=5)
            
            if response.status_code == 200:
                print_success(f"응답 성공 (상태: {response.status_code})")
            else:
                print_warning(f"응답 상태: {response.status_code}")
                
        except Exception as e:
            print_error(f"요청 실패: {e}")
        
        time.sleep(DELAY_BETWEEN_REQUESTS * 0.3)

def main():
    """메인 실행 함수"""
    print(f"{Colors.BOLD}{Colors.WHITE}🎤 음성 설정 시스템 자동 테스트 도구{Colors.END}")
    print(f"{Colors.CYAN}서버 주소: {BASE_URL}{Colors.END}")
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        
        if test_type == "full" or test_type == "setup":
            success = run_full_setup_test()
            sys.exit(0 if success else 1)
        
        elif test_type == "error":
            test_error_scenarios()
        
        elif test_type == "pattern":
            test_various_input_patterns()
        
        elif test_type == "api":
            test_api_endpoints()
        
        elif test_type == "all":
            print_header("🚀 전체 테스트 실행")
            success = run_full_setup_test()
            test_error_scenarios()
            test_various_input_patterns()
            test_api_endpoints()
            
            print_header("🏁 전체 테스트 완료")
            print_success("모든 테스트가 완료되었습니다!") if success else print_error("일부 테스트가 실패했습니다.")
        
        else:
            print(f"{Colors.RED}알 수 없는 테스트 타입: {test_type}{Colors.END}")
            print_usage()
    
    else:
        # 기본 실행: 전체 설정 테스트
        success = run_full_setup_test()
        sys.exit(0 if success else 1)

def print_usage():
    """사용법 출력"""
    print(f"\n{Colors.BOLD}사용법:{Colors.END}")
    print(f"  python test_setup.py [테스트타입]")
    print(f"\n{Colors.BOLD}테스트 타입:{Colors.END}")
    print(f"  {Colors.CYAN}full{Colors.END} 또는 {Colors.CYAN}setup{Colors.END} - 전체 설정 테스트 (기본값)")
    print(f"  {Colors.CYAN}error{Colors.END}                - 에러 처리 테스트")
    print(f"  {Colors.CYAN}pattern{Colors.END}              - 다양한 입력 패턴 테스트")
    print(f"  {Colors.CYAN}api{Colors.END}                  - API 엔드포인트 테스트")
    print(f"  {Colors.CYAN}all{Colors.END}                  - 모든 테스트 실행")
    print(f"\n{Colors.BOLD}예시:{Colors.END}")
    print(f"  python test_setup.py full")
    print(f"  python test_setup.py error")
    print(f"  python test_setup.py all")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}테스트가 사용자에 의해 중단되었습니다.{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print_error(f"예상치 못한 오류 발생: {e}")
        sys.exit(1)