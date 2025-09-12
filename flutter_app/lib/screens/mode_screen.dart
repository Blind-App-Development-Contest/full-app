import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:provider/provider.dart';

import '../constants/config.dart';
import '../widgets/aeye_card.dart';
import '../widgets/accessible_text.dart';
import '../widgets/caregiver_button.dart';

import '../services/voice_service.dart';
import '../utils/voice_utils.dart';

import 'setting_screen.dart';
import 'map_screen.dart';
import 'camera_mode_screen.dart';

enum AppPreferredMode { camera, navigation }

class ModeScreen extends StatefulWidget {
  const ModeScreen({super.key});

  @override
  State<ModeScreen> createState() => _ModeScreenState();
}

class _ModeScreenState extends State<ModeScreen> {
  static const String kUserNameKey = 'user_name';
  static const String kPreferredModeKey =
      'preferred_mode'; // 'camera' | 'navigation'

  String? _userName;
  AppPreferredMode? _preferred;

  // 음성인식 상태 관리
  bool _isListening = false;
  VoiceService? _voiceService;

  @override
  void initState() {
    super.initState();
    _loadUserPrefs();
    _initializeVoiceService();
  }

  void _initializeVoiceService() {
    try {
      _voiceService = Provider.of<VoiceService>(context, listen: false);
      debugPrint('✅ ModeScreen VoiceService 초기화 성공');
    } catch (e) {
      debugPrint('❌ ModeScreen VoiceService 초기화 실패: $e');
    }
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

  /// 백그라운드에서 선호 모드 저장 (UI 블로킹 없음)
  void _savePreferredInBackground(AppPreferredMode mode) {
    SharedPreferences.getInstance()
        .then((prefs) {
          prefs.setString(
            kPreferredModeKey,
            mode == AppPreferredMode.camera ? 'camera' : 'navigation',
          );
        })
        .catchError((e) {
          debugPrint('선호 모드 저장 실패: $e');
        });
  }

  Future<void> _openCameraMode(BuildContext context) async {
    setState(() => _preferred = AppPreferredMode.camera);
    _savePreferredInBackground(AppPreferredMode.camera);
    final pushed = await _tryPushNamed(context, '/camera');
    if (!pushed && context.mounted) {
      await Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const CameraModeScreen()),
      );
    }
  }

  Future<void> _openNavigationMode(BuildContext context) async {
    setState(() => _preferred = AppPreferredMode.navigation);
    _savePreferredInBackground(AppPreferredMode.navigation);
    final pushed = await _tryPushNamed(context, '/navigation');
    if (!pushed && context.mounted) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => MapScreen(backendBaseUrl: AppConfig.backendBaseUrl),
        ),
      );
    }
  }

  void _openSettings(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    ).then((_) => _loadUserPrefs());
  }

  Future<bool> _tryPushNamed(BuildContext context, String routeName) async {
    try {
      await Navigator.of(context).pushNamed(routeName);
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
            onPressed: () {
              _speakText('설정');
              _openSettings(context);
            },
            icon: const Icon(Icons.settings_outlined, color: Colors.white),
          ),
        ],
      ),
      floatingActionButton: Container(
        decoration: BoxDecoration(
          color: _isListening ? Colors.red : Colors.blue,
          shape: BoxShape.circle,
        ),
        child: FloatingActionButton(
          onPressed: _toggleVoiceRecognition,
          backgroundColor: Colors.transparent,
          elevation: 0,
          child: Icon(
            _isListening ? Icons.mic : Icons.mic_none,
            color: Colors.white,
          ),
        ),
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
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFF151C2C),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(
                        color: divider.withValues(alpha: 0.35),
                      ),
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
                onTap: () {
                  _speakText('카메라 모드');
                  _openCameraMode(context);
                },
              ),
              const SizedBox(height: 16),
              _ModeCard(
                icon: Icons.route_outlined,
                title: '길찾기 모드',
                description: '음성 길 안내 및 경로 탐색',
                panel: panel,
                divider: divider,
                caption: caption,
                onTap: () {
                  _speakText('길찾기 모드');
                  _openNavigationMode(context);
                },
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

              // ✅ 보호자 호출 버튼 (uuid 전송)
              const SizedBox(height: 16),
              CaregiverButton(
                backendBaseUrl: AppConfig.backendBaseUrl,
                panel: panel,
                divider: divider,
                caption: caption,
                onCompleted: (ok, msg) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        ok
                            ? (msg ?? '보호자에게 호출을 전송했습니다.')
                            : (msg ?? '호출에 실패했습니다.'),
                      ),
                    ),
                  );
                },
              ),

              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }

  /// 음성인식 토글 함수 - 실제 STT 연결
  void _toggleVoiceRecognition() async {
    if (_voiceService == null) return;

    setState(() {
      _isListening = !_isListening;
    });

    if (_isListening) {
      _speakText('음성인식을 시작합니다.');
      // STT 시작
      try {
        await _voiceService!.startListening();
        _voiceService!.addListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ STT 시작 실패: $e');
        setState(() => _isListening = false);
      }
    } else {
      _speakText('음성인식을 중지합니다.');
      // STT 중지
      try {
        await _voiceService!.stopListeningAndProcess();
        _voiceService!.removeListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ STT 중지 실패: $e');
      }
    }
  }

  /// VoiceService 상태 변경 리스너
  void _onVoiceServiceUpdate() {
    if (_voiceService == null) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty && _isListening) {
      debugPrint('🎤 모드 화면에서 인식된 텍스트: $recognizedText');

      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리
  void _processVoiceCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 모드 화면 음성 명령 처리: $lowerCommand');

    if (lowerCommand.contains('카메라') || lowerCommand.contains('사진')) {
      _speakText('카메라 모드로 이동합니다.');
      _openCameraMode(context);
    } else if (lowerCommand.contains('지도') ||
        lowerCommand.contains('길찾기') ||
        lowerCommand.contains('네비게이션')) {
      _speakText('길찾기 모드로 이동합니다.');
      _openNavigationMode(context);
    } else if (lowerCommand.contains('설정')) {
      _speakText('설정 화면으로 이동합니다.');
      _openSettings(context);
    } else {
      _speakText('모드 선택 화면입니다. 카메라, 길찾기, 또는 설정을 말씀해주세요.');
    }
  }

  /// 음성 출력 함수
  void _speakText(String text) async {
    await VoiceUtils.speakWithService(_voiceService, text);
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

  const _ModeCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.panel,
    required this.divider,
    required this.caption,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      splashColor: Colors.white.withValues(alpha: 0.1),
      highlightColor: Colors.white.withValues(alpha: 0.05),
      child: Container(
        height: 110,
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
