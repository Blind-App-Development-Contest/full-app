import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
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

    final result = await Navigator.push<double>(
      context,
      MaterialPageRoute(
        builder: (context) => const CameraMeasurementScreen(),
      ),
    );

    debugPrint("🔙 CameraMeasurementScreen에서 돌아옴, 결과: $result");

    if (result != null) {
      // CameraMeasurementScreen에서 거리(미터)를 받음
      final measuredDistanceMeters = result;
      debugPrint("📏 카메라에서 측정된 거리: ${measuredDistanceMeters.toStringAsFixed(1)}m");
      
      setState(() {
        _measured = true;
        _resultConfirmed = false; // 재측정 시 결과 확인 리셋
      });

      // 거리 측정 완료 후 걸음 수 입력 안내
      _announceDistanceMeasured(measuredDistanceMeters);
    }
  }

  // 거리 측정 완료 후 걸음 수 입력 안내
  Future<void> _announceDistanceMeasured(double distanceMeters) async {
    if (_voiceService == null) return;

    try {
      // 거리 측정 완료 안내
      await _voiceService!.speak("거리 측정이 완료되었습니다!");

      await Future.delayed(const Duration(milliseconds: 500));
      await _voiceService!.speak("측정된 거리는 ${distanceMeters.toStringAsFixed(1)}미터입니다.");

      await Future.delayed(const Duration(milliseconds: 500));
      
      // 걸음 수 입력 요청
      await _voiceService!.speak("이제 ${distanceMeters.toStringAsFixed(0)}미터를 걸으며 세신 걸음 수를 말씀해 주세요.");
      await Future.delayed(const Duration(milliseconds: 300));
      await _voiceService!.speak("걸음 수를 말씀해 주세요.");
      
      // 걸음 수 음성 인식 시작
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

    setState(() {
      _isListening = true;
    });

    // 거리 정보를 저장하여 나중에 보폭 계산에 사용
    _currentDistanceMeters = distanceMeters;

    // 자동 음성 인식 사이클 시작 (걸음 수 입력 대기)
    _voiceService!.addListener(_onStepCountVoiceUpdate);
    _voiceService!.startAutoRecognitionCycle();
  }

  /// 걸음 수 입력 음성 인식 리스너
  void _onStepCountVoiceUpdate() {
    if (_voiceService == null || !_isListening) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isEmpty) return;

    debugPrint('🎤 걸음 수 입력 인식: $recognizedText');
    
    // 걸음 수 추출 로직 (VoiceService에서 이동)
    final stepCount = _extractStepCountFromSpeech(recognizedText);

    if (stepCount > 0 && stepCount <= 50 && _currentDistanceMeters != null) {
      _voiceService!.removeListener(_onStepCountVoiceUpdate);
      _voiceService!.stopAutoRecognitionCycle();
      setState(() => _isListening = false);
      _confirmStepCount(stepCount, _currentDistanceMeters!);
    } else {
      // 잘못된 입력 시 재시도 (음성 인식은 계속)
      _voiceService?.speak("죄송합니다. 다시 걸음 수를 말씀해 주세요. 1부터 50 사이의 숫자로 말씀해 주세요.");
    }
  }

  // 걸음 수 확인 (거리 정보 포함)
  void _confirmStepCount(int stepCount, double distanceMeters) async {
    setState(() {
      _isListening = false;
    });

    try {
      await _voiceService?.speak("$stepCount 걸음으로 입력하셨습니다. 맞으면 '네', 틀리면 '아니오'라고 말씀해 주세요.");
      
      await Future.delayed(const Duration(milliseconds: 500));
      
      // 확인 응답을 위한 음성 인식 시작 (거리 정보 포함)
      _startConfirmationListening(stepCount, distanceMeters);
      
    } catch (e) {
      debugPrint('❌ 걸음 수 확인 오류: $e');
      _saveStepCountAndProceed(stepCount, distanceMeters);
    }
  }

  // 확인 응답 음성 인식 시작 (거리 정보 포함)
  void _startConfirmationListening(int stepCount, double distanceMeters) {
    if (_voiceService == null) {
      _saveStepCountAndProceed(stepCount, distanceMeters);
      return;
    }

    setState(() {
      _isListening = true;
      _isConfirming = true;
    });

    // 확인 응답을 위한 콜백 설정 (일반 음성 인식 사용)
    _voiceService!.addListener(() => _onConfirmationUpdate(stepCount, distanceMeters));
    
    // 자동 인식 사이클 시작
    _voiceService!.startAutoRecognitionCycle();
    
    // 15초 후 타임아웃
    Future.delayed(const Duration(seconds: 15), () {
      if (mounted && _isListening && _isConfirming) {
        _voiceService?.removeListener(() => _onConfirmationUpdate(stepCount, distanceMeters));
        _voiceService?.stopAutoRecognitionCycle();
        setState(() {
          _isListening = false;
          _isConfirming = false;
        });
        _voiceService?.speak("시간이 초과되었습니다. 자동으로 저장하겠습니다.");
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
    
    _voiceService!.removeListener(() => _onConfirmationUpdate(stepCount, distanceMeters));
    _voiceService!.stopAutoRecognitionCycle();
    
    setState(() {
      _isListening = false;
      _isConfirming = false;
    });

    if (input.contains('네') || input.contains('예') || input.contains('맞') || 
        input.contains('확인') || input.contains('좋') || input.contains('그래')) {
      _saveStepCountAndProceed(stepCount, distanceMeters);
    } else if (input.contains('아니') || input.contains('다시') || 
               input.contains('틀렸') || input.contains('아니오') || input.contains('안')) {
      _voiceService?.speak("다시 걸음 수를 말씀해 주세요.");
      Future.delayed(const Duration(milliseconds: 500), () {
        _startStepCountListening(distanceMeters);
      });
    } else {
      // 애매한 경우 재확인
      _voiceService?.speak("네 또는 아니오로 답변해 주세요.");
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
      await _voiceService?.speak("$stepCount 걸음으로 저장했습니다.");
      
      debugPrint("💾 걸음 수 저장: $stepCount걸음, 거리: ${distanceMeters.toStringAsFixed(1)}m");
      
      // 거리와 걸음 수로 보폭 계산
      await _voiceService?.speak("보폭을 계산하고 있습니다.");
      final calculatedStepLength = (distanceMeters * 100) / stepCount; // cm 단위
      
      debugPrint("📏 계산된 보폭: ${calculatedStepLength.toStringAsFixed(1)}cm");
      
      // 기존 측정값을 계산된 값으로 업데이트
      setState(() {
        step_length_cm = calculatedStepLength;
        _resultConfirmed = true;
      });
      
      // 서버에 최종 보폭 전송
      await _sendStepLengthResult(calculatedStepLength);
      
      await _voiceService?.speak("보폭 계산이 완료되었습니다. ${calculatedStepLength.toStringAsFixed(1)}센티미터입니다.");
      
      await Future.delayed(const Duration(milliseconds: 500));

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
    setState(() {
      _isListening = false;
      _resultConfirmed = true;
    });

    if (widget.fromSettings) {
      _saveAndPop();
    } else {
      _goNext();
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
    // 음성 인식 사이클 중단 및 리소스 정리
    if (_voiceService != null) {
      _voiceService!.stopAutoRecognitionCycle();
      _voiceService!.removeListener(_onVoiceServiceUpdate);
      _voiceService!.removeListener(_onStepCountVoiceUpdate);
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

    setState(() {
      _isListening = !_isListening;
    });

    if (_isListening) {
      _speakText('음성인식을 시작합니다. 측정시작이라고 말씀해주세요.');
      // 자동 인식 사이클 시작
      try {
        await _voiceService!.startAutoRecognitionCycle();
        _voiceService!.addListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ 자동 인식 시작 실패: $e');
        setState(() => _isListening = false);
      }
    } else {
      _speakText('음성인식을 중지합니다.');
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


  /// 음성에서 걸음 수 추출 (VoiceService에서 이동)
  int _extractStepCountFromSpeech(String speech) {
    final cleanText = speech.toLowerCase().trim();
    debugPrint('🔍 걸음 수 추출 시도: "$cleanText"');
    
    // 확장된 한국어 숫자 매핑
    final koreanNumbers = {
      '영': 0, '공': 0, '하나': 1, '일': 1, '한': 1, '둘': 2, '이': 2,
      '셋': 3, '삼': 3, '넷': 4, '사': 4, '다섯': 5, '오': 5,
      '여섯': 6, '육': 6, '일곱': 7, '칠': 7, '여덟': 8, '팔': 8,
      '아홉': 9, '구': 9, '열': 10, '십': 10, '스무': 20, '이십': 20,
      '서른': 30, '삼십': 30, '마흔': 40, '사십': 40, '쉰': 50, '오십': 50
    };
    
    // 복합 숫자 매핑 (자주 사용되는 것들)
    final compositeNumbers = {
      '열하나': 11, '열한': 11, '열둘': 12, '열두': 12, '열셋': 13, '열세': 13,
      '열넷': 14, '열네': 14, '열다섯': 15, '열여섯': 16, '열일곱': 17,
      '열여덟': 18, '열아홉': 19, '스물하나': 21, '스물한': 21, '스물둘': 22,
      '스물두': 22, '스물셋': 23, '스물세': 23, '스물넷': 24, '스물네': 24,
      '스물다섯': 25
    };
    
    // 1. 직접적인 숫자 패턴 찾기 (15걸음, 20보 등)
    final patterns = [
      RegExp(r'(\d+)\s*(?:걸음|보|발자국|스텝|개|번|회)'),
      RegExp(r'(\d+)\s*(?:번|개)?'),
      RegExp(r'(?:걸음|보|발자국|스텝).*?(\d+)'),
    ];
    
    for (final pattern in patterns) {
      final match = pattern.firstMatch(cleanText);
      if (match != null) {
        final num = int.tryParse(match.group(1)!);
        if (num != null && num > 0 && num <= 100) {
          debugPrint('✅ 패턴 매칭으로 걸음 수 추출: $num');
          return num;
        }
      }
    }
    
    // 2. 복합 한국어 숫자 변환 시도 (우선순위 높음)
    for (final entry in compositeNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        debugPrint('✅ 복합 한국어 숫자 변환으로 걸음 수 추출: ${entry.value}');
        return entry.value;
      }
    }
    
    // 3. 기본 한국어 숫자 변환 시도
    if (cleanText.contains('열') && cleanText.length > 1) {
      // 열 + 숫자 조합 처리
      final afterTen = cleanText.replaceFirst('열', '').trim();
      final baseNum = koreanNumbers[afterTen];
      if (baseNum != null && baseNum < 10) {
        debugPrint('✅ 열+숫자 조합으로 걸음 수 추출: ${10 + baseNum}');
        return 10 + baseNum;
      }
      debugPrint('✅ 열로 걸음 수 추출: 10');
      return 10;
    }
    
    for (final entry in koreanNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        debugPrint('✅ 기본 한국어 숫자 변환으로 걸음 수 추출: ${entry.value}');
        return entry.value;
      }
    }
    
    // 4. 전체 텍스트에서 숫자만 추출
    final digitOnly = RegExp(r'\d+').allMatches(cleanText);
    for (final match in digitOnly) {
      final num = int.tryParse(match.group(0)!);
      if (num != null && num > 0 && num <= 100) {
        debugPrint('✅ 숫자 추출로 걸음 수 획득: $num');
        return num;
      }
    }
    
    debugPrint('❌ 걸음 수 추출 실패: "$cleanText"');
    return 0;
  }

  /// 보폭 결과를 서버에 전송
  Future<void> _sendStepLengthResult(double stepLengthCm) async {
    try {
      final baseUrl = _voiceService?.baseUrl ?? 'https://aeye-backend-app-jp.azurewebsites.net';
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/users/step-length'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'user_id': 'current_user',
              'step_length': stepLengthCm,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        debugPrint('✅ 보폭 측정 결과 전송 성공');
      } else {
        debugPrint('❌ 보폭 결과 전송 실패: ${response.statusCode}');
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
