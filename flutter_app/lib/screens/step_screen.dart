import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
import '../services/voice_service.dart';
import '../services/api_service.dart';
import 'voice_screen.dart';
import 'camera_measurement_screen.dart';

class StepScreen extends StatefulWidget {
  const StepScreen({
    super.key,
    this.fromSettings = false, // 설정에서 진입 여부
    this.initialStepLengthCm, // 기존 보폭(cm) — 설정에서 진입 시 비교용
  });

  final bool fromSettings;
  final int? initialStepLengthCm;

  @override
  State<StepScreen> createState() => _StepScreenState();
}

class _StepScreenState extends State<StepScreen> {
  bool _measured = false;
  bool _resultConfirmed = false; // 측정 결과 확인 여부
  double? stepLength; // 통일된 변수명 사용
  VoiceService? _voiceService;

  bool get _hasChangedFromSettings =>
      widget.fromSettings &&
      stepLength != null &&
      stepLength!.toInt() != widget.initialStepLengthCm;

  @override
  void initState() {
    super.initState();
    _initializeVoiceService();
  }

  void _initializeVoiceService() {
    try {
      _voiceService = context.read<VoiceService>();
      debugPrint("🎙️ StepScreen VoiceService Provider에서 가져오기 성공");
      _setupVoiceCommands();
      debugPrint("✅ StepScreen VoiceService 초기화 및 음성 인식 시작 완료");
    } catch (e) {
      debugPrint("❌ StepScreen VoiceService 초기화 실패: $e");
    }
  }

  void _setupVoiceCommands() {
    if (_voiceService == null) return;

    // 자동 측정 모드이므로 음성 인식은 시작하지 않음
    debugPrint("🎙️ StepScreen 초기화 완료 - 자동 측정 모드");
  }

  // 카메라 측정 화면으로 이동 후 결과 받기
  void _startMeasure() async {
    debugPrint("보폭 측정 시작");

    // 음성 안내
    if (_voiceService != null) {
      try {
        await _voiceService!.speak("보폭 측정을 시작합니다.");
      } catch (e) {
        debugPrint('❌ 음성 안내 실패: $e');
      }
    }

    if (!mounted) return;

    final result = await Navigator.push<int>(
      context,
      MaterialPageRoute(
        builder:
            (context) => CameraMeasurementScreen(
              isFromSettings: widget.fromSettings, // 설정 여부 전달
            ),
      ),
    );

    if (result != null) {
      setState(() {
        _measured = true;
        _resultConfirmed = false; // 재측정 시 결과 확인 리셋
        stepLength = result.toDouble(); // 통일된 변수명
      });

      // 측정 완료 후 상세 음성 안내
      _announceResults(result);
    }
  }

  // 측정 완료 후 상세 음성 안내
  Future<void> _announceResults(int stepLengthCm) async {
    if (_voiceService == null) return;

    try {
      // 시각장애인용 상세 음성 안내
      await _voiceService!.speak("보폭 측정 결과를 안내드리겠습니다.");

      await Future.delayed(const Duration(milliseconds: 200));
      await _voiceService!.speak("측정된 평균 보폭은 $stepLengthCm 센티미터 입니다.");

      await Future.delayed(const Duration(milliseconds: 200));
      if (widget.fromSettings) {
        await _voiceService!.speak("측정 결과 확인 버튼을 눌러 설정을 완료하세요.", speed: 0.9);
      } else {
        await _voiceService!.speak("측정 결과 확인 버튼을 눌러 다음 단계로 진행하세요.", speed: 0.9);
      }
    } catch (e) {
      debugPrint('❌ 음성 안내 실패: $e');
    }
  }

  // 온보딩 플로우: 다음 단계(VoiceScreen)로
  void _goNext() async {
    if (stepLength != null) {
      final stepLengthCm = stepLength!.toInt();

      // 데이터베이스에 보폭 저장 (온보딩 플로우)
      try {
        debugPrint('📏 온보딩 보폭 저장 시도: ${stepLengthCm}cm');
        await ApiService().saveStepLength(stepLengthCm);
        debugPrint('✅ 온보딩 보폭 저장 성공');
      } catch (e) {
        debugPrint('❌ 온보딩 보폭 저장 실패: $e');
        // 저장 실패해도 계속 진행 (오프라인 모드 고려)
      }
    }

    if (mounted) {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const VoiceScreen()),
      );
    }
  }

  // 설정에서 진입: 변경사항 저장 후 값 반환
  void _saveAndPop() async {
    if (stepLength != null) {
      final stepLengthCm = stepLength!.toInt();

      // 데이터베이스에 보폭 저장
      try {
        debugPrint('📏 보폭 설정 저장 시도: ${stepLengthCm}cm');
        await ApiService().saveStepLength(stepLengthCm);
        debugPrint('✅ 보폭 설정 저장 성공');
      } catch (e) {
        debugPrint('❌ 보폭 설정 저장 실패: $e');
        // 저장 실패해도 계속 진행 (오프라인 모드 고려)
      }

      if (mounted) {
        Navigator.pop<int>(context, stepLengthCm);
      }
    }
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  void _backWithoutSave() {
    if (_hasChangedFromSettings) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('변경사항이 저장되지 않았습니다.')));
    }
    Navigator.pop(context); // 결과 없이 Pop → 저장 안 됨
  }

  @override
  void dispose() {
    // 음성 인식 사이클 중단
    if (_voiceService != null) {
      _voiceService!.stopAutoRecognitionCycle();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const inner = Color(0xFF151C2C);
    const divider = Color(0xFF22304A);
    const hint = Color(0xFF9AA3B2);

    // 설정 진입 시: 변경되었는지 여부 판단
    final bool hasChangedFromSettings =
        widget.fromSettings
            ? (stepLength != null &&
                stepLength!.toInt() != widget.initialStepLengthCm)
            : false;

    return Scaffold(
      backgroundColor: bg,

      // ✅ 설정에서만 AppBar + 뒤로가기
      appBar:
          widget.fromSettings
              ? AppBar(
                backgroundColor: bg,
                elevation: 0,
                leading: IconButton(
                  icon: const Icon(
                    Icons.arrow_back_ios_new,
                    color: Colors.white,
                  ),
                  onPressed: _backWithoutSave,
                ),
                title: const Text(
                  '보폭 설정',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              )
              : null,

      // ✅ 하단 버튼 분기
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child:
            widget.fromSettings
                ? SetButton(
                  label: '완료',
                  hasChanged: hasChangedFromSettings,
                  onPressed: hasChangedFromSettings ? _saveAndPop : null,
                )
                : _measured && !_resultConfirmed
                ? SetButton(
                  label: '측정 결과 확인',
                  hasChanged: true,
                  onPressed: () {
                    setState(() {
                      _resultConfirmed = true;
                    });
                  },
                )
                : NextButton(
                  label: '다음 단계',
                  enabled: _resultConfirmed,
                  onPressed: _resultConfirmed ? _goNext : null,
                ),
      ),

      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              AeyeCard(
                title: 'A:EYE',
                subtitle: widget.fromSettings ? '보폭 재측정' : '1단계: 보폭 측정',
              ),

              // ── 안내 카드
              _InfoCard(
                panel: panel,
                divider: divider,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.volume_up_outlined,
                      color: Colors.white,
                      size: 20,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        widget.fromSettings
                            ? '보폭을 다시 측정해 저장할 수 있습니다.'
                            : 'A아이 앱에 오신 것을 환영합니다. 먼저 보폭을 측정해주세요.',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 16),

              // ── 보폭 측정 카드
              _InfoCard(
                panel: panel,
                divider: divider,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Row(
                      children: [
                        Icon(
                          Icons.near_me_outlined,
                          color: Colors.white,
                          size: 20,
                        ),
                        SizedBox(width: 8),
                        Text(
                          '보폭 측정',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // 내부 버튼 영역
                    Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 14,
                        horizontal: 16,
                      ),
                      decoration: BoxDecoration(
                        color: inner,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: divider.withValues(alpha: 0.45),
                        ),
                      ),
                      child: SizedBox(
                        height: 52,
                        child: ElevatedButton(
                          onPressed: _startMeasure,
                          style: ElevatedButton.styleFrom(
                            elevation: 0,
                            backgroundColor: const Color(0xFF3A465B),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                            textStyle: const TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          child: const Text('보폭 측정 시작'),
                        ),
                      ),
                    ),

                    const SizedBox(height: 14),
                    Column(
                      children: [
                        Text(
                          widget.fromSettings
                              ? (stepLength == null
                                  ? '현재 설정된 보폭: ${widget.initialStepLengthCm ?? '-'} cm'
                                  : '새 보폭: ${stepLength!.toInt()} cm')
                              : _measured
                              ? '측정된 보폭: ${stepLength!.toInt()} cm'
                              : '카메라를 발 위에서 내려다보며 평소처럼 자연스럽게 10걸음을 걸어주세요',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: hint,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        if (_measured && !_resultConfirmed) ...[
                          const SizedBox(height: 8),
                          Text(
                            '측정이 완료되었습니다. 결과를 확인해주세요.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: Colors.green.shade300,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                        if (_resultConfirmed) ...[
                          const SizedBox(height: 8),
                          Text(
                            '✓ 보폭이 설정되었습니다. 다음 단계로 진행해주세요.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: Colors.blue.shade300,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 120), // 스크롤 여유
            ],
          ),
        ),
      ),
    );
  }
}

/// 공통 카드 컨테이너
class _InfoCard extends StatelessWidget {
  final Widget child;
  final Color panel;
  final Color divider;

  const _InfoCard({
    required this.child,
    required this.panel,
    required this.divider,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
      decoration: BoxDecoration(
        color: panel,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: divider.withValues(alpha: 0.25)),
      ),
      child: child,
    );
  }
}
