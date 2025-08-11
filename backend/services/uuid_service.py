import uuid
import os
from pathlib import Path
import requests

# 로컬 저장 경로
UUID_FILE = Path.home() / ".my_app_uuid.txt"

# 서버 API 엔드포인트
SERVER_URL = "http://localhost:8000/users/register"

def get_or_create_uuid():
    # 최초 실행 시 UUID 생성, 이후엔 기존 값 재사용
    if UUID_FILE.exists():
        return UUID_FILE.read_text().strip()
    new_uuid = str(uuid.uuid4())
    UUID_FILE.write_text(new_uuid)
    return new_uuid

def register_to_server(app_uuid, user_name=None):
    # 서버에 UUID 등록
    payload = {"app_uuid": app_uuid, "user_name": user_name}
    res = requests.post(SERVER_URL, json=payload)
    res.raise_for_status()
    return res.json()

if __name__ == "__main__":
    # 1) UUID 가져오기 (없으면 생성)
    app_uuid = get_or_create_uuid()
    print(f"Local App UUID: {app_uuid}")

    # 2) 서버에 등록 요청
    result = register_to_server(app_uuid, "테스트유저")
    print(f"Server Response: {result}")
