#!/bin/bash

# 음성 설정 시스템 테스트 실행 스크립트

echo "🚀 음성 설정 시스템 테스트 시작"
echo "================================"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 함수 정의
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 1. 서버 실행 상태 확인
print_status "서버 연결 확인 중..."
response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)

if [ "$response" != "200" ]; then
    print_error "서버가 실행되지 않았습니다."
    print_status "서버를 백그라운드에서 시작합니다..."
    
    # 서버 백그라운드 실행
    cd backend 2>/dev/null || cd .
    python main.py &
    SERVER_PID=$!
    
    print_status "서버 시작 대기 중... (PID: $SERVER_PID)"
    sleep 5
    
    # 다시 연결 확인
    response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
    if [ "$response" != "200" ]; then
        print_error "서버 시작 실패"
        exit 1
    fi
    
    print_success "서버가 성공적으로 시작되었습니다."
    STARTED_SERVER=true
else
    print_success "서버가 이미 실행 중입니다."
    STARTED_SERVER=false
fi

# 2. 테스트 의존성 설치
print_status "테스트 의존성 확인 중..."
if ! python -c "import requests" 2>/dev/null; then
    print_status "requests 패키지 설치 중..."
    pip install requests
fi

# 3. 테스트 실행
print_status "테스트 실행 중..."

# 테스트 타입 확인
if [ $# -eq 0 ]; then
    TEST_TYPE="full"
else
    TEST_TYPE="$1"
fi

print_status "테스트 타입: $TEST_TYPE"

# Python 테스트 스크립트 실행
python test_setup.py "$TEST_TYPE"
TEST_RESULT=$?

# 4. 결과 출력
echo ""
echo "================================"
if [ $TEST_RESULT -eq 0 ]; then
    print_success "모든 테스트가 성공적으로 완료되었습니다! 🎉"
else
    print_error "일부 테스트가 실패했습니다. 로그를 확인해주세요."
fi

# 5. 서버 정리 (스크립트에서 시작한 경우)
if [ "$STARTED_SERVER" = true ]; then
    print_status "테스트용 서버를 종료합니다..."
    kill $SERVER_PID 2>/dev/null
    print_success "서버가 종료되었습니다."
fi

echo "테스트 완료."
exit $TEST_RESULT