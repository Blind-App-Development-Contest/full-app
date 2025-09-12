"""통합 음성 인식 서비스 - OpenAI Whisper 기반"""

import os
import httpx
import logging
from typing import Tuple
from fastapi import HTTPException, UploadFile
from dotenv import load_dotenv
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class SpeechService:
    """통합 음성 인식 서비스 - OpenAI Whisper 기반"""
    
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    
    def validate_audio_file(self, file: UploadFile) -> Tuple[bool, str]:
        """오디오 파일 타입 및 기본 검증"""
        try:
            # 파일 타입 검증
            if file.content_type and not any(file.content_type.startswith(t) for t in settings.SUPPORTED_AUDIO_TYPES):
                return False, f"지원하지 않는 파일 타입: {file.content_type}"
            
            # 파일명 검증
            if not file.filename:
                return False, "파일명이 없습니다"
            
            return True, "검증 성공"
            
        except Exception as e:
            logger.error(f"파일 검증 중 오류: {e}")
            return False, f"파일 검증 오류: {str(e)}"
    
    async def validate_and_read_audio(self, file: UploadFile) -> Tuple[bytes, float, str]:
        """오디오 파일 검증 및 읽기 통합 메서드"""
        logger.info(f"[STT] 파일 수신: {file.filename}, 타입: {file.content_type}")
        
        # 1. 파일 타입 검증
        is_valid, validation_message = self.validate_audio_file(file)
        if not is_valid:
            logger.error(f"[STT] 파일 검증 실패: {validation_message}")
            raise HTTPException(status_code=400, detail=validation_message)
        
        # 2. 파일 읽기
        try:
            audio_bytes = await file.read()
        except Exception as e:
            logger.error(f"[STT] 파일 읽기 실패: {e}")
            raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {str(e)}")
        
        # 3. 파일 크기 검증
        total_bytes = len(audio_bytes)
        file_size_mb = total_bytes / (1024 * 1024)
        
        if file_size_mb > settings.MAX_FILE_SIZE_MB:
            logger.error(f"[STT] 파일 크기 초과: {file_size_mb:.2f}MB")
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기가 너무 큽니다. 최대 {settings.MAX_FILE_SIZE_MB}MB"
            )
        
        # 최소 크기 검증(무발화/빈 업로드 차단)
        MIN_AUDIO_BYTES = 1200  # 환경에 맞게 조정 가능
        if total_bytes < MIN_AUDIO_BYTES:
            logger.error(f"[STT] 파일 크기 너무 작음: {total_bytes} bytes (< {MIN_AUDIO_BYTES})")
            raise HTTPException(status_code=400, detail="오디오 데이터가 너무 짧습니다. 다시 시도해주세요.")

        logger.info(f"[STT] 파일 크기: {total_bytes} bytes ({file_size_mb:.2f}MB)")
        
        return audio_bytes, file_size_mb, file.content_type or "application/octet-stream"
    
    async def transcribe_from_file(self, file: UploadFile) -> str:
        """UploadFile에서 직접 음성 인식 (통합된 전처리 포함)"""
        try:
            # 통합된 검증 및 읽기
            audio_bytes, file_size_mb, content_type = await self.validate_and_read_audio(file)
            
            # OpenAI Whisper API 호출
            transcribed_text = await self.transcribe_audio_bytes(audio_bytes, content_type)
            
            logger.info(f"[STT] 변환 완료: '{transcribed_text}' (파일크기: {file_size_mb:.2f}MB)")
            return transcribed_text
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[STT] 파일 음성인식 실패: {e}")
            raise HTTPException(status_code=500, detail=f"음성인식 처리 오류: {str(e)}")
    
    async def transcribe_audio_bytes(self, file_content: bytes, content_type: str = "audio/m4a") -> str:
        """바이트 데이터에서 음성 인식 (개선된 메서드)"""
        # 파일 확장자 추론
        file_extension = self._get_file_extension_from_content_type(content_type)
        filename = f"audio.{file_extension}"
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": (filename, file_content, content_type)}
        # 낮은 temperature로 환각 줄이기, 한국어 고정
        data = {
            "model": "whisper-1",
            "language": "ko",
            "temperature": 0,
        }
        
        async with httpx.AsyncClient() as client:
            try:
                logger.debug(f"[STT] OpenAI API 호출 시작 (크기: {len(file_content)} bytes)")
                
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60.0
                )
                response.raise_for_status()
                
                result = response.json()
                transcribed_text = result.get("text", "")
                
                logger.debug(f"[STT] OpenAI API 응답 성공: {len(transcribed_text)} 글자")
                return transcribed_text

            except httpx.HTTPStatusError as e:
                logger.error(f"[STT] OpenAI API 에러: {e.response.status_code}")
                logger.error(f"[STT] 에러 내용: {e.response.text}")
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"OpenAI API 에러: {e.response.text}"
                )
            except httpx.TimeoutException:
                logger.error("[STT] OpenAI API 타임아웃")
                raise HTTPException(status_code=504, detail="음성인식 서비스 타임아웃")
            except Exception as e:
                logger.error(f"[STT] 내부 서버 오류: {e}")
                raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")
    
    async def transcribe_audio(self, file_content: bytes) -> str:
        """기존 호환성을 위한 래퍼 메서드"""
        return await self.transcribe_audio_bytes(file_content)
    
    def _get_file_extension_from_content_type(self, content_type: str) -> str:
        """Content-Type에서 파일 확장자 추론"""
        content_type_mapping = {
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/m4a": "m4a",
            "audio/x-m4a": "m4a",
            "audio/webm": "webm",
            "audio/ogg": "ogg",
            "application/octet-stream": "m4a"  # 기본값
        }
        
        return content_type_mapping.get(content_type, "m4a")
    
    def get_supported_formats(self) -> list:
        """지원되는 오디오 형식 목록 반환"""
        return settings.SUPPORTED_AUDIO_TYPES
    
    def get_service_info(self) -> dict:
        """서비스 정보 반환"""
        return {
            "service": "OpenAI Whisper",
            "supported_formats": self.get_supported_formats(),
            "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
            "language": "ko",
            "model": "whisper-1",
            "features": [
                "unified_preprocessing",
                "file_validation",
                "content_type_detection",
                "error_handling"
            ]
        }
