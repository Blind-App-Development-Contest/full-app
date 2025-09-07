import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
import '../widgets/accessible_text.dart';
import '../services/voice_service.dart';
import '../services/api_service.dart';
import '../utils/voice_utils.dart';
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
  // ignore: non_constant_identifier_names
  double? step_length_cm; // 백엔드와 동일한 변수명 사용
  VoiceService? _voiceService;
  
  // 음성인식 상태 관리
  bool _isListening = false;

  bool get _hasChangedFromSettings =>
      widget.fromSettings &&
      step_length_cm != null &&
      step_length_cm!.toInt() != widget.initialStepLengthCm;

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
    debugPrint("🎯 보폭 측정 시작 버튼 클릭");
    
    // 클릭 음성 피드백
    _speakText('측정 시작');

    if (!mounted) {
      debugPrint("❌ Widget이 마운트되지 않음");
      return;
    }

    // 즉시 카메라 화면으로 이동
    debugPrint("🎥 CameraMeasurementScreen으로 이동 시작");
    
    // 임시로 음성 안내 제거 (디버깅용)
    // if (_voiceService != null) {
    //   _voiceService!.speak("보폭 측정을 시작합니다.").catchError((e) {
    //     debugPrint('❌ 음성 안내 실패: $e');
    //   });
    // }

    final result = await Navigator.push<int>(
      context,
      MaterialPageRoute(
        builder:
            (context) => CameraMeasurementScreen(
              isFromSettings: widget.fromSettings, // 설정 여부 전달
            ),
      ),
    );

    debugPrint("🔙 CameraMeasurementScreen에서 돌아옴, 결과: $result");

    if (result != null) {
      setState(() {
        _measured = true;
        _resultConfirmed = false; // 재측정 시 결과 확인 리셋
        step_length_cm = result.toDouble(); // 백엔드와 동일한 변수명
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
        await Future.delayed(const Duration(milliseconds: 500));
        // 결과 확인 후 자동 완료
        setState(() {
          _resultConfirmed = true;
        });
        _saveAndPop();
      } else {
        await _voiceService!.speak("다음 단계로 진행합니다.", speed: 0.9);
        await Future.delayed(const Duration(milliseconds: 500));
        // 결과 확인 후 자동 다음 단계 진행
        setState(() {
          _resultConfirmed = true;
        });
        _goNext();
      }
    } catch (e) {
      debugPrint('❌ 음성 안내 실패: $e');
    }
  }

  // 온보딩 플로우: 다음 단계(VoiceScreen)로
  void _goNext() async {
    // 클릭 음성 피드백
    _speakText('다음');
    
    if (step_length_cm != null) {
      final stepLengthCm = step_length_cm!.toInt();

      // 데이터베이스에 보폭 저장 (온보딩 플로우)
      try {
        debugPrint('📏 온보딩 보폭 저장 시도: ${stepLengthCm}cm');
        await ApiService().saveStepLength(stepLengthCm.toDouble());
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
    // 클릭 음성 피드백
    _speakText('저장');
    
    if (step_length_cm != null) {
      final stepLengthCm = step_length_cm!.toInt();

      // 데이터베이스에 보폭 저장
      try {
        debugPrint('📏 보폭 설정 저장 시도: ${stepLengthCm}cm');
        await ApiService().saveStepLength(stepLengthCm.toDouble());
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
    // 클릭 음성 피드백
    _speakText('뒤로가기');
    if (_hasChangedFromSettings) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: AccessibleText('변경사항이 저장되지 않았습니다.')));
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
            ? (step_length_cm != null &&
                step_length_cm!.toInt() != widget.initialStepLengthCm)
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
                title: const AccessibleTitle(
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

      body: GestureDetector(
        onTap: () {
          // 배경 터치 시 키보드 내리기
          FocusScope.of(context).unfocus();
        },
        child: SafeArea(
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
                      child: AccessibleDescription(
                        widget.fromSettings
                            ? '보폭을 다시 측정해 저장할 수 있습니다.'
                            : 'A아이 앱에 오신 것을 환영합니다. 먼저 보폭측정을 시작해주세요.',
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
                        AccessibleTitle(
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
                          child: const AccessibleText('보폭 측정 시작'),
                        ),
                      ),
                    ),

                    const SizedBox(height: 14),
                    Column(
                      children: [
                        AccessibleText(
                          widget.fromSettings
                              ? (step_length_cm == null
                                  ? '현재 설정된 보폭: ${widget.initialStepLengthCm ?? '-'} cm'
                                  : '새 보폭: ${step_length_cm!.toInt()} cm')
                              : _measured
                              ? '측정된 보폭: ${step_length_cm!.toInt()} cm'
                              : '평소처럼 자연스럽게 걸으며 걸음 수를 세어주세요',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: hint,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        if (_measured && !_resultConfirmed) ...[
                          const SizedBox(height: 8),
                          AccessibleDescription(
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
                          AccessibleDescription(
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
  
  /// 음성인식 토글 함수 - 실제 STT 연결
  void _toggleVoiceRecognition() async {
    if (_voiceService == null) return;

    setState(() {
      _isListening = !_isListening;
    });

    if (_isListening) {
      _speakText('음성인식을 시작합니다. 측정시작이라고 말씀해주세요.');
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
      debugPrint('🎤 보폭 화면에서 인식된 텍스트: $recognizedText');
      
      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);
      
      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리
  void _processVoiceCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 보폭 화면 음성 명령 처리: $lowerCommand');

    if (lowerCommand.contains('측정') || lowerCommand.contains('시작')) {
      if (!_measured) {
        _speakText('보폭 측정을 시작합니다.');
        _startMeasure();
      } else {
        _speakText('이미 측정이 완료되었습니다.');
      }
    } else if (lowerCommand.contains('다시') || lowerCommand.contains('재측정')) {
      _speakText('보폭을 다시 측정합니다.');
      _startMeasure();
    } else if (lowerCommand.contains('다음') || lowerCommand.contains('완료') || lowerCommand.contains('저장')) {
      if (_measured && _resultConfirmed) {
        _speakText('보폭 설정을 저장하고 다음 단계로 진행합니다.');
        if (widget.fromSettings) {
          _saveAndPop();
        } else {
          _goNext();
        }
      } else if (_measured && !_resultConfirmed) {
        _speakText('측정 결과를 먼저 확인해주세요.');
      } else {
        _speakText('보폭 측정을 먼저 진행해주세요.');
      }
    } else if (lowerCommand.contains('뒤로') || lowerCommand.contains('취소')) {
      _speakText('이전 화면으로 돌아갑니다.');
      if (widget.fromSettings) {
        _backWithoutSave();
      } else {
        Navigator.pop(context);
      }
    } else {
      final statusText = _measured 
        ? '보폭이 측정되었습니다. 다음 단계로 진행하려면 다음이라고 말씀해주세요.'
        : '보폭 측정 화면입니다. 측정하기라고 말씀해주세요.';
      _speakText(statusText);
    }
  }

  /// 음성 출력 함수
  void _speakText(String text) async {
    await VoiceUtils.speakWithService(_voiceService, text);
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
