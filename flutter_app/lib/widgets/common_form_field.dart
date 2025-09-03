import 'package:flutter/material.dart';
import '../constants/app_colors.dart';

/// 공통 입력 필드 위젯
class CommonFormField extends StatelessWidget {
  final TextEditingController controller;
  final String hintText;
  final bool enabled;
  final TextInputType? keyboardType;
  final int? maxLength;
  final ValueChanged<String>? onChanged;
  final String? errorText;
  final bool obscureText;
  final Color? fieldColor;

  const CommonFormField({
    super.key,
    required this.controller,
    required this.hintText,
    this.enabled = true,
    this.keyboardType,
    this.maxLength,
    this.onChanged,
    this.errorText,
    this.obscureText = false,
    this.fieldColor,
  });

  @override
  Widget build(BuildContext context) {
    const field = Color(0xFF151C2C); // 입력 필드 전용 색상

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.dividerWithOpacity),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 0),
            decoration: BoxDecoration(
              color: fieldColor ?? field,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.dividerBorder),
            ),
            child: TextField(
              controller: controller,
              enabled: enabled,
              keyboardType: keyboardType,
              maxLength: maxLength,
              onChanged: onChanged,
              obscureText: obscureText,
              style: const TextStyle(
                color: AppColors.primaryText,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
              decoration: InputDecoration(
                border: InputBorder.none,
                hintText: hintText,
                hintStyle: const TextStyle(
                  color: AppColors.hint,
                  fontWeight: FontWeight.w600,
                ),
                counterText: '', // 글자 수 카운터 숨김
                errorText: errorText,
                errorStyle: const TextStyle(
                  color: Colors.redAccent,
                  fontSize: 12,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 공통 정보 카드 위젯 (step_screen.dart의 _InfoCard 대체)
class InfoCard extends StatelessWidget {
  final Widget child;
  
  const InfoCard({
    super.key,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.dividerWithOpacity),
      ),
      child: child,
    );
  }
}

/// 공통 선택 버튼 위젯
class SelectionButton extends StatelessWidget {
  final String text;
  final bool isSelected;
  final VoidCallback onPressed;
  final IconData? icon;

  const SelectionButton({
    super.key,
    required this.text,
    required this.isSelected,
    required this.onPressed,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 4),
      child: ElevatedButton(
        onPressed: onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: isSelected 
              ? AppColors.primaryText 
              : AppColors.panel,
          foregroundColor: isSelected 
              ? AppColors.bg 
              : AppColors.primaryText,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(
              color: isSelected 
                  ? AppColors.primaryText 
                  : AppColors.dividerBorder,
            ),
          ),
          elevation: 0,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 16),
              const SizedBox(width: 6),
            ],
            Text(
              text,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: isSelected 
                    ? AppColors.bg 
                    : AppColors.primaryText,
              ),
            ),
          ],
        ),
      ),
    );
  }
}