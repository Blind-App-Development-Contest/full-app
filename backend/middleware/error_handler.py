"""통합 에러 처리 미들웨어 - 중복 try-catch 패턴 제거"""

import logging
import traceback
from typing import Any, Dict, Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """통합 에러 처리 미들웨어"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            # HTTPException은 FastAPI가 자동으로 처리하도록 다시 발생
            raise
        except Exception as e:
            # 모든 예상치 못한 예외를 통합 처리
            return await self.handle_unexpected_error(request, e)
    
    async def handle_unexpected_error(self, request: Request, error: Exception) -> JSONResponse:
        """예상치 못한 예외 통합 처리"""
        error_id = f"ERR_{id(error)}"
        endpoint = f"{request.method} {request.url.path}"
        
        # 로깅
        logger.error(
            f"[{error_id}] 예상치 못한 오류 발생 - {endpoint}: {str(error)}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        
        # 콘솔 출력 (기존 패턴 유지)
        print(f"[오류] {endpoint} 처리 중 오류: {error}")
        
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"서버 오류: {str(error)}",
                "error_id": error_id,
                "endpoint": endpoint
            }
        )

class APIErrorHandler:
    """API 엔드포인트용 에러 처리 헬퍼"""
    
    @staticmethod
    def handle_validation_error(message: str, field: Optional[str] = None) -> HTTPException:
        """입력 검증 오류 (400)"""
        detail = f"{field}: {message}" if field else message
        return HTTPException(status_code=400, detail=detail)
    
    @staticmethod
    def handle_not_found_error(resource: str, identifier: Optional[str] = None) -> HTTPException:
        """리소스 없음 오류 (404)"""
        detail = f"{resource}"
        if identifier:
            detail += f" (ID: {identifier})"
        detail += "을(를) 찾을 수 없습니다."
        return HTTPException(status_code=404, detail=detail)
    
    @staticmethod
    def handle_file_size_error(current_size_mb: float, max_size_mb: float) -> HTTPException:
        """파일 크기 초과 오류 (413)"""
        return HTTPException(
            status_code=413,
            detail=f"파일 크기가 너무 큽니다. 최대 {max_size_mb}MB (현재: {current_size_mb:.2f}MB)"
        )
    
    @staticmethod
    def handle_service_timeout_error(service_name: str) -> HTTPException:
        """서비스 타임아웃 오류 (504)"""
        return HTTPException(
            status_code=504,
            detail=f"{service_name} 서비스 타임아웃"
        )
    
    @staticmethod
    def handle_external_api_error(api_name: str, status_code: int, message: str) -> HTTPException:
        """외부 API 오류 (502)"""
        return HTTPException(
            status_code=502,
            detail=f"{api_name} API 에러 ({status_code}): {message}"
        )
    
    @staticmethod
    def handle_duplicate_resource_error(resource: str, field: str) -> HTTPException:
        """중복 리소스 오류 (409)"""
        return HTTPException(
            status_code=409,
            detail=f"이미 존재하는 {resource}입니다. ({field})"
        )

# 데코레이터를 통한 간편한 에러 처리
def handle_api_errors(func):
    """API 엔드포인트 에러 처리 데코레이터"""
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # HTTPException은 그대로 전달
            raise
        except Exception as e:
            # 엔드포인트별 로깅
            endpoint_name = func.__name__
            print(f"[오류] {endpoint_name} 처리 중 오류: {e}")
            raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")
    
    return wrapper

# 공통 에러 응답 생성기
class ErrorResponseBuilder:
    """표준화된 에러 응답 생성"""
    
    @staticmethod
    def build_error_response(
        success: bool = False,
        message: str = "",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """표준 에러 응답 형식"""
        response = {
            "success": success,
            "message": message
        }
        
        if error_code:
            response["error_code"] = error_code
        
        if details:
            response["details"] = details
        
        return response
    
    @staticmethod
    def build_validation_error_response(field: str, message: str) -> Dict[str, Any]:
        """입력 검증 에러 응답"""
        return ErrorResponseBuilder.build_error_response(
            success=False,
            message=f"입력 검증 실패: {message}",
            error_code="VALIDATION_ERROR",
            details={"field": field, "validation_message": message}
        )
    
    @staticmethod
    def build_service_error_response(service: str, operation: str, error: str) -> Dict[str, Any]:
        """서비스 에러 응답"""
        return ErrorResponseBuilder.build_error_response(
            success=False,
            message=f"{service} {operation} 실패",
            error_code="SERVICE_ERROR",
            details={"service": service, "operation": operation, "error": error}
        )

# 로깅 헬퍼
class ErrorLogger:
    """통합 에러 로깅"""
    
    @staticmethod
    def log_api_error(endpoint: str, operation: str, error: Exception, context: Optional[Dict] = None):
        """API 에러 로깅"""
        context_str = f" | 컨텍스트: {context}" if context else ""
        logger.error(f"[API 에러] {endpoint} - {operation}: {str(error)}{context_str}")
        print(f"[오류] {endpoint} {operation} 중 오류: {error}")
    
    @staticmethod
    def log_service_error(service: str, operation: str, error: Exception, details: Optional[Dict] = None):
        """서비스 에러 로깅"""
        details_str = f" | 세부사항: {details}" if details else ""
        logger.error(f"[서비스 에러] {service} - {operation}: {str(error)}{details_str}")
        print(f"[오류] {service} {operation} 중 오류: {error}")
    
    @staticmethod
    def log_external_api_error(api_name: str, status_code: int, response_text: str):
        """외부 API 에러 로깅"""
        logger.error(f"[외부 API 에러] {api_name}: {status_code} - {response_text}")
        print(f"[오류] {api_name} API 에러: {status_code}")