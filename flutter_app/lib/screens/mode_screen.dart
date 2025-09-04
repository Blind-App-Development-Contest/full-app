import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../constants/config.dart';
import '../widgets/aeye_card.dart';
import '../widgets/accessible_text.dart';
import 'setting_screen.dart';
import 'map_screen.dart';
import 'object_detection_screen.dart';

enum AppPreferredMode { camera, navigation }

class ModeScreen extends StatefulWidget {
  const ModeScreen({super.key});

  @override
  State<ModeScreen> createState() => _ModeScreenState();
}

class _ModeScreenState extends State<ModeScreen> {
  static const String kUserNameKey = 'user_name';
  static const String kPreferredModeKey = 'preferred_mode'; // 'camera' | 'navigation'

  String? _userName;
  AppPreferredMode? _preferred;

  @override
  void initState() {
    super.initState();
    _loadUserPrefs();
  }

  Future<void> _loadUserPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    final name = prefs.getString(kUserNameKey);
    final prefStr = prefs.getString(kPreferredModeKey);

    setState(() {
      _userName = (name?.trim().isNotEmpty == true) ? name!.trim() : null;
      if (prefStr == 'camera') {
        _preferred = AppPreferredMode.camera;
      } else if (prefStr == 'navigation') {
        _preferred = AppPreferredMode.navigation;
      } else {
        _preferred = null;
      }
    });
  }

  Future<void> _savePreferred(AppPreferredMode mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      kPreferredModeKey,
      mode == AppPreferredMode.camera ? 'camera' : 'navigation',
    );
    setState(() => _preferred = mode);
  }

  /// 백그라운드에서 선호 모드 저장 (UI 블로킹 없음)
  void _savePreferredInBackground(AppPreferredMode mode) {
    SharedPreferences.getInstance().then((prefs) {
      prefs.setString(
        kPreferredModeKey,
        mode == AppPreferredMode.camera ? 'camera' : 'navigation',
      );
    }).catchError((e) {
      debugPrint('선호 모드 저장 실패: $e');
    });
  }

  Future<void> _openCameraMode(BuildContext context) async {
    // 즉시 UI 상태 업데이트 (사용자에게 빠른 피드백)
    setState(() => _preferred = AppPreferredMode.camera);
    
    // 백그라운드에서 SharedPreferences 저장
    _savePreferredInBackground(AppPreferredMode.camera);
    
    // 먼저 네임드 라우트 시도
    final pushed = await _tryPushNamed(context, '/camera');
    // 실패하면 직접 화면으로 이동
    if (!pushed && context.mounted) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => const ObjectDetectionScreen(),
        ),
      );
    }
  }

  Future<void> _openNavigationMode(BuildContext context) async {
    // 즉시 UI 상태 업데이트 (사용자에게 빠른 피드백)
    setState(() => _preferred = AppPreferredMode.navigation);
    
    // 백그라운드에서 SharedPreferences 저장
    _savePreferredInBackground(AppPreferredMode.navigation);
    
    // 먼저 네임드 라우트 시도
    final pushed = await _tryPushNamed(context, '/navigation');
    // 실패하면 직접 화면으로 이동
    if (!pushed && context.mounted) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => MapScreen(
            backendBaseUrl: AppConfig.backendBaseUrl,
          ),
        ),
      );
    }
  }

  void _openSettings(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    ).then((_) {
      // 설정에서 이름/모드가 바뀌었을 수 있으니 복귀 시 재로딩
      _loadUserPrefs();
    });
  }

  /// 라우트가 등록돼 있으면 pushNamed, 없으면 false 반환
  Future<bool> _tryPushNamed(BuildContext context, String routeName) async {
    try {
      if (Navigator.of(context).canPop()) {
        // 그냥 pushNamed만 시도 (등록 안됐으면 throw)
        await Navigator.of(context).pushNamed(routeName);
      } else {
        await Navigator.of(context).pushNamed(routeName);
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const divider = Color(0xFF22304A);
    const caption = Color(0xFF9AA3B2);

    // 선호 모드 뱃지 텍스트
    String? preferredBadge;
    if (_preferred == AppPreferredMode.camera) {
      preferredBadge = '최근: 카메라';
    } else if (_preferred == AppPreferredMode.navigation) {
      preferredBadge = '최근: 길찾기';
    }

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        actions: [
          IconButton(
            tooltip: '설정',
            onPressed: () => _openSettings(context),
            icon: const Icon(Icons.settings_outlined, color: Colors.white),
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              AeyeCard(
                title: _userName == null ? 'A:EYE' : '안녕하세요, $_userName님',
                subtitle: '모드 선택',
              ),
              if (preferredBadge != null) ...[
                Align(
                  alignment: Alignment.centerRight,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: const Color(0xFF151C2C),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: divider.withValues(alpha: 0.35)),
                    ),
                    child: Text(
                      preferredBadge,
                      style: TextStyle(
                        color: caption,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
              ],
              _ModeCard(
                icon: Icons.photo_camera_outlined,
                title: '카메라 모드',
                description: '실시간 장애물 탐지 및 안전 안내',
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
  final double height;

  const _ModeCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.panel,
    required this.divider,
    required this.caption,
    required this.onTap,
    this.height = 110,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      splashColor: Colors.white.withValues(alpha: 0.1),
      highlightColor: Colors.white.withValues(alpha: 0.05),
      child: Container(
        height: height,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: panel,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: divider.withValues(alpha: 0.25)),
        ),
        child: Row(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: divider.withValues(alpha: 0.4)),
              ),
              child: Icon(icon, color: Colors.white, size: 28),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  AccessibleTitle(
                    title,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 6),
                  AccessibleDescription(
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
