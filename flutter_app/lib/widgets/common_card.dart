import 'package:flutter/material.dart';
import '../constants/app_colors.dart';

/// 앱 전체에서 사용되는 공통 카드 위젯
class CommonCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets? padding;
  final VoidCallback? onTap;
  final Color? backgroundColor;
  final Color? borderColor;
  final double borderRadius;

  const CommonCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.onTap,
    this.backgroundColor,
    this.borderColor,
    this.borderRadius = 18,
  });

  @override
  Widget build(BuildContext context) {
    Widget cardWidget = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: backgroundColor ?? AppColors.panel,
        borderRadius: BorderRadius.circular(borderRadius),
        border: Border.all(
          color: borderColor ?? AppColors.dividerWithOpacity,
        ),
      ),
      child: child,
    );

    if (onTap != null) {
      return InkWell(
        borderRadius: BorderRadius.circular(borderRadius),
        onTap: onTap,
        child: cardWidget,
      );
    }

    return cardWidget;
  }
}

/// 설정 화면에서 사용되는 타일 위젯
class SettingTile extends StatelessWidget {
  final IconData leadingIcon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const SettingTile({
    super.key,
    required this.leadingIcon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return CommonCard(
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 좌측 아이콘
          Container(
            width: 48,
            height: 48,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.dividerBorder),
            ),
            child: Icon(leadingIcon, color: AppColors.primaryText, size: 24),
          ),
          const SizedBox(width: 14),

          // 타이틀/서브타이틀
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                      color: AppColors.primaryText,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    )),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: TextStyle(
                    color: AppColors.caption,
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),

          // 우측 편집 아이콘
          Container(
            width: 40,
            height: 40,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.dividerBorder),
            ),
            child: const Icon(Icons.edit_outlined, color: AppColors.primaryText),
          ),
        ],
      ),
    );
  }
}

/// 모드 선택 카드 위젯
class ModeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;
  final VoidCallback onTap;

  const ModeCard({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return CommonCard(
      onTap: onTap,
      child: Row(
        children: [
          // 좌측 아이콘
          Container(
            width: 56,
            height: 56,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.dividerBorder),
            ),
            child: Icon(icon, color: AppColors.primaryText, size: 28),
          ),
          const SizedBox(width: 18),

          // 제목과 설명
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: AppColors.primaryText,
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  description,
                  style: TextStyle(
                    color: AppColors.caption,
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}