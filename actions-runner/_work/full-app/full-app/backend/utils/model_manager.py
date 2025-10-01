"""
MiDaS 모델 중앙 관리자
중복 로딩 방지 및 성능 최적화를 위한 싱글톤 매니저
"""

import torch
import torch.nn.functional as F
import logging
import time
from typing import Optional, Tuple, Any
import numpy as np

logger = logging.getLogger(__name__)

class MiDaSModelManager:
    """MiDaS 모델 중앙 관리 싱글톤"""
    
    _instance = None
    _model = None
    _transform = None
    _device = None
    _model_loaded = False
    _model_name = "MiDaS_small"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MiDaSModelManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("[MiDaSManager] 모델 매니저 초기화")
    
    def load_model(self) -> bool:
        """MiDaS 모델 로딩 (지연 로딩)"""
        if self._model_loaded:
            return True
        
        try:
            logger.info(f"[MiDaSManager] {self._model_name} 모델 로딩 시작...")
            start_time = time.time()
            
            # GPU/CPU 디바이스 설정
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"[MiDaSManager] 사용 디바이스: {self._device}")
            
            # MiDaS 모델 로드
            self._model = torch.hub.load("intel-isl/MiDaS", self._model_name, pretrained=True)
            self._model.to(self._device)
            self._model.eval()
            
            # 변환 파이프라인 로드
            midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
            self._transform = midas_transforms.small_transform
            
            load_time = time.time() - start_time
            logger.info(f"[MiDaSManager] 모델 로딩 완료 ({load_time:.2f}초)")
            
            self._model_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"[MiDaSManager] 모델 로딩 실패: {e}")
            self._model_loaded = False
            return False
    
    def get_model(self) -> Tuple[Optional[Any], Optional[Any], Optional[torch.device]]:
        """모델, 변환기, 디바이스 반환"""
        if not self._model_loaded:
            if not self.load_model():
                return None, None, None
        
        return self._model, self._transform, self._device
    
    def is_loaded(self) -> bool:
        """모델 로딩 상태 확인"""
        return self._model_loaded
    
    def get_model_info(self) -> dict:
        """모델 정보 반환"""
        return {
            "model_name": self._model_name,
            "device": str(self._device) if self._device else "not_loaded",
            "model_loaded": self._model_loaded,
            "memory_usage": self._get_memory_usage()
        }
    
    def _get_memory_usage(self) -> dict:
        """메모리 사용량 정보"""
        memory_info = {"cpu": "unknown", "gpu": "unknown"}
        
        try:
            if torch.cuda.is_available() and self._model_loaded:
                gpu_memory = torch.cuda.memory_allocated() / 1024**2  # MB
                gpu_max_memory = torch.cuda.max_memory_allocated() / 1024**2  # MB
                memory_info["gpu"] = f"{gpu_memory:.1f}MB / {gpu_max_memory:.1f}MB"
        except Exception as e:
            logger.debug(f"GPU 메모리 정보 수집 실패: {e}")
        
        return memory_info
    
    def cleanup(self):
        """모델 메모리 정리"""
        try:
            if self._model is not None:
                del self._model
                self._model = None
            
            if self._transform is not None:
                del self._transform
                self._transform = None
            
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            self._model_loaded = False
            logger.info("[MiDaSManager] 모델 메모리 정리 완료")
            
        except Exception as e:
            logger.error(f"[MiDaSManager] 메모리 정리 실패: {e}")

# 글로벌 싱글톤 인스턴스
midas_manager = MiDaSModelManager()

def get_midas_manager() -> MiDaSModelManager:
    """MiDaS 매니저 인스턴스 반환"""
    return midas_manager