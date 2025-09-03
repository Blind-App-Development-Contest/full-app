import 'package:flutter/material.dart';

/// 앱 전체에서 사용되는 색상 상수들
class AppColors {
  // 기본 배경 및 컨테이너 색상
  static const Color bg = Color(0xFF000000);
  static const Color panel = Color(0xFF0D1320);
  static const Color divider = Color(0xFF22304A);
  
  // 텍스트 색상
  static const Color caption = Color(0xFF9AA3B2);
  static const Color hint = Color(0xFF9AA3B2);
  
  // 기본 텍스트 색상
  static const Color primaryText = Colors.white;
  
  // 투명도가 적용된 색상들
  static Color get secondaryText => Colors.white.withValues(alpha: 0.8);
  static Color get dividerWithOpacity => divider.withValues(alpha: 0.25);
  static Color get dividerBorder => divider.withValues(alpha: 0.4);
}