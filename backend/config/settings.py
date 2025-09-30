import os
from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache

class Settings(BaseSettings):
    """앱 설정 관리"""

    # 서버 설정
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 8000))
    DEBUG: bool = False

    # CORS 설정 - 보안 강화
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000", 
        "http://localhost:8080",
        "http://127.0.0.1:8080"
    ]  # Flutter 개발 서버 및 로컬 테스트용

    # 음성/검색 설정
    MAX_FILE_SIZE_MB: int = 50
    SUPPORTED_AUDIO_TYPES: List[str] = ["audio/", "application/octet-stream"]
    DEFAULT_SEARCH_RADIUS: int = 500
    POI_SEARCH_RADIUS: int = 1000

    # API 키들 (환경 변수 매핑)
    google_tts_api_key: Optional[str] = None
    google_maps_api_key: Optional[str] = None  # ✅ 서버에서 호출할 Google Maps/Directions/Places용 키
    openai_api_key: Optional[str] = None
    
    # Mapbox API (도보 길찾기용)
    mapbox_access_token: Optional[str] = None
    
    # Naver Cloud Platform API (지오코딩용)
    naver_client_id: Optional[str] = None
    naver_client_secret: Optional[str] = None

    # 데이터베이스 설정
    db_url: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # 추가 필드 허용 (기존 환경 변수 호환성을 위해)
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    """설정 싱글톤 인스턴스 반환"""
    return Settings()
