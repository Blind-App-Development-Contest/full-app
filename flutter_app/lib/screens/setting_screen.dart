import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/step_measurement_result.dart';
import '../services/api_service.dart';
import '../services/voice_service.dart';
import '../widgets/accessible_text.dart';
import '../utils/voice_utils.dart';
import 'step_screen.dart';
import 'voice_screen.dart';
import 'guardian_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // 백엔드와 동일한 변수명 사용
  // ignore: non_constant_identifier_names
  double step_length_cm = StepMeasurementResult.defaultStepLengthCm; // 보폭 (cm)
  String voiceGender = '여성'; // '여성' | '남성'
  double voiceSpeed = 1.0; // 0.5 ~ 2.0
  int guardians = 0; // 등록된 보호자 수

  // 측정 완료 상태 관리
  bool measurementCompleted = false;
  String? completionMessage;

  // 설정 로드 상태 관리
  bool _isLoadingSettings = false;

  // 음성 서비스
  VoiceService? _voiceService;

  // 음성인식 상태 관리
  bool _isListening = false;

  @override
  void initState() {
    super.initState();
    _initializeVoiceService();
    _handleMeasurementCompletion();
    _loadUserSettings(); // 사용자 설정 불러오기
  }

  @override
  void dispose() {
    // VoiceService 리스너 정리
    _voiceService?.removeListener(_onVoiceServiceUpdate);
    super.dispose();
  }

  void _initializeVoiceService() {
    try {
      _voiceService = Provider.of<VoiceService>(context, listen: false);
      debugPrint('✅ SettingsScreen VoiceService 초기화 성공');
    } catch (e) {
      debugPrint('❌ SettingsScreen VoiceService 초기화 실패: $e');
    }
  }

  void _handleMeasurementCompletion() {
    // 화면이 완전히 로드된 후 arguments 처리
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final args =
          ModalRoute.of(context)?.settings.arguments as Map<String, dynamic>?;

      if (args != null && args['measurement_completed'] == true) {
        setState(() {
          measurementCompleted = true;
          step_length_cm = args['stepLength']?.toDouble() ?? step_length_cm;
          completionMessage = args['message'] as String?;
        });

        // 시각장애인용 음성 안내
        _announceCompletion();
      }
    });
  }

  // 사용자 설정 불러오기 (온보딩 정보 포함)
  void _loadUserSettings() async {
    // 이미 로딩 중이면 중복 호출 방지
    if (_isLoadingSettings) {
      debugPrint('⚠️ 이미 설정 로딩 중 - 중복 호출 방지');
      return;
    }

    _isLoadingSettings = true;

    try {
      debugPrint('📊 사용자 설정 불러오기 시도');

      final settings = await ApiService().getUserSettings();
      if (settings != null) {
        setState(() {
          // 사용자 이름 로드
          if (settings.containsKey('user_name') &&
              settings['user_name'] != null) {
            debugPrint('✅ 서버에서 사용자 이름 로드: ${settings['user_name']}');
          }

          // 보폭 설정 로드 (서버 필드명: step_length)
          if (settings.containsKey('step_length') &&
              settings['step_length'] != null) {
            step_length_cm = (settings['step_length'] as num).toDouble();
            debugPrint(
              '✅ 서버에서 보폭 설정 로드: ${step_length_cm.toStringAsFixed(1)}cm',
            );
          } else if (settings.containsKey('step_length_cm') &&
              settings['step_length_cm'] != null) {
            step_length_cm = (settings['step_length_cm'] as num).toDouble();
            debugPrint(
              '✅ 서버에서 보폭 설정 로드 (legacy): ${step_length_cm.toStringAsFixed(1)}cm',
            );
          }

          // 음성 설정 로드 (서버 필드명: voice_speed, voice_gender)
          if (settings.containsKey('voice_speed') &&
              settings['voice_speed'] != null) {
            final dynamic serverSpeed = settings['voice_speed'];
            if (serverSpeed is int) {
              // 서버 값(퍼센트)을 배속으로 변환 (백엔드와 동일한 로직)
              voiceSpeed = serverSpeed / 400.0;
              debugPrint(
                '✅ 서버에서 음성 속도 로드: $serverSpeed% -> ${voiceSpeed.toStringAsFixed(2)}x',
              );
            } else if (serverSpeed is double) {
              voiceSpeed = serverSpeed;
              debugPrint(
                '✅ 서버에서 음성 속도 로드 (직접): ${voiceSpeed.toStringAsFixed(2)}x',
              );
            }
          }

          if (settings.containsKey('voice_gender') &&
              settings['voice_gender'] != null) {
            final String gender =
                settings['voice_gender'].toString().toLowerCase();
            voiceGender = (gender == 'male' || gender == 'm') ? '남성' : '여성';
            debugPrint('✅ 서버에서 음성 성별 로드: $gender -> $voiceGender');
          }

          // 보호자 정보 로드 (서버 필드명: caregiver_name, caregiver_phone)
          if (settings.containsKey('caregiver_name') &&
              settings['caregiver_name'] != null &&
              settings['caregiver_name'].toString().isNotEmpty) {
            guardians = 1; // 보호자가 등록되어 있으면 1명
            debugPrint(
              '✅ 서버에서 보호자 정보 로드: ${settings['caregiver_name']} (${settings['caregiver_phone']})',
            );
          } else {
            guardians = 0;
          }
        });
        debugPrint('✅ 서버에서 사용자 설정 불러오기 완료');

        // VoiceService에도 새로운 설정 반영
        if (_voiceService != null) {
          _voiceService!.setVoiceSpeed(voiceSpeed);
          _voiceService!.setVoiceGender(
            voiceGender == '남성' ? 'male' : 'female',
          );
          debugPrint('🔊 VoiceService에 서버 설정 반영: ${voiceSpeed}x, $voiceGender');
        }

        // null 값들이 많은 경우 로그로 알림
        final nullFields = <String>[];
        if (settings['voice_speed'] == null) nullFields.add('voice_speed');
        if (settings['voice_gender'] == null) nullFields.add('voice_gender');
        if (settings['step_length'] == null) nullFields.add('step_length');
        if (settings['caregiver_name'] == null)
          nullFields.add('caregiver_name');

        if (nullFields.isNotEmpty) {
          debugPrint('⚠️ 서버에서 null인 필드들: ${nullFields.join(', ')} - 기본값 유지');
        }
      } else {
        // 서버 연결 실패 시 현재 설정값 유지 (기본값으로 덮어쓰지 않음)
        debugPrint('⚠️ 서버 연결 실패 - 현재 설정값 유지');
        debugPrint(
          '📋 현재 설정: 보폭=${step_length_cm}cm, 음성=$voiceGender ${voiceSpeed}x, 보호자=$guardians명',
        );
      }
    } catch (e) {
      debugPrint('❌ 사용자 설정 불러오기 실패: $e');
      // 오류 발생 시에도 현재 설정값 유지 (첫 실행시에만 기본값 사용)
      if (step_length_cm == 0.0 && voiceSpeed == 0.0) {
        debugPrint('🔧 첫 실행 - 기본값 설정');
        _loadLocalDefaultSettings();
      } else {
        debugPrint('📋 설정 로드 실패 - 기존 값 유지');
      }
    } finally {
      _isLoadingSettings = false;
    }
  }

  // 서버 연결 실패 시 로컬 기본값 설정
  void _loadLocalDefaultSettings() {
    setState(() {
      step_length_cm = StepMeasurementResult.defaultStepLengthCm;
      voiceGender = '여성';
      voiceSpeed = 1.0;
      guardians = 0;
    });
    debugPrint(
      '✅ 로컬 기본값으로 설정 완료 (보폭: ${step_length_cm.toStringAsFixed(0)}cm, 음성: $voiceGender ${voiceSpeed.toStringAsFixed(1)}배속, 보호자: $guardians명)',
    );
  }

  void _announceCompletion() async {
    if (completionMessage != null && _voiceService != null) {
      try {
        // 음성 안내: 측정 완료 메시지
        await VoiceUtils.speakWithService(
          _voiceService,
          completionMessage!,
          speed: 1.0,
        );

        // 1초 후 상세 안내
        await Future.delayed(const Duration(seconds: 1));

        if (mounted) {
          await VoiceUtils.speakWithService(
            _voiceService,
            "보폭이 ${step_length_cm.toStringAsFixed(0)}센티미터로 측정되었습니다. "
            "다음 단계로 버튼을 눌러서 음성 설정을 진행할 수 있습니다.",
            speed: 0.9,
          );
        }
      } catch (e) {
        debugPrint('❌ 측정 완료 음성 안내 실패: $e');
      }
    }
  }

  /// 보폭 측정 완료 시 상세 음성 안내 (시각장애인 전용)
  void _announceStepMeasurementComplete(int stepLengthCm) async {
    if (_voiceService == null) return;

    try {
      // 1단계: 측정 완료 알림
      await VoiceUtils.speakWithService(
        _voiceService,
        "보폭 측정이 완료되었습니다!",
        speed: 1.0,
      );

      await Future.delayed(const Duration(milliseconds: 800));

      // 2단계: 측정 결과 안내
      await VoiceUtils.speakWithService(
        _voiceService,
        "측정된 보폭은 $stepLengthCm 센티미터입니다.",
        speed: 0.9,
      );

      await Future.delayed(const Duration(milliseconds: 600));

      // 3단계: 상태 변경 안내
      await VoiceUtils.speakWithService(
        _voiceService,
        "설정 화면에서 보폭 항목이 측정 완료 상태로 변경되었습니다.",
        speed: 0.9,
      );

      await Future.delayed(const Duration(milliseconds: 400));

      // 4단계: 다음 액션 안내
      await VoiceUtils.speakWithService(
        _voiceService,
        "다른 설정을 변경하거나 음성 설정을 진행할 수 있습니다.",
        speed: 0.9,
      );
    } catch (e) {
      debugPrint('❌ 보폭 측정 완료 음성 안내 실패: $e');
    }
  }

  /// 음성 설정 변경 완료 안내 (시각장애인 전용)
  void _announceVoiceSettingsChanged() async {
    if (_voiceService == null) return;

    try {
      await Future.delayed(const Duration(milliseconds: 500));

      await VoiceUtils.speakWithService(
        _voiceService,
        "음성 설정이 업데이트되었습니다. "
        "현재 설정은 $voiceGender 음성, ${voiceSpeed.toStringAsFixed(1)}배속입니다.",
        speed: 0.9,
      );
    } catch (e) {
      debugPrint('❌ 음성 설정 변경 안내 실패: $e');
    }
  }

  /// 보호자 설정 변경 완료 안내 (시각장애인 전용)
  void _announceGuardianSettingsChanged() async {
    if (_voiceService == null) return;

    try {
      await Future.delayed(const Duration(milliseconds: 500));

      final guardianMessage =
          guardians > 0
              ? "보호자 설정이 업데이트되었습니다. 현재 $guardians명의 보호자가 등록되어 있습니다."
              : "보호자 설정이 업데이트되었습니다. 현재 등록된 보호자가 없습니다.";

      await VoiceUtils.speakWithService(
        _voiceService,
        guardianMessage,
        speed: 0.9,
      );
    } catch (e) {
      debugPrint('❌ 보호자 설정 변경 안내 실패: $e');
    }
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

        // 음성 인식 결과 처리를 위한 리스너 등록
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

    // 음성 인식 결과가 있을 때 처리
    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty && _isListening) {
      debugPrint('🎤 설정 화면에서 인식된 텍스트: $recognizedText');

      // 인식 중지
      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      // 인식된 명령 처리
      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리
  void _processVoiceCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 설정 화면 음성 명령 처리: $lowerCommand');

    if (lowerCommand.contains('보폭') || lowerCommand.contains('측정')) {
      _speakText('보폭 설정 화면으로 이동합니다.');
      Navigator.push(
        context,
        MaterialPageRoute(
          builder:
              (_) => StepScreen(
                fromSettings: true,
                initialStepLengthCm: step_length_cm.toInt(),
              ),
        ),
      );
    } else if (lowerCommand.contains('음성') || lowerCommand.contains('목소리')) {
      _speakText('음성 설정 화면으로 이동합니다.');
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => const VoiceScreen(fromSettings: true),
        ),
      );
    } else if (lowerCommand.contains('보호자') || lowerCommand.contains('가족')) {
      _speakText('보호자 설정 화면으로 이동합니다.');
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => const GuardianScreen(fromSettings: true),
        ),
      );
    } else if (lowerCommand.contains('뒤로') || lowerCommand.contains('돌아가')) {
      _speakText('이전 화면으로 돌아갑니다.');
      Navigator.pop(context);
    } else {
      _speakText('설정 화면입니다. 보폭 설정, 음성 설정, 보호자 설정 중 하나를 말씀해주세요.');
    }
  }

  /// 음성 출력 함수
  void _speakText(String text) async {
    await VoiceUtils.speakWithService(_voiceService, text);
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
          onPressed: () {
            _speakText('뒤로가기');
            Navigator.pop(context);
          },
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
                label:
                    measurementCompleted
                        ? '보폭 측정이 완료되었습니다. 측정된 보폭은 ${step_length_cm.toStringAsFixed(0)}센티미터입니다.'
                        : '보폭 설정하기. 현재 보폭은 ${step_length_cm.toStringAsFixed(0)}센티미터입니다.',
                button: true,
                child: _SettingTile(
                  panel: panel,
                  divider: divider,
                  captionColor: caption,
                  leadingIcon:
                      measurementCompleted
                          ? Icons.check_circle
                          : Icons.near_me_outlined,
                  title: measurementCompleted ? '보폭 측정 완료' : '보폭 설정',
                  subtitle:
                      measurementCompleted
                          ? '측정 완료: ${step_length_cm.toStringAsFixed(0)}cm ✅'
                          : '현재: ${step_length_cm.toStringAsFixed(0)}cm',
                  onTap: () async {
                    // 클릭 음성 피드백
                    _speakText('보폭 설정');

                    final result = await Navigator.push<int>(
                      context,
                      MaterialPageRoute(
                        builder:
                            (_) => StepScreen(
                              fromSettings: true,
                              initialStepLengthCm: step_length_cm.toInt(),
                            ),
                      ),
                    );

                    if (result != null) {
                      if (mounted) {
                        setState(() {
                          step_length_cm = result.toDouble();
                          measurementCompleted = true; // 측정 완료 상태로 변경
                          completionMessage = '보폭 측정이 완료되었습니다.';
                        });

                        // 시각장애인용 상세 음성 안내
                        _announceStepMeasurementComplete(result);

                        // 서버에서 최신 설정도 다시 로드
                        _loadUserSettings();
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
                subtitle: '$voiceGender 음성, ${voiceSpeed.toStringAsFixed(1)}배속',
                onTap: () async {
                  // 클릭 음성 피드백
                  _speakText('음성 설정');

                  await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const VoiceScreen(fromSettings: true),
                    ),
                  );
                  // 음성 설정이 변경되었을 수 있으므로 서버에서 최신 설정 로드
                  if (mounted) {
                    _loadUserSettings();

                    // 음성 설정 변경 완료 안내
                    _announceVoiceSettingsChanged();
                  }
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
                subtitle: guardians > 0 ? '$guardians명 등록됨' : '등록된 보호자 없음',
                onTap: () async {
                  // 클릭 음성 피드백
                  _speakText('보호자 설정');

                  await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const GuardianScreen(fromSettings: true),
                    ),
                  );
                  // 보호자 설정이 변경되었을 수 있으므로 서버에서 최신 설정 로드
                  if (mounted) {
                    _loadUserSettings();

                    // 보호자 설정 변경 완료 안내
                    _announceGuardianSettingsChanged();
                  }
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
                        // 클릭 음성 피드백
                        _speakText('다음 단계로 이동합니다.');

                        // 온보딩 플로우 음성 설정 화면으로 이동 (fromSettings: false)
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder:
                                (context) =>
                                    const VoiceScreen(fromSettings: false),
                          ),
                        );
                      },
                      icon: const Icon(
                        Icons.arrow_forward_ios,
                        color: Colors.white,
                        size: 20,
                      ),
                      label: const AccessibleTitle(
                        '다음 단계로 (음성 설정)',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF00A6FF),
                        padding: const EdgeInsets.symmetric(
                          vertical: 20,
                          horizontal: 16,
                        ),
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
