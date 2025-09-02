import 'package:flutter/material.dart';
import '../models/step_measurement_result.dart';
import '../widgets/accessible_text.dart';
import '../services/api_service.dart';
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
  double stepLength = StepMeasurementResult.defaultStepLengthCm; // 보폭 (cm)
  String voiceGender = '여성'; // '여성' | '남성'
  double voiceSpeed = 1.0; // 0.5 ~ 2.0
  int guardians = 0; // 등록된 보호자 수
  
  // 측정 완료 상태 관리
  bool measurementCompleted = false;
  String? completionMessage;

  @override
  void initState() {
    super.initState();
    _handleMeasurementCompletion();
    _loadUserSettings(); // 사용자 설정 불러오기
  }
  
  void _handleMeasurementCompletion() {
    // 화면이 완전히 로드된 후 arguments 처리
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final args = ModalRoute.of(context)?.settings.arguments as Map<String, dynamic>?;
      
      if (args != null && args['measurement_completed'] == true) {
        setState(() {
          measurementCompleted = true;
          stepLength = args['stepLength']?.toDouble() ?? stepLength;
          completionMessage = args['message'] as String?;
        });
        
        // 시각장애인용 음성 안내
        _announceCompletion();
      }
    });
  }
  
  // 사용자 설정 불러오기 (온보딩 정보 포함)
  void _loadUserSettings() async {
    try {
      debugPrint('📊 사용자 설정 불러오기 시도');
      
      // 현재 ApiService에 개별 getter 메서드가 없으므로 기본값 사용
      // TODO: 실제 구현시 ApiService에 다음 메서드들 추가:
      // - getStepLength(): 저장된 보폭 가져오기
      // - getVoiceSettings(): 음성 설정 가져오기
      // - getGuardianInfo(): 보호자 정보 가져오기
      
      debugPrint('✅ 사용자 설정 불러오기 완료 (기본값 사용)');
    } catch (e) {
      debugPrint('❌ 사용자 설정 불러오기 실패: $e');
    }
  }

  void _announceCompletion() async {
    if (completionMessage != null) {
      // 음성 안내: 측정 완료 메시지
      debugPrint('🔊 음성 안내: $completionMessage');
      
      // 1초 후 다음 단계 안내
      await Future.delayed(const Duration(seconds: 1));
      
      if (mounted) {
        debugPrint('🔊 음성 안내: 다음 단계로 버튼을 눌러서 음성 설정을 진행할 수 있습니다.');
      }
    }
  }

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
        title: const AccessibleTitle(
          '설정',
          style: TextStyle(
            color: Colors.white,
            fontSize: 28,
            fontWeight: FontWeight.w900,
          ),
        ),
      ),
      body: GestureDetector(
        onTap: () {
          // 배경 터치 시 키보드 내리기
          FocusScope.of(context).unfocus();
        },
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
          child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 상단 설명
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: AccessibleDescription(
                '앱 설정을 변경할 수 있습니다',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.8),
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),

            // 보폭 설정 (시각장애인 접근성 강화)
            Semantics(
              label: measurementCompleted 
                ? '보폭 측정이 완료되었습니다. 측정된 보폭은 ${stepLength.toStringAsFixed(0)}센티미터입니다.'
                : '보폭 설정하기. 현재 보폭은 ${stepLength.toStringAsFixed(0)}센티미터입니다.',
              button: true,
              child: _SettingTile(
                panel: panel,
                divider: divider,
                captionColor: caption,
                leadingIcon: measurementCompleted ? Icons.check_circle : Icons.near_me_outlined,
                title: measurementCompleted ? '보폭 측정 완료' : '보폭 설정',
                subtitle: measurementCompleted 
                  ? '측정 완료: ${stepLength.toStringAsFixed(0)}cm ✅'
                  : '현재: ${stepLength.toStringAsFixed(0)}cm',
              onTap: () async {
                final result = await Navigator.push<int>(
                  context,
                  MaterialPageRoute(
                    builder:
                        (_) => StepScreen(
                          fromSettings: true,
                          initialStepLengthCm: stepLength.toInt(),
                        ),
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
                    builder: (_) => const VoiceScreen(fromSettings: true),
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
                    builder: (_) => const GuardianScreen(fromSettings: true),
                  ),
                );
                // TODO: 되돌아오면 보호자 수 갱신
                setState(() {});
              },
            ),
            
            // 측정 완료 시 다음 단계 버튼 표시 (시각장애인 접근성 강화)
            if (measurementCompleted) ...[
              const SizedBox(height: 24),
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(bottom: 16),
                child: Semantics(
                  label: '다음 단계로 이동하기. 음성 설정을 진행합니다.',
                  button: true,
                  child: ElevatedButton.icon(
                    onPressed: () {
                      // 음성 피드백
                      debugPrint('🔊 음성 안내: 음성 설정 화면으로 이동합니다.');
                      
                      // 온보딩 플로우 음성 설정 화면으로 이동 (fromSettings: false)
                      Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (context) => const VoiceScreen(fromSettings: false),
                        ),
                      );
                    },
                    icon: const Icon(Icons.arrow_forward_ios, color: Colors.white, size: 20),
                    label: const AccessibleTitle(
                      '다음 단계로 (음성 설정)',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.bold
                      ),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF00A6FF),
                      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      elevation: 2,
                    ),
                  ),
                ),
              ),
            ],
          ],
          ),
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
          border: Border.all(color: divider.withValues(alpha: 0.25)),
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
                border: Border.all(color: divider.withValues(alpha: 0.4)),
              ),
              child: Icon(leadingIcon, color: Colors.white, size: 24),
            ),
            const SizedBox(width: 14),

            // 타이틀/서브
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
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
                border: Border.all(color: divider.withValues(alpha: 0.4)),
              ),
              child: const Icon(Icons.edit_outlined, color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }
}
