import 'package:flutter/material.dart';
import '../models/step_measurement_result.dart';
import 'step_screen.dart';
import 'voice_screen.dart';
import 'guardian_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // 통일된 변수명 사용 (StepMeasurementResult와 일치)
  double stepLength = StepMeasurementResult.defaultStepLengthCm;  // 보폭 (cm)
  String voiceGender = '여성';     // '여성' | '남성'
  double voiceSpeed = 1.0;        // 0.5 ~ 2.0
  int guardians = 0;              // 등록된 보호자 수

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const divider = Color(0xFF22304A);
    const caption = Color(0xFF9AA3B2);

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        backgroundColor: bg,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        titleSpacing: 0,
        title: const Text(
          '설정',
          style: TextStyle(
            color: Colors.white,
            fontSize: 28,
            fontWeight: FontWeight.w900,
          ),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 상단 설명
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: Text(
                '앱 설정을 변경할 수 있습니다',
                style: TextStyle(
                  color: Colors.white.withOpacity(0.8),
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),

            // 보폭 설정
            _SettingTile(
              panel: panel,
              divider: divider,
              captionColor: caption,
              leadingIcon: Icons.near_me_outlined,
              title: '보폭 설정',
              subtitle: '현재: ${stepLength.toStringAsFixed(0)}cm',
              onTap: () async {
                final result = await Navigator.push<int>(
                  context,
                  MaterialPageRoute(
                      builder: (_) => StepScreen(
                        fromSettings: true,
                        initialStepLengthCm: stepLength.toInt(),
                      )
                  ),
                );
                
                if (result != null) {
                  if (mounted) {
                    setState(() {
                      stepLength = result.toDouble();
                    });
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('보폭이 ${result}cm로 변경되었습니다.')),
                    );
                  }
                }
              },
            ),
            const SizedBox(height: 16),

            // 음성 설정
            _SettingTile(
              panel: panel,
              divider: divider,
              captionColor: caption,
              leadingIcon: Icons.volume_up_outlined,
              title: '음성 설정',
              subtitle: '$voiceGender 음성, ${voiceSpeed.toStringAsFixed(0)}배속',
              onTap: () async {
                await Navigator.push(
                  context,
                  MaterialPageRoute(
                      builder: (_) => const VoiceScreen(
                        fromSettings: true,
                      )
                  ),
                );
                // TODO: 되돌아오면 음성 값 갱신
                setState(() {});
              },
            ),
            const SizedBox(height: 16),

            // 보호자 설정
            _SettingTile(
              panel: panel,
              divider: divider,
              captionColor: caption,
              leadingIcon: Icons.person_outline,
              title: '보호자 설정',
              subtitle: '└ ($guardians)',
              onTap: () async {
                await Navigator.push(
                  context,
                  MaterialPageRoute(
                      builder: (_) => const GuardianScreen(
                        fromSettings: true,
                      )
                  ),
                );
                // TODO: 되돌아오면 보호자 수 갱신
                setState(() {});
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _SettingTile extends StatelessWidget {
  final Color panel;
  final Color divider;
  final Color captionColor;
  final IconData leadingIcon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _SettingTile({
    required this.panel,
    required this.divider,
    required this.captionColor,
    required this.leadingIcon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: panel,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: divider.withOpacity(0.25)),
        ),
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
                border: Border.all(color: divider.withOpacity(0.4)),
              ),
              child: Icon(leadingIcon, color: Colors.white, size: 24),
            ),
            const SizedBox(width: 14),

            // 타이틀/서브
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                      )),
                  const SizedBox(height: 6),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: captionColor,
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
                border: Border.all(color: divider.withOpacity(0.4)),
              ),
              child: const Icon(Icons.edit_outlined, color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }
}
