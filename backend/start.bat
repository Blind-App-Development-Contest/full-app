@echo off

REM 루트 디렉토리로 이동
cd /d %~dp0\..

REM 가상환경 활성화
call venv\Scripts\activate.bat

REM FastAPI 실행
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
