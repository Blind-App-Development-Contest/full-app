import 'package:flutter/material.dart';
import '../services/voice_service.dart';

/// 음성 인식 공통 헬퍼 클래스
/// 중복 코드 제거 및 일관된 음성 인식 처리를 위한 유틸리티
class VoiceRecognitionHelper {
  final VoiceService voiceService;
  final VoidCallback? onTextRecognized;
  Function(String)? _currentCallback;
  
  VoiceRecognitionHelper({
    required this.voiceService,
    this.onTextRecognized,
  });

  /// 특정 키워드들을 기다리는 음성 인식 시작
  void startListeningForKeywords({
    required List<String> keywords,
    required Function(String matchedKeyword, String fullText) onMatch,
    int timeoutSeconds = 30,
    VoidCallback? onTimeout,
  }) {
    _currentCallback = (String recognizedText) {
      final text = recognizedText.toLowerCase().trim();
      
      for (String keyword in keywords) {
        if (text.contains(keyword.toLowerCase())) {
          stopListening();
          onMatch(keyword, recognizedText);
          return;
        }
      }
    };
    
    voiceService.addListener(_onVoiceUpdate);
    voiceService.startAutoRecognitionCycle();
    
    // 타임아웃 처리
    if (timeoutSeconds > 0) {
      Future.delayed(Duration(seconds: timeoutSeconds), () {
        if (_currentCallback != null) {
          stopListening();
          onTimeout?.call();
        }
      });
    }
  }

  /// 숫자 입력을 기다리는 음성 인식 시작 (걸음 수 등)
  void startListeningForNumber({
    required Function(int number, String fullText) onNumberFound,
    int minValue = 1,
    int maxValue = 100,
    int timeoutSeconds = 30,
    VoidCallback? onTimeout,
    VoidCallback? onInvalidInput,
  }) {
    _currentCallback = (String recognizedText) {
      final number = extractNumberFromSpeech(recognizedText);
      
      if (number >= minValue && number <= maxValue) {
        stopListening();
        onNumberFound(number, recognizedText);
      } else if (number > 0) {
        // 숫자는 인식되었지만 범위를 벗어남
        onInvalidInput?.call();
      }
    };
    
    voiceService.addListener(_onVoiceUpdate);
    voiceService.startAutoRecognitionCycle();
    
    // 타임아웃 처리
    if (timeoutSeconds > 0) {
      Future.delayed(Duration(seconds: timeoutSeconds), () {
        if (_currentCallback != null) {
          stopListening();
          onTimeout?.call();
        }
      });
    }
  }

  /// 예/아니오 응답을 기다리는 음성 인식 시작
  void startListeningForConfirmation({
    required Function(bool confirmed, String fullText) onConfirm,
    int timeoutSeconds = 15,
    VoidCallback? onTimeout,
  }) {
    _currentCallback = (String recognizedText) {
      final text = recognizedText.toLowerCase().trim();
      
      if (_isPositiveResponse(text)) {
        stopListening();
        onConfirm(true, recognizedText);
      } else if (_isNegativeResponse(text)) {
        stopListening();
        onConfirm(false, recognizedText);
      }
    };
    
    voiceService.addListener(_onVoiceUpdate);
    voiceService.startAutoRecognitionCycle();
    
    // 타임아웃 처리
    if (timeoutSeconds > 0) {
      Future.delayed(Duration(seconds: timeoutSeconds), () {
        if (_currentCallback != null) {
          stopListening();
          onTimeout?.call();
        }
      });
    }
  }

  /// 음성 인식 중지
  void stopListening() {
    if (_currentCallback != null) {
      voiceService.removeListener(_onVoiceUpdate);
      voiceService.stopAutoRecognitionCycle();
      _currentCallback = null;
    }
  }

  /// 음성 인식 업데이트 리스너
  void _onVoiceUpdate() {
    final recognizedText = voiceService.lastRecognizedText;
    if (recognizedText.isNotEmpty && _currentCallback != null) {
      _currentCallback!(recognizedText);
      onTextRecognized?.call();
    }
  }

  /// 음성에서 숫자 추출 (공통 사용을 위해 static으로 변경)
  static int extractNumberFromSpeech(String speech) {
    final cleanText = speech.toLowerCase().trim();
    
    // 확장된 한국어 숫자 매핑
    final koreanNumbers = {
      '영': 0, '공': 0, '하나': 1, '일': 1, '한': 1, '둘': 2, '이': 2,
      '셋': 3, '삼': 3, '넷': 4, '사': 4, '다섯': 5, '오': 5,
      '여섯': 6, '육': 6, '일곱': 7, '칠': 7, '여덟': 8, '팔': 8,
      '아홉': 9, '구': 9, '열': 10, '십': 10, '스무': 20, '이십': 20,
      '서른': 30, '삼십': 30, '마흔': 40, '사십': 40, '쉰': 50, '오십': 50
    };
    
    // 복합 숫자 매핑 (자주 사용되는 것들)
    final compositeNumbers = {
      '열하나': 11, '열한': 11, '열둘': 12, '열두': 12, '열셋': 13, '열세': 13,
      '열넷': 14, '열네': 14, '열다섯': 15, '열여섯': 16, '열일곱': 17,
      '열여덟': 18, '열아홉': 19, '스물하나': 21, '스물한': 21, '스물둘': 22,
      '스물두': 22, '스물셋': 23, '스물세': 23, '스물넷': 24, '스물네': 24,
      '스물다섯': 25
    };
    
    // 1. 직접적인 숫자 패턴 찾기 (15걸음, 20보 등)
    final patterns = [
      RegExp(r'(\d+)\s*(?:걸음|보|발자국|스텝|개|번|회)'),
      RegExp(r'(\d+)\s*(?:번|개)?'),
      RegExp(r'(?:걸음|보|발자국|스텝).*?(\d+)'),
    ];
    
    for (final pattern in patterns) {
      final match = pattern.firstMatch(cleanText);
      if (match != null) {
        final num = int.tryParse(match.group(1)!);
        if (num != null && num > 0 && num <= 100) {
          return num;
        }
      }
    }
    
    // 2. 복합 한국어 숫자 변환 시도 (우선순위 높음)
    for (final entry in compositeNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        return entry.value;
      }
    }
    
    // 3. 기본 한국어 숫자 변환 시도
    if (cleanText.contains('열') && cleanText.length > 1) {
      // 열 + 숫자 조합 처리
      final afterTen = cleanText.replaceFirst('열', '').trim();
      final baseNum = koreanNumbers[afterTen];
      if (baseNum != null && baseNum < 10) {
        return 10 + baseNum;
      }
      return 10;
    }
    
    for (final entry in koreanNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        return entry.value;
      }
    }
    
    // 4. 전체 텍스트에서 숫자만 추출
    final digitOnly = RegExp(r'\d+').allMatches(cleanText);
    for (final match in digitOnly) {
      final num = int.tryParse(match.group(0)!);
      if (num != null && num > 0 && num <= 100) {
        return num;
      }
    }
    
    return 0; // 숫자를 찾지 못함
  }

  /// 긍정 응답 확인
  bool _isPositiveResponse(String text) {
    final positiveKeywords = ['네', '예', '맞아', '맞습니다', '그래', '그렇습니다', '좋아', '좋습니다', '오케이', '확인'];
    return positiveKeywords.any((keyword) => text.contains(keyword));
  }

  /// 부정 응답 확인
  bool _isNegativeResponse(String text) {
    final negativeKeywords = ['아니', '아니요', '안돼', '안됩니다', '틀려', '틀렸어', '다시', '아니다'];
    return negativeKeywords.any((keyword) => text.contains(keyword));
  }

  /// 리소스 정리
  void dispose() {
    stopListening();
  }

  // ===== 정적 유틸리티 메서드들 =====
  
  /// 확인 명령어 체크 (네, 예, 맞음, 확인, 좋아 등)
  static bool isConfirmationCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    final positiveKeywords = ['네', '예', '맞', '확인', '좋', '그래', '오케이'];
    return positiveKeywords.any((keyword) => lowerCommand.contains(keyword));
  }
  
  /// 거부 명령어 체크 (아니오, 다시, 틀렸음 등)
  static bool isRejectionCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    final negativeKeywords = ['아니', '다시', '틀렸', '안돼', '재'];
    return negativeKeywords.any((keyword) => lowerCommand.contains(keyword));
  }
  
  /// 완료/저장/다음 명령어 체크
  static bool isCompletionCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    return lowerCommand.contains('완료') ||
           lowerCommand.contains('저장') ||
           lowerCommand.contains('다음');
  }
  
  /// 뒤로가기 명령어 체크
  static bool isBackCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    return lowerCommand.contains('뒤로') ||
           lowerCommand.contains('취소') ||
           lowerCommand.contains('돌아가');
  }
  
  /// 측정/시작 명령어 체크
  static bool isStartCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    return lowerCommand.contains('측정') ||
           lowerCommand.contains('시작');
  }
  
  /// 재측정/다시 명령어 체크
  static bool isRetryCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    return lowerCommand.contains('다시') ||
           lowerCommand.contains('재측정');
  }
}