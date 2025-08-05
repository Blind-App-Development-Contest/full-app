# full-app

## 기술 스택

| 분야            | 기술 스택                                                     |
|----------------|-------------------------------------------------------------|
| **모바일 앱**    | Flutter (Android / iOS)                                     |
| **객체 인식**    | YOLOv8 (Python)                                             |
| **깊이 추정**    | FastDepth                                                   |
| **음성 인식**    | Google Speech-to-Text                                       |
| **명령어 해석**   | GPT-4 API                                                  |
| **지도 서비스**   | Google Maps API                                            |
| **음성 출력**    | Google Text-to-Speech (TTS)                                 |
| **스트리밍 처리** | Google ML Kit (영상 프레임 실시간 처리)                           |
| **백엔드**       | FastAPI                                                    |
| **데이터베이스**  | PostgreSQL                                                  |
| **배포 환경**    | AWS (EC2, RDS 등)                                           |


## 디렉토리 구조(임시: 추후 구체화 예정)
FULL-APP/
├── .github/                  # GitHub Actions (CI 등 자동화)
│
├── backend/                  # FastAPI 백엔드
│   ├── main.py               # FastAPI 진입점
│   ├── start.sh              # macOS/Linux 실행 스크립트
│   ├── start.ps1             # Windows PowerShell 실행 스크립트
│   ├── start.bat             # Windows CMD 실행 스크립트
│   ├── api/                  # 라우터 분리 예정 (vision, command 등)
│   ├── services/             # YOLO, GPT, TTS 등 비즈니스 로직
│   ├── models/               # Pydantic or SQLAlchemy 모델
│   ├── db/                   # DB 연결, 세션 관리
│   ├── core/                 # 설정, 환경 변수 관리
│   └── tests/                # 테스트 코드
│
├── flutter_app/              # Flutter 모바일 앱
│   ├── android/
│   ├── ios/
│   ├── lib/
│   │   ├── main.dart         # 앱 진입점
│   │   ├── screens/          # UI 화면
│   │   ├── widgets/          # 공용 위젯
│   │   ├── services/         # 백엔드 API 호출
│   │   ├── models/           # 데이터 모델
│   │   ├── core/             # 앱 전역 설정 (상수, 스타일, 환경변수)
│   │   ├── routes/           # 화면 전환 경로 관리
│   │   └── providers/        # 상태 관리 (Provider, Riverpod 등)
│   ├── pubspec.yaml
│   └── ...
│
├── .gitignore                # Git 무시 설정
├── README.md                 # 프로젝트 설명서
├── requirements.txt          # FastAPI 백엔드 의존성
├── venv/                     # Python 가상환경 (Git에 포함 X)


## 백엔드 초기 가상환경 설정
(venv/ 폴더는 Git에 포함되지 않으며, 각 사용자가 로컬에서 직접 생성해야 함)

1. 파이썬 설치

2. 가상환경 생성
    Windows |   python -m venv venv
    macOS   |   python3 -m venv venv

3. 가상환경 이동
    Windows |   venv\Scripts\activate (cmd)
            |   	.\venv\Scripts\Activate.ps1 (powershell)
    macOS   |   source venv/bin/activate 

4. 의존성 설치
    Windows |   pip install -r requirements.txt
    macOS   |   pip install -r requirements.txt

5. FastAPI 서버 실행
    Windows |   backend\start.bat (cmd)
                .\backend\start.ps1 (powershell)
    macOS   |   ./backend/start.sh