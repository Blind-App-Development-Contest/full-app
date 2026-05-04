import 'package:flutter/material.dart';

class NextButton extends StatelessWidget {
  final String label;
  final bool enabled;
  final VoidCallback? onPressed;

  const NextButton({
    super.key,
    this.label = '다음 단계',
    this.enabled = true,
    this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    // 비활성화 시 회색, 활성화 시 밝은 그레이 톤
    final Color bgColor = enabled ? const Color(0xFFBFBFBF) : const Color(0xFF696969);
    final Color fgColor = Colors.black;

    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 8),
      child: SizedBox(
        width: double.infinity,
        height: 56,
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
