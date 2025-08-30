import 'package:flutter/material.dart';
import '../widgets/aeye_card.dart';
import 'setting_screen.dart';
import 'map_screen.dart';

class ModeScreen extends StatelessWidget {
  const ModeScreen({super.key});

  void _openCameraMode(BuildContext context) {
    Navigator.pushNamed(context, '/measurement-camera');
  }

  void _openNavigationMode(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => const MapScreen(backendBaseUrl: 'http://20.22.6.21:8000'),
      ),
    );
  }

  void _openSettings(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const divider = Color(0xFF22304A);
    const caption = Color(0xFF9AA3B2);

    return Scaffold(
      backgroundColor: bg,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const AeyeCard(
                title: 'A:EYE',
                subtitle: '모드 선택',
              ),
              _ModeCard(
                icon: Icons.photo_camera_outlined,
                title: '카메라 모드',
                description: '실시간 객체 인식 및 위험 감지',
                panel: panel,
                divider: divider,
                caption: caption,
                onTap: () => _openCameraMode(context),
              ),
              const SizedBox(height: 16),
              _ModeCard(
                icon: Icons.route_outlined,
                title: '길찾기 모드',
                description: '음성 길 안내 및 경로 탐색',
                panel: panel,
                divider: divider,
                caption: caption,
                onTap: () => _openNavigationMode(context),
              ),
              const SizedBox(height: 16),
              _ModeCard(
                icon: Icons.settings_outlined,
                title: '설정',
                description: '음성 · 보폭 · 보호자 정보 관리',
                panel: panel,
                divider: divider,
                caption: caption,
                onTap: () => _openSettings(context),
              ),
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;
  final Color panel;
  final Color divider;
  final Color caption;
  final VoidCallback onTap;
  final double height; // ✅ 기본값을 주는 선택 파라미터

  const _ModeCard({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.panel,
    required this.divider,
    required this.caption,
    required this.onTap,
    this.height = 110, // ✅ 기본값만 사용 (required 제거)
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: Container(
        height: height, // ✅ 높이 적용
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: panel,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: divider.withOpacity(0.25)),
        ),
        child: Row(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: divider.withOpacity(0.4)),
              ),
              child: Icon(icon, color: Colors.white, size: 28),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center, // ✅ 수직 가운데 정렬
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    description,
                    style: TextStyle(
                      color: caption,
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
