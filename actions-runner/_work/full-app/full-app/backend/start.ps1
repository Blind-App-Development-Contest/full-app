# 현재 스크립트 위치 기준으로 루트 폴더로 이동
Set-Location -Path "$PSScriptRoot\.."

# 가상환경 활성화
.\venv\Scripts\Activate.ps1

# FastAPI 실행
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
