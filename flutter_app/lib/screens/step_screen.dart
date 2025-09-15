import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
import '../widgets/accessible_text.dart';
import 'package:flutter/services.dart';
import '../services/voice_service.dart';
import '../services/api_service.dart';
import '../utils/voice_utils.dart';
import '../utils/voice_recognition_helper.dart';
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
  VoiceRecognitionHelper? _voiceHelper;

  // 음성인식 상태 관리
  bool _isListening = false;
  bool _isConfirming = false; // 확인 중인지 표시
  double? _currentDistanceMeters; // 카메라에서 측정된 거리 저장

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

      // VoiceRecognitionHelper 초기화
      _voiceHelper = VoiceRecognitionHelper(voiceService: _voiceService!);

      debugPrint("🎙️ StepScreen VoiceService 및 헬퍼 Provider에서 가져오기 성공");
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

    // 현재 진행 중인 음성 인식/리스너 정리 후 진입 (레이스 방지)
    try {
      _voiceHelper?.stopListening();
      if (_voiceService != null) {
        _voiceService!.stopAutoRecognitionCycle();
        _voiceService!.removeListener(_onVoiceServiceUpdate);
      }
    } catch (_) {}

    if (!mounted) {
      debugPrint("❌ Widget이 마운트되지 않음");
      return;
    }

    // 즉시 카메라 화면으로 이동
    debugPrint("🎥 CameraMeasurementScreen으로 이동 시작");

    final result = await Navigator.push<double>(
      context,
      MaterialPageRoute(builder: (context) => const CameraMeasurementScreen()),
    );

    debugPrint("🔙 CameraMeasurementScreen에서 돌아옴, 결과: $result");

    if (result != null) {
      // CameraMeasurementScreen에서 거리(미터)를 받음
      final measuredDistanceMeters = result;
      debugPrint(
        "📏 카메라에서 측정된 거리: ${measuredDistanceMeters.toStringAsFixed(1)}m",
      );

      if (mounted) {
        setState(() {
          _measured = true;
          _resultConfirmed = false; // 재측정 시 결과 확인 리셋
        });
      }

      // 거리 측정 완료 후 걸음 수 입력 안내
      _announceDistanceMeasured(measuredDistanceMeters);
    }
  }

  // 거리 측정 완료 후 걸음 수 입력 안내
  Future<void> _announceDistanceMeasured(double distanceMeters) async {
    try {
      // 카메라 화면에서 이미 완료 안내를 했으므로 바로 걸음 수 인식 시작
      _startStepCountListening(distanceMeters);
    } catch (e) {
      debugPrint('❌ 거리 측정 안내 실패: $e');
      _fallbackToNextStep(); // 오류 시 기본 진행
    }
  }

  // 걸음 수 음성 인식 시작 (거리 정보 포함)
  void _startStepCountListening(double distanceMeters) {
    debugPrint("🎙️ 걸음 수 음성 인식 시작 - 거리: ${distanceMeters.toStringAsFixed(1)}m");

    if (_voiceService == null) {
      _fallbackToNextStep();
      return;
    }

    if (mounted) {
      setState(() {
        _isListening = true;
      });
    }

    // 거리 정보를 저장하여 나중에 보폭 계산에 사용
    _currentDistanceMeters = distanceMeters;

    // VoiceRecognitionHelper로 걸음 수 인식 (로딩 에러 방지)
    if (_voiceHelper != null) {
      _voiceHelper!.startListeningForNumber(
        onNumberFound: (int stepCount, String fullText) {
          debugPrint('🎤 걸음 수 인식됨: $stepCount (전체: $fullText)');
          if (mounted) {
            setState(() => _isListening = false);
          }
          if (_currentDistanceMeters != null) {
            _confirmStepCount(stepCount, _currentDistanceMeters!);
          }
        },
        minValue: 1,
        maxValue: 50,
        timeoutSeconds: 30,
        onTimeout: () {
          debugPrint("⏰ 걸음 수 입력 타임아웃");
          if (mounted) {
            setState(() => _isListening = false);
            _voiceService?.speak("시간 초과. 다시 시도해주세요.");
            _fallbackToNextStep();
          }
        },
        onInvalidInput: () {
          debugPrint("❌ 잘못된 걸음 수 입력");
          if (mounted) {
            _voiceService?.speak("1부터 50 사이 숫자로 다시 말씀해주세요.");
          }
        },
      );
    } else {
      debugPrint("❌ VoiceRecognitionHelper가 초기화되지 않음 - 기본 진행");
      _fallbackToNextStep();
    }
  }

  // 걸음 수 확인 (거리 정보 포함)
  void _confirmStepCount(int stepCount, double distanceMeters) async {
    if (mounted) {
      setState(() {
        _isListening = false;
      });
    }

    try {
      await VoiceUtils.speakWithService(_voiceService, "$stepCount 걸음이 맞나요?");

      await Future.delayed(const Duration(milliseconds: 500));

      // VoiceRecognitionHelper로 확인 응답 인식 (로딩 에러 방지)
      _startConfirmationListeningWithHelper(stepCount, distanceMeters);
    } catch (e) {
      debugPrint('❌ 걸음 수 확인 오류: $e');
      _saveStepCountAndProceed(stepCount, distanceMeters);
    }
  }

  // VoiceRecognitionHelper를 사용한 확인 응답 인식 (로딩 에러 방지)
  void _startConfirmationListeningWithHelper(
    int stepCount,
    double distanceMeters,
  ) {
    if (_voiceHelper == null) {
      debugPrint("❌ VoiceRecognitionHelper가 초기화되지 않음 - 자동 저장");
      _saveStepCountAndProceed(stepCount, distanceMeters);
      return;
    }

    if (mounted) {
      setState(() {
        _isListening = true;
        _isConfirming = true;
      });
    }

    _voiceHelper!.startListeningForConfirmation(
      onConfirm: (bool confirmed, String fullText) {
        debugPrint('🎤 확인 응답: $confirmed (전체: $fullText)');
        if (mounted) {
          setState(() {
            _isListening = false;
            _isConfirming = false;
          });
        }

        if (confirmed) {
          _saveStepCountAndProceed(stepCount, distanceMeters);
        } else {
          _voiceService?.speak("다시 말씀해주세요.");
          Future.delayed(const Duration(milliseconds: 300), () {
            _startStepCountListening(distanceMeters);
          });
        }
      },
      timeoutSeconds: 15,
      onTimeout: () {
        debugPrint("⏰ 확인 응답 타임아웃");
        if (mounted) {
          setState(() {
            _isListening = false;
            _isConfirming = false;
          });
          _voiceService?.speak("자동으로 완료합니다.");
          _saveStepCountAndProceed(stepCount, distanceMeters);
        }
      },
    );
  }

  // 확인 응답 음성 인식 시작 (거리 정보 포함)
  void _startConfirmationListening(int stepCount, double distanceMeters) {
    if (_voiceService == null) {
      _saveStepCountAndProceed(stepCount, distanceMeters);
      return;
    }

    if (mounted) {
      setState(() {
        _isListening = true;
        _isConfirming = true;
      });
    }

    // 확인 응답을 위한 콜백 설정 (일반 음성 인식 사용)
    _voiceService!.addListener(
      () => _onConfirmationUpdate(stepCount, distanceMeters),
    );

    // 자동 인식 사이클 시작
    _voiceService!.startAutoRecognitionCycle();

    // 15초 후 타임아웃
    Future.delayed(const Duration(seconds: 15), () {
      if (mounted && _isListening && _isConfirming) {
        _voiceService?.removeListener(
          () => _onConfirmationUpdate(stepCount, distanceMeters),
        );
        _voiceService?.stopAutoRecognitionCycle();
        if (mounted) {
          setState(() {
            _isListening = false;
            _isConfirming = false;
          });
        }
        _voiceService?.speak("시간 초과, 자동으로 저장하겠습니다.");
        _saveStepCountAndProceed(stepCount, distanceMeters);
      }
    });
  }

  // 확인 응답 처리 (거리 정보 포함)
  void _onConfirmationUpdate(int stepCount, double distanceMeters) {
    if (_voiceService == null || !_isListening) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isEmpty) return;

    final input = recognizedText.toLowerCase().trim();
    debugPrint('🎤 확인 응답: $input');

    _voiceService!.removeListener(
      () => _onConfirmationUpdate(stepCount, distanceMeters),
    );
    _voiceService!.stopAutoRecognitionCycle();

    if (mounted) {
      setState(() {
        _isListening = false;
        _isConfirming = false;
      });
    }

    if (input.contains('네') ||
        input.contains('예') ||
        input.contains('맞') ||
        input.contains('확인') ||
        input.contains('좋') ||
        input.contains('그래')) {
      _saveStepCountAndProceed(stepCount, distanceMeters);
    } else if (input.contains('아니') ||
        input.contains('다시') ||
        input.contains('틀렸') ||
        input.contains('아니오') ||
        input.contains('안')) {
      VoiceUtils.speakWithService(_voiceService, "걸음 수를 다시 말씀해 주세요.");
      Future.delayed(const Duration(milliseconds: 500), () {
        _startStepCountListening(distanceMeters);
      });
    } else {
      // 애매한 경우 재확인
      VoiceUtils.speakWithService(_voiceService, "네 또는 아니오로 답변해 주세요.");
      Future.delayed(const Duration(milliseconds: 500), () {
        _startConfirmationListening(stepCount, distanceMeters);
      });
    }
  }

  // 걸음 수 저장하고 다음 단계 진행 (거리 정보 포함)
  void _saveStepCountAndProceed(int stepCount, double distanceMeters) async {
    // VoiceService의 걸음 수 입력 모드 종료
    if (_voiceService != null) {
      _voiceService!.stopAutoRecognitionCycle();
    }

    try {
      debugPrint(
        "💾 걸음 수 저장: $stepCount걸음, 거리: ${distanceMeters.toStringAsFixed(1)}m",
      );

      // 거리와 걸음 수로 보폭 계산
      final calculatedStepLength = (distanceMeters * 100) / stepCount; // cm 단위

      debugPrint("📏 계산된 보폭: ${calculatedStepLength.toStringAsFixed(1)}cm");

      // 기존 측정값을 계산된 값으로 업데이트
      if (mounted) {
        setState(() {
          step_length_cm = calculatedStepLength;
          _resultConfirmed = false; // 확인 플로우를 위해 false로 설정
          _isConfirming = true; // 확인 단계 시작
        });
      }

      // 최종 확인 요청
      await VoiceUtils.speakWithService(
        _voiceService,
        "보폭이 ${calculatedStepLength.toStringAsFixed(0)}센티미터로 계산되었습니다.",
      );

      await Future.delayed(const Duration(milliseconds: 800));

      if (widget.fromSettings) {
        _saveAndPop();
      } else {
        _goNext();
      }
    } catch (e) {
      debugPrint('❌ 걸음 수 저장 오류: $e');
      _fallbackToNextStep();
    }
  }

  // 오류 시 기본 진행
  void _fallbackToNextStep() {
    if (mounted) {
      setState(() {
        _isListening = false;
        _resultConfirmed = true;
      });
    }

    if (widget.fromSettings) {
      _saveAndPop();
    } else {
      _goNext();
    }
  }

  // 온보딩 플로우: 다음 단계(VoiceScreen)로
  void _goNext() async {
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('다음 단계로 진행합니다.');

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
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('완료합니다.');

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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: AccessibleText('변경사항이 저장되지 않았습니다.')),
      );
    }
    // 음성 인식/리스너 선해제 후 Pop (레이스 방지)
    try {
      _voiceHelper?.stopListening();
      _voiceService?.stopAutoRecognitionCycle();
      _voiceService?.removeListener(_onVoiceServiceUpdate);
    } catch (_) {}
    if (!mounted) return;
    Navigator.pop(context); // 결과 없이 Pop → 저장 안 됨
  }

  @override
  void dispose() {
    // 음성 인식 사이클 중단 및 리소스 정리
    _voiceHelper?.dispose();
    if (_voiceService != null) {
      _voiceService!.stopAutoRecognitionCycle();
      _voiceService!.removeListener(_onVoiceServiceUpdate);
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
                    if (mounted) {
                      setState(() {
                        _resultConfirmed = true;
                      });
                    }
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
                              ? (_measured
                                  ? (_resultConfirmed
                                      ? '보폭이 설정되었습니다. 변경이 필요하면 다시 측정해 저장할 수 있습니다.'
                                      : '측정이 완료되었습니다. 결과를 확인하거나 다시 측정할 수 있습니다.')
                                  : '보폭을 다시 측정해 저장할 수 있습니다.')
                              : (_measured
                                  ? (_resultConfirmed
                                      ? '보폭이 설정되었습니다. 다음 단계로 진행해주세요.'
                                      : '거리 측정이 완료되었습니다. 걸음 수를 입력하고 결과를 확인해주세요.')
                                  : 'A아이 앱에 오신 것을 환영합니다. 먼저 보폭측정을 시작해주세요.'),
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
                            child: const AccessibleText(
                              '보폭 측정 시작',
                              enableVoiceOutput:
                                  false, // 버튼 내 텍스트는 버튼 onPressed 유지
                            ),
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
                            if (_isListening) ...[
                              Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Icon(
                                    Icons.mic,
                                    color: Colors.red.shade300,
                                    size: 16,
                                  ),
                                  const SizedBox(width: 8),
                                  AccessibleDescription(
                                    '걸음 수를 말씀해 주세요...',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                      color: Colors.red.shade300,
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ] else ...[
                              AccessibleDescription(
                                '측정이 완료되었습니다. 걸음 수를 말씀해 주세요.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Colors.green.shade300,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
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

  /// 음성인식 토글 함수 - 자동 인식 사이클 제어
  void _toggleVoiceRecognition() async {
    if (_voiceService == null) return;

    if (mounted) {
      setState(() {
        _isListening = !_isListening;
      });
    }

    if (_isListening) {
      // 효과음으로 시작 알림
      SystemSound.play(SystemSoundType.click);
      // 자동 인식 사이클 시작
      try {
        await _voiceService!.startAutoRecognitionCycle();
        _voiceService!.addListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ 자동 인식 시작 실패: $e');
        if (mounted) {
          setState(() => _isListening = false);
        }
      }
    } else {
      SystemSound.play(SystemSoundType.alert);
      // 자동 인식 사이클 중지
      try {
        _voiceService!.stopAutoRecognitionCycle();
        _voiceService!.removeListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ 자동 인식 중지 실패: $e');
      }
    }
  }

  /// VoiceService 상태 변경 리스너
  void _onVoiceServiceUpdate() {
    if (_voiceService == null) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty && _isListening) {
      debugPrint('🎤 보폭 화면에서 인식된 텍스트: $recognizedText');

      if (mounted) {
        setState(() => _isListening = false);
      }
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리 - 보폭 측정 → 확인 → 자동 전환
  void _processVoiceCommand(String command) async {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 보폭 화면 음성 명령 처리: $lowerCommand');

    // 확인 단계인 경우 (측정 완료 후)
    if (_isConfirming && _measured) {
      if (VoiceRecognitionHelper.isConfirmationCommand(command)) {
        // 확인됨 - 서버에 전송 후 자동으로 다음 단계로 전환
        setState(() {
          _resultConfirmed = true;
          _isConfirming = false;
        });

        // 서버에 최종 보폭 전송
        if (step_length_cm != null) {
          await _sendStepLengthResult(step_length_cm!);
        }

        await Future.delayed(const Duration(seconds: 1));
        if (widget.fromSettings) {
          _saveAndPop();
        } else {
          _goNext();
        }
        return;
      } else if (VoiceRecognitionHelper.isRejectionCommand(command) ||
          VoiceRecognitionHelper.isRetryCommand(command)) {
        // 다시 측정
        setState(() {
          _isConfirming = false;
          _measured = false;
          _resultConfirmed = false;
          step_length_cm = null;
        });
        await _speakText('보폭을 다시 측정합니다.');
        _startMeasure();
        return;
      }
    }

    if (VoiceRecognitionHelper.isStartCommand(command)) {
      if (!_measured) {
        _speakText('보폭 측정을 시작합니다.');
        _startMeasure();
      } else {
        _speakText('이미 측정이 완료되었습니다.');
      }
    } else if (VoiceRecognitionHelper.isRetryCommand(command)) {
      _speakText('보폭을 다시 측정합니다.');
      _startMeasure();
    } else if (VoiceRecognitionHelper.isCompletionCommand(command)) {
      if (_measured && _resultConfirmed) {
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
    } else if (VoiceRecognitionHelper.isBackCommand(command)) {
      _speakText('이전 화면으로 돌아갑니다.');
      if (widget.fromSettings) {
        _backWithoutSave();
      } else {
        Navigator.pop(context);
      }
    } else {
      final statusText = _measured ? '보폭이 측정되었습니다.' : '보폭 측정 화면입니다.';
      _speakText(statusText);
    }
  }

  /// 음성 출력 함수
  Future<void> _speakText(String text) async {
    await VoiceUtils.speakWithService(
      _voiceService,
      text,
      speed: _voiceService?.getCurrentSpeed() ?? 1.0,
    );
  }

  /// 보폭 결과를 서버에 전송 (통합 API 사용)
  Future<void> _sendStepLengthResult(double stepLengthCm) async {
    try {
      final ok = await ApiService().saveStepLength(stepLengthCm);
      if (ok) {
        debugPrint('✅ 보폭 측정 결과 전송 성공');
      } else {
        debugPrint('❌ 보폭 결과 전송 실패');
      }
    } catch (e) {
      debugPrint('❌ 보폭 결과 전송 오류: $e');
    }
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
