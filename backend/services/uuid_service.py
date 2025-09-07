import uuid
from pathlib import Path
import requests

UUID_FILE = Path.home() / ".my_app_uuid.txt"
NAME_FILE = Path.home() / ".my_app_user_name.txt"
SERVER_URL = "https://aeye-backend-app-jp.azurewebsites.net"

def get_or_create_uuid() -> str:
    if UUID_FILE.exists():
        return UUID_FILE.read_text().strip()
    new_id = str(uuid.uuid4())
    UUID_FILE.write_text(new_id)
    return new_id

def get_or_ask_name() -> str:
    if NAME_FILE.exists():
        return NAME_FILE.read_text().strip()
    name = input("이름을 입력하세요: ").strip()
    if not name:
        name = "사용자"  # 비어있으면 기본값
    NAME_FILE.write_text(name)
    return name

def register_to_server(app_uuid: str, user_name: str | None):
    payload = {"app_uuid": app_uuid, "user_name": user_name}
    r = requests.post(SERVER_URL, json=payload, timeout=10)
    print("STATUS:", r.status_code, "BODY:", r.text)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    app_uuid = get_or_create_uuid()
    user_name = get_or_ask_name()
    print("Local App UUID:", app_uuid)
    print("Local User Name:", user_name)

    res = register_to_server(app_uuid, user_name)
    print("Server Response:", res)
