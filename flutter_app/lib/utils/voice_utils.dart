import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';

/// 음성 출력 유틸리티 클래스
/// 모든 화면에서 동일한 방식으로 음성 출력을 수행하기 위한 공통 함수 제공
class VoiceUtils {
  
  /// 컨텍스트를 사용하여 음성 출력
  /// AccessibleText와 동일한 구현을 사용하여 일관성 보장
  static Future<void> speak(
    BuildContext context, 
    String text, {
    double? speed,
  }) async {
    debugPrint('\n🔊 ===== VoiceUtils 음성 출력 시작 =====');
    debugPrint('📝 텍스트: "$text"');
    
    try {
      final voiceService = context.read<VoiceService>();
      debugPrint('✅ VoiceService Provider 연결 성공');
      
      // 속도가 지정되지 않으면 기본 속도 사용
      final finalSpeed = speed ?? voiceService.getCurrentSpeed();
      debugPrint('⏱️ 음성 속도: ${finalSpeed}x');
      
      // VoiceService의 speak 메서드 직접 호출
      debugPrint('🚀 VoiceService.speak() 호출 시작...');
      await voiceService.speak(
        text,
        speed: finalSpeed,
      );
      
      debugPrint('✅ VoiceUtils 음성 출력 요청 완료!');
      debugPrint('🔊 TTS 서버로 요청 전송됨 - 음성이 재생되어야 합니다');
      debugPrint('===== VoiceUtils 음성 출력 완료 =====\n');
      
    } catch (e) {
      debugPrint('❌ VoiceUtils 음성 출력 실패!');
      debugPrint('❌ 오류 내용: $e');
      debugPrint('⚠️ 가능한 원인: VoiceService 오류, 네트워크 문제, TTS 서버 오류');
      debugPrint('===== VoiceUtils 음성 출력 실패 =====\n');
    }
  }

  /// VoiceService 인스턴스를 사용하여 음성 출력 (기존 패턴 호환)
  /// 각 화면의 _speakText 함수를 대체하기 위한 함수
  static Future<void> speakWithService(
    VoiceService? voiceService, 
    String text, {
    double? speed,
  }) async {
    if (voiceService == null) {
      debugPrint('⚠️ VoiceService가 null입니다.');
      return;
    }
    
    try {
      if (speed != null) {
        await voiceService.speak(text, speed: speed);
      } else {
        await voiceService.speak(text);
      }
    } catch (e) {
      debugPrint('❌ 음성 출력 실패: $e');
    }
  }
}