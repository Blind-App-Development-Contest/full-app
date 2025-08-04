#!/bin/bash

# 현재 스크립트 위치 기준으로 루트 경로로 이동
cd "$(dirname "$0")/.."

# 가상환경 활성화
source venv/bin/activate

# FastAPI 실행
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
