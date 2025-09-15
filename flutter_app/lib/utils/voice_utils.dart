import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';

/// 음성 출력 유틸리티 클래스
/// 모든 화면에서 동일한 방식으로 음성 출력을 수행하기 위한 공통 함수 제공
class VoiceUtils {
  
  /// 컨텍스트를 사용하여 음성 출력 - 최적화된 버전
  static Future<void> speak(
    BuildContext context, 
    String text, {
    double? speed,
  }) async {
    if (text.trim().isEmpty) return; // 빈 텍스트 빠른 반환
    
    try {
      final voiceService = context.read<VoiceService>();
      final finalSpeed = speed ?? voiceService.getCurrentSpeed();
      
      // 로그 제거로 속도 향상, await 제거로 비동기 실행
      voiceService.speak(text, speed: finalSpeed);
      
    } catch (_) {
      // 에러 로그 제거로 속도 향상
    }
  }

  /// VoiceService 인스턴스를 사용하여 음성 출력 - 최적화된 버전
  static Future<void> speakWithService(
    VoiceService? voiceService, 
    String text, {
    double? speed,
  }) async {
    if (voiceService == null || text.trim().isEmpty) return;
    
    try {
      // await 제거로 비동기 실행, 응답성 향상
      if (speed != null) {
        voiceService.speak(text, speed: speed);
      } else {
        voiceService.speak(text);
      }
    } catch (_) {
      // 로그 제거로 속도 향상
    }
  }

  /// 걸음수 측정 시작 안내 (공통)
  static Future<void> announceStepMeasurementStart(VoiceService? voiceService) async {
    if (voiceService == null) return;
    
    await speakWithService(voiceService, "보폭 측정을 시작합니다. 직선으로 자연스럽게 걸어주세요.");
    await Future.delayed(const Duration(milliseconds: 600));
    await speakWithService(voiceService, "10미터 거리를 걸으면 자동으로 측정이 완료되고, 걸음 수를 물어보겠습니다.");
  }

  /// 거리 측정 완료 안내 (공통)
  static Future<void> announceDistanceMeasured(VoiceService? voiceService, double distanceMeters) async {
    if (voiceService == null) return;
    
    await speakWithService(voiceService, "거리 측정이 완료되었습니다!");
    await Future.delayed(const Duration(milliseconds: 500));
    await speakWithService(voiceService, "정확히 ${distanceMeters.toStringAsFixed(1)}미터를 측정했습니다.");
    await Future.delayed(const Duration(milliseconds: 500));
    await speakWithService(voiceService, "측정 완료. ${distanceMeters.toStringAsFixed(0)}미터 걸으며 센 걸음 수를 말씀해주세요.");
  }
}