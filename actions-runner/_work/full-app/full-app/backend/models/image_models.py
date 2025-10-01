"""
이미지 데이터 모델 정의
프레임 데이터 타입 명확화 및 검증
"""

import numpy as np
import cv2
import base64
from typing import Union, Optional, Any
from pydantic import BaseModel, Field, validator
from fastapi import UploadFile
import io

class ImageFrame:
    """OpenCV 이미지 프레임 래퍼 클래스"""
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, cv_image: np.ndarray):
        if cv_image is None or cv_image.size == 0:
            raise ValueError("유효하지 않은 이미지 데이터")
        
        self.data = cv_image
        self.shape = cv_image.shape
        self.height, self.width = cv_image.shape[:2]
        self.channels = cv_image.shape[2] if len(cv_image.shape) == 3 else 1
    
    @classmethod
    def from_bytes(cls, image_bytes: bytes) -> 'ImageFrame':
        """바이트 데이터에서 이미지 생성"""
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            cv_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if cv_image is None:
                raise ValueError("이미지 디코딩 실패")
            return cls(cv_image)
        except Exception as e:
            raise ValueError(f"바이트에서 이미지 변환 실패: {e}")
    
    @classmethod
    def from_base64(cls, base64_str: str) -> 'ImageFrame':
        """Base64 문자열에서 이미지 생성"""
        try:
            # Base64 헤더 제거 (data:image/jpeg;base64, 등)
            if ',' in base64_str:
                base64_str = base64_str.split(',')[1]
            
            image_bytes = base64.b64decode(base64_str)
            return cls.from_bytes(image_bytes)
        except Exception as e:
            raise ValueError(f"Base64에서 이미지 변환 실패: {e}")
    
    @classmethod
    async def from_upload_file(cls, upload_file: UploadFile) -> 'ImageFrame':
        """UploadFile에서 이미지 생성"""
        try:
            image_bytes = await upload_file.read()
            return cls.from_bytes(image_bytes)
        except Exception as e:
            raise ValueError(f"업로드 파일에서 이미지 변환 실패: {e}")
    
    def to_bytes(self, format: str = '.jpg') -> bytes:
        """이미지를 바이트로 변환"""
        try:
            _, buffer = cv2.imencode(format, self.data)
            return buffer.tobytes()
        except Exception as e:
            raise ValueError(f"이미지를 바이트로 변환 실패: {e}")
    
    def to_base64(self, format: str = '.jpg') -> str:
        """이미지를 Base64로 변환"""
        try:
            image_bytes = self.to_bytes(format)
            return base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            raise ValueError(f"이미지를 Base64로 변환 실패: {e}")
    
    def validate_for_depth_estimation(self) -> bool:
        """Depth estimation에 적합한지 검증"""
        if self.width < 224 or self.height < 224:
            return False  # MiDaS 최소 크기
        if self.width > 2048 or self.height > 2048:
            return False  # 메모리 제한
        if self.channels not in [1, 3]:
            return False  # 그레이스케일 또는 RGB만
        return True
    
    def resize_for_processing(self, target_size: int = 384) -> 'ImageFrame':
        """처리를 위한 리사이즈"""
        try:
            # 비율 유지하며 리사이즈
            scale = target_size / max(self.height, self.width)
            new_width = int(self.width * scale)
            new_height = int(self.height * scale)
            
            resized = cv2.resize(self.data, (new_width, new_height))
            return ImageFrame(resized)
        except Exception as e:
            raise ValueError(f"이미지 리사이즈 실패: {e}")
    
    def __str__(self) -> str:
        return f"ImageFrame({self.width}x{self.height}x{self.channels})"

class FrameDataRequest(BaseModel):
    """프레임 데이터 요청 모델"""
    
    # 다양한 입력 형식 지원
    image_base64: Optional[str] = Field(
        None,
        description="Base64 인코딩된 이미지 데이터"
    )
    
    image_bytes: Optional[bytes] = Field(
        None,
        description="바이너리 이미지 데이터"
    )
    
    # 메타데이터
    format: Optional[str] = Field(
        "jpg",
        description="이미지 형식 (jpg, png, bmp)"
    )
    
    resize_for_processing: bool = Field(
        True,
        description="처리를 위한 자동 리사이즈 여부"
    )
    
    @validator('image_base64', 'image_bytes')
    def validate_image_data(cls, v, values):
        """적어도 하나의 이미지 데이터는 필수"""
        if not v and not values.get('image_bytes') and not values.get('image_base64'):
            raise ValueError("image_base64 또는 image_bytes 중 하나는 필수입니다")
        return v
    
    def to_image_frame(self) -> ImageFrame:
        """ImageFrame 객체로 변환"""
        try:
            if self.image_base64:
                frame = ImageFrame.from_base64(self.image_base64)
            elif self.image_bytes:
                frame = ImageFrame.from_bytes(self.image_bytes)
            else:
                raise ValueError("이미지 데이터가 없습니다")
            
            # 검증
            if not frame.validate_for_depth_estimation():
                raise ValueError(f"Depth estimation에 부적합한 이미지: {frame}")
            
            # 리사이즈 (옵션)
            if self.resize_for_processing:
                frame = frame.resize_for_processing()
            
            return frame
            
        except Exception as e:
            raise ValueError(f"ImageFrame 변환 실패: {e}")

# 타입 별칭 정의
ImageFrameType = Union[ImageFrame, np.ndarray, bytes, str]
ProcessableImage = ImageFrame