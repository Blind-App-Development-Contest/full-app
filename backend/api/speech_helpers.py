"""speech_routes.py의 헬퍼 함수들"""

import time
import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

from models.common_models import ExecutionStatus
from models.recognition_schemas import SpeechRecognitionResponse
from models.execution_schemas import CommandExecutionResponse, FullCommandResponse
from models.fastdepth_models import FastDepthFrameData, EnhancedCommandRequest
from services.command_executor import CommandExecutionResult
from services.speech_analyzer import SpeechAnalyzer
from services.command_executor import CommandExecutor
from utils.fastdepth_processor import get_fastdepth_processor

# 싱글톤 서비스 인스턴스 가져오기
from services.singleton import service_manager

speech_analyzer = service_manager.get_speech_analyzer()
command_executor = service_manager.get_command_executor()


def get_current_context() -> str:
    """현재 컨텍스트 조회"""
    try:
        if command_executor.is_measurement_active():
            return "measurement_active"
        else:
            return "default"
    except Exception as e:
        print(f"컨텍스트 조회 실패: {e}")
        return "default"


async def process_fastdepth_frame(frame: FastDepthFrameData):
    """프레임 처리 - 통합 FastDepth 프로세서 전용"""
    try:
        # 통합 FastDepth 프로세서 사용 (단일 프로세싱 경로)
        processor = get_fastdepth_processor()
        processed_frame = processor.convert_frame_to_dict(frame)
        
        return await command_executor.process_fastdepth_frame(processed_frame.frame_dict)
    except Exception as e:
        logger.error(f"FastDepth 프레임 처리 실패: {e}")
        raise  # 에러를 상위로 전파하여 일관된 에러 처리


async def process_speech_command_with_context(request: EnhancedCommandRequest, context: str):
    """컨텍스트를 포함한 음성 명령 처리 - 통합 실행 로직 사용"""
    # SpeechAnalyzer로 분석 (컨텍스트 포함)
    recognition_result = speech_analyzer.analyze_command(request.command_text, context)
    
    # 통합 조건부 실행 로직 사용
    execution_result = await execute_command_conditionally(
        recognition_result, 
        request.execute_immediately, 
        context
    )
    
    return recognition_result, execution_result


def build_enhanced_response(command_result, frame_result, context: str):
    """향상된 응답 구성"""
    if command_result:
        recognition_result, execution_result = command_result
    else:
        recognition_result = SpeechRecognitionResponse(
            intent="FASTDEPTH_FRAME_ONLY",
            entities={"frame_processing": True, "context": context},
            confidence=1.0,
            command_text=""
        )
        execution_result = frame_result
    
    response_data = execution_result.data.copy() if execution_result else {}
    response_actions = execution_result.actions.copy() if execution_result else []
    
    # 컨텍스트 정보 추가
    response_data.update({
        "context": context
    })
    
    if frame_result:
        response_data.update({
            "frame_processing": {
                "processed": True,
                "frame_result": frame_result.data if hasattr(frame_result, 'data') else frame_result,
                "frame_message": frame_result.message if hasattr(frame_result, 'message') else "프레임 처리 완료"
            }
        })
    
    return FullCommandResponse(
        intent=recognition_result.intent,
        entities=recognition_result.entities,
        confidence=recognition_result.confidence,
        execution=CommandExecutionResponse(
            status=execution_result.status if execution_result else ExecutionStatus.SUCCESS,
            message=execution_result.message if execution_result else "처리 완료",
            data=response_data,
            actions=response_actions,
            timestamp=execution_result.timestamp if execution_result else datetime.now()
        )
    )


def get_available_commands_for_context() -> List[str]:
    """사용 가능한 기본 명령어들 반환"""
    if command_executor.is_measurement_active():
        return [
            "측정 완료", "보폭 측정 완료", "완료",
            "측정 취소", "측정 중단", "취소"
        ]
    else:
        return [
            "보폭 측정 시작", "보폭 재측정", "측정 시작"
        ]


def analyze_speech_command_with_context(command_text: str, context: str = None) -> 'SpeechRecognitionResponse':
    """
    음성 명령 분석 및 컨텍스트 처리 통합 헬퍼 함수
    
    Args:
        command_text: 분석할 음성 명령 텍스트
        context: 현재 컨텍스트 (None이면 자동 감지)
        
    Returns:
        SpeechRecognitionResponse: 분석된 음성 인식 결과
        
    Raises:
        ValueError: command_text가 비어있는 경우
    """
    if not command_text or not command_text.strip():
        raise ValueError("command_text는 필수입니다")
    
    # 현재 컨텍스트 자동 감지 (context가 제공되지 않은 경우)
    if context is None:
        context = get_current_context()
    
    logger.debug(f"음성 명령 분석: '{command_text}', 컨텍스트: {context}")
    
    # SpeechAnalyzer로 명령 분석 (컨텍스트 포함)
    recognition_result = speech_analyzer.analyze_command(command_text, context)
    
    # 보폭 측정 관련 의도인 경우 기본 컨텍스트 정보 제공
    if recognition_result.intent.startswith("FOOTSTEP_"):
        measurement_context = {
            "measurement_active": command_executor.is_measurement_active(),
            "measurement_type": "kalman_filter"
        }
        
        # entities에 컨텍스트 정보 추가
        recognition_result.entities.update({"measurement_context": measurement_context})
    
    logger.debug(f"분석 결과: 의도={recognition_result.intent}, 신뢰도={recognition_result.confidence}")
    return recognition_result


# 공유 명령 실행 로직
def create_pending_execution_result(context: str = None) -> CommandExecutionResult:
    """
    PENDING 상태의 CommandExecutionResult 생성 (중복 제거용)
    
    Args:
        context: 실행 컨텍스트
        
    Returns:
        표준화된 PENDING CommandExecutionResult
    """
    return CommandExecutionResult(
        status=ExecutionStatus.PENDING,
        message="명령이 분석되었습니다.",
        data={"execute_immediately": False, "context": context or get_current_context()},
        actions=["analyze_command"]
    )


async def execute_command_conditionally(
    recognition_result: SpeechRecognitionResponse, 
    execute_immediately: bool,
    context: str = None
) -> CommandExecutionResult:
    """
    조건부 명령 실행 로직 (중복 제거용)
    
    Args:
        recognition_result: 음성 인식 결과
        execute_immediately: 즉시 실행 여부
        context: 실행 컨텍스트
        
    Returns:
        명령 실행 결과
    """
    if execute_immediately:
        return await command_executor.execute_command(recognition_result)
    else:
        return create_pending_execution_result(context)


def get_supported_intents_with_kalman():
    """칼만 필터 의도를 포함한 전체 의도 목록 반환"""
    base_intents = speech_analyzer.get_supported_intents()
    
    # 칼만 필터 관련 의도 추가
    kalman_intents = {
        "FOOTSTEP_MEASUREMENT_START": {
            "description": "칼만 필터 기반 보폭 측정 시작",
            "keywords": ["보폭 측정 시작", "측정 시작", "보폭 재측정"],
            "measurement_type": "kalman_filter"
        },
        "FOOTSTEP_MEASUREMENT_COMPLETE": {
            "description": "보폭 측정 완료",
            "keywords": ["측정 완료", "보폭 측정 완료", "완료"],
            "context_dependent": True
        },
        "FOOTSTEP_MEASUREMENT_CANCEL": {
            "description": "보폭 측정 취소",
            "keywords": ["측정 취소", "측정 중단", "취소"]
        },
        "FOOTSTEP_STATUS_CHECK": {
            "description": "보폭 상태 확인",
            "keywords": ["보폭 상태", "현재 보폭", "측정 상태", "보폭 확인"]
        }
    }
    
    return {
        "supported_intents": {**base_intents, **kalman_intents},
        "keyword_mapping": speech_analyzer.KEYWORD_MAPPING,
        "kalman_filter_intents": kalman_intents,
        "measurement_types": ["kalman_filter"],
        "measurement_active": command_executor.is_measurement_active()
    }
