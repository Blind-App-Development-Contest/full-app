import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';

/// 시각장애인용 접근성 텍스트 위젯
/// 탭하면 VoiceService.speak() 메서드를 호출하여 실제 음성으로 읽어줍니다
/// 
/// 사용 예제:
/// ```dart
/// AccessibleText('안녕하세요') // 탭하면 음성 출력
/// AccessibleTitle('제목입니다') // 제목용
/// AccessibleDescription('설명입니다') // 설명용 (느린 속도)
/// ```
class AccessibleText extends StatelessWidget {
  final String text;
  final TextStyle? style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;
  final bool softWrap;
  final TextScaler? textScaler;
  final String? semanticsLabel;
  final bool enableVoiceOutput;
  final double? customSpeed; // 커스텀 속도 (기본값은 null)

  const AccessibleText(
    this.text, {
    super.key,
    this.style,
    this.textAlign,
    this.maxLines,
    this.overflow,
    this.softWrap = true,
    this.textScaler,
    this.semanticsLabel,
    this.enableVoiceOutput = true,
    this.customSpeed,
  });

  @override
  Widget build(BuildContext context) {
    if (!enableVoiceOutput) {
      return Text(
        text,
        style: style,
        textAlign: textAlign,
        maxLines: maxLines,
        overflow: overflow,
        softWrap: softWrap,
        textScaler: textScaler ?? TextScaler.noScaling,
        semanticsLabel: semanticsLabel,
      );
    }

    return GestureDetector(
      onTap: () => _speakText(context),
      child: Semantics(
        label: semanticsLabel ?? text,
        button: true,
        hint: '탭하여 음성으로 듣기',
        child: Text(
          text,
          style: style,
          textAlign: textAlign,
          maxLines: maxLines,
          overflow: overflow,
          softWrap: softWrap,
          textScaler: textScaler ?? TextScaler.noScaling,
        ),
      ),
    );
  }

  /// 실제 음성 출력 수행 메서드
  /// VoiceService.speak()를 호출하여 TTS 서버에 요청하고 음성 재생
  void _speakText(BuildContext context) async {
    if (!enableVoiceOutput) {
      debugPrint('⚠️ AccessibleText 음성 출력 비활성화됨');
      return;
    }
    
    final textToSpeak = semanticsLabel ?? text;
    debugPrint('\n🔊 ===== AccessibleText 음성 출력 시작 =====');
    debugPrint('📝 텍스트: "$textToSpeak"');
    
    try {
      final voiceService = context.read<VoiceService>();
      debugPrint('✅ VoiceService Provider 연결 성공');
      
      // 커스텀 속도가 있으면 사용, 없으면 기본 속도 사용
      final speed = customSpeed ?? voiceService.getCurrentSpeed();
      debugPrint('⏱️ 음성 속도: ${speed}x');
      
      // VoiceService의 speak 메서드 직접 호출
      debugPrint('🚀 VoiceService.speak() 호출 시작...');
      await voiceService.speak(
        textToSpeak,
        speed: speed,
      );
      
      debugPrint('✅ AccessibleText 음성 출력 요청 완료!');
      debugPrint('🔊 TTS 서버로 요청 전송됨 - 음성이 재생되어야 합니다');
      debugPrint('===== AccessibleText 음성 출력 완료 =====\n');
      
    } catch (e) {
      debugPrint('❌ AccessibleText 음성 출력 실패!');
      debugPrint('❌ 오류 내용: $e');
      debugPrint('⚠️ 가능한 원인: VoiceService 오류, 네트워크 문제, TTS 서버 오류');
      debugPrint('===== AccessibleText 음성 출력 실패 =====\n');
    }
  }
  
  /// 테스트용: 직접 음성 출력 호출
  static void testSpeak(BuildContext context, String text) {
    final accessibleText = AccessibleText(text);
    accessibleText._speakText(context);
  }

}

/// 제목용 접근성 텍스트
class AccessibleTitle extends AccessibleText {
  const AccessibleTitle(
    super.text, {
    super.key,
    super.style,
    super.textAlign,
    super.maxLines,
    super.overflow,
    super.softWrap,
    super.textScaler,
    super.semanticsLabel,
    super.enableVoiceOutput = true,
    super.customSpeed,
  });
}

/// 설명용 접근성 텍스트 (조금 느린 속도)
class AccessibleDescription extends AccessibleText {
  const AccessibleDescription(
    super.text, {
    super.key,
    super.style,
    super.textAlign,
    super.maxLines,
    super.overflow,
    super.softWrap,
    super.textScaler,
    super.semanticsLabel,
    super.enableVoiceOutput = true,
    double? customSpeed,
  }) : super(
    customSpeed: customSpeed ?? 0.8, // 설명은 기본적으로 조금 더 느리게
  );
}