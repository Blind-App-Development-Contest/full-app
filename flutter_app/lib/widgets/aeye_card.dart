import 'package:flutter/material.dart';

class AeyeCard extends StatelessWidget {
  final String title;
  final String subtitle;

  const AeyeCard({
    super.key,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const SizedBox(height: 12),
        Text(
          title,
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 36,
            letterSpacing: 1.2,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          subtitle,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.8),
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 28),
      ],
    );
  }
}
