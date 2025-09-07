# Python 3.10.13 버전을 기반으로 이미지 생성
FROM python:3.10.13-slim

# 작업 디렉토리 설정
WORKDIR /app

# 필요한 시스템 라이브러리 설치 (OpenCV 등에서 사용)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 먼저 복사하여 캐시 활용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 소스코드 및 모델 파일 복사
COPY . .

# 디버깅 스크립트 복사 및 실행 권한 부여
COPY start.sh .
RUN chmod +x ./start.sh

# uvicorn을 사용하여 FastAPI 앱 실행
# 0.0.0.0으로 바인딩해야 Render에서 외부 요청을 받을 수 있음
CMD ["./start.sh"]
