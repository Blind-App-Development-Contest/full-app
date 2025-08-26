import 'package:flutter/material.dart';

class SetButton extends StatelessWidget {
  final String label;
  final bool hasChanged;       // ✅ 변경 여부
  final VoidCallback? onPressed;

  const SetButton({
    super.key,
    this.label = '완료',
    required this.hasChanged,  // true → 활성화, false → 비활성화
    this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final bool enabled = hasChanged;
    final Color bgColor = enabled ? const Color(0xFFBFBFBF) : const Color(0xFF696969);
    final Color fgColor = Colors.black;

    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 8),
      child: SizedBox(
        width: double.infinity,
        height: 56, // ✅ next_button과 동일
        child: ElevatedButton(
          onPressed: enabled ? onPressed : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: bgColor,
            disabledBackgroundColor: bgColor,
            foregroundColor: fgColor,
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
            textStyle: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
            ),
          ),
          child: Text(label),
        ),
      ),
    );
  }
}
