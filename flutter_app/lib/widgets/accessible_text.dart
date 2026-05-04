import 'package:flutter/material.dart';
import '../utils/voice_utils.dart';

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
  /// VoiceUtils를 사용하여 일관된 음성 출력 수행
  void _speakText(BuildContext context) async {
    if (!enableVoiceOutput) {
      debugPrint('⚠️ AccessibleText 음성 출력 비활성화됨');
      return;
    }
    
    final textToSpeak = semanticsLabel ?? text;
    await VoiceUtils.speak(context, textToSpeak, speed: customSpeed);
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