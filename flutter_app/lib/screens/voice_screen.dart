import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
import '../widgets/accessible_text.dart';
import '../services/api_service.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';
import '../utils/voice_recognition_helper.dart';
import 'guardian_screen.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({
    super.key,
    this.fromSettings = false, // ✅ 설정 화면에서 진입 여부
    this.initialGender = 'F', // 'F' or 'M'
    this.initialSpeed = 1.0, // UI 범위: 0.5 ~ 2.0
  });

  final bool fromSettings;
  final String initialGender;
  final double initialSpeed;

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  late String _gender; // 'F' or 'M'
  late double _speed; // 0.5 ~ 2.0

  // 음성인식 상태 관리
  bool _isListening = false;
  VoiceService? _voiceService;

  @override
  void initState() {
    super.initState();
    _gender = widget.initialGender;
    _speed = widget.initialSpeed;

    // VoiceService에 초기 속도와 성별 설정
    WidgetsBinding.instance.addPostFrameCallback((_) {
      try {
        _voiceService = context.read<VoiceService>();
        _voiceService!.setVoiceSpeed(_speed);
        _voiceService!.setVoiceGender(_gender == 'F' ? 'female' : 'male');
        debugPrint(
          '🎙️ VoiceScreen 초기화: 음성 속도 ${_speed}x, 성별 ${_gender == 'F' ? '여성' : '남성'} 설정',
        );

        // 초기 음성 안내 시작
        _startInitialVoiceGuidance();
      } catch (e) {
        debugPrint('❌ VoiceScreen 초기화: VoiceService 설정 실패: $e');
      }
    });
  }

  @override
  void dispose() {
    // VoiceService 자동 인식 중지
    try {
      _voiceService?.stopAutoRecognitionCycle();
      debugPrint('✅ VoiceScreen: 자동 인식 사이클 중지 완료');
    } catch (e) {
      debugPrint('❌ VoiceScreen: 자동 인식 중지 실패: $e');
    }

    // 리스너 해제
    try {
      _voiceService?.removeListener(_onVoiceServiceUpdate);
      debugPrint('✅ VoiceScreen: VoiceService 리스너 해제 완료');
    } catch (e) {
      debugPrint('❌ VoiceScreen: 리스너 해제 실패: $e');
    }

    // 음성 인식 상태 초기화
    if (_isListening) {
      try {
        _voiceService?.stopListeningAndProcess();
        debugPrint('✅ VoiceScreen: 진행 중인 음성 인식 중지 완료');
      } catch (e) {
        debugPrint('❌ VoiceScreen: 음성 인식 중지 실패: $e');
      }
    }
    super.dispose();
  }

  bool get _hasChanged {
    final g = _gender != widget.initialGender;
    final s =
        double.parse(_speed.toStringAsFixed(2)) !=
        double.parse(widget.initialSpeed.toStringAsFixed(2));
    return g || s;
  }

  // 온보딩 플로우: 다음 단계(GuardianScreen) 이동
  void _goNext() async {
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('다음 단계로 진행합니다.');

    // 선해제: 음성 인식/리스너 정리 후 화면 전환
    try {
      _voiceService?.stopAutoRecognitionCycle();
    } catch (_) {}

    // 음성 설정 저장 (온보딩 플로우)
    try {
      debugPrint(
        '🎙️ 온보딩 음성 설정 저장 시도: ${_gender == 'F' ? 'female' : 'male'}, ${_speed}x',
      );
      await ApiService().saveVoiceSettings({
        'gender': _gender == 'F' ? 'female' : 'male',
        'speed': _speed,
      });
      debugPrint('✅ 온보딩 음성 설정 저장 성공');
    } catch (e) {
      debugPrint('❌ 온보딩 음성 설정 저장 실패: $e');
      // 저장 실패해도 계속 진행 (오프라인 모드 고려)
    }

    if (mounted) {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const GuardianScreen()),
      );
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '설정 저장: ${_gender == 'F' ? '여성' : '남성'}, ${_speed.toStringAsFixed(1)}x',
          ),
        ),
      );
    }
  }

  // 설정에서 진입: 값 저장 후 되돌아가기
  void _saveAndPop() async {
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('완료합니다.');

    if (_hasChanged) {
      // 음성 설정 저장 (설정 화면에서 진입)
      try {
        debugPrint(
          '🎙️ 설정 음성 변경 저장 시도: ${_gender == 'F' ? 'female' : 'male'}, ${_speed}x',
        );
        await ApiService().saveVoiceSettings({
          'gender': _gender == 'F' ? 'female' : 'male',
          'speed': _speed,
        });
        debugPrint('✅ 설정 음성 변경 저장 성공');
      } catch (e) {
        debugPrint('❌ 설정 음성 변경 저장 실패: $e');
        // 저장 실패해도 계속 진행 (오프라인 모드 고려)
      }
    }

    if (mounted) {
      // 선해제 후 Pop
      try {
        _voiceService?.stopAutoRecognitionCycle();
      } catch (_) {}
      Navigator.pop<Map<String, dynamic>>(context, {
        'gender': _gender,
        'speed': _speed,
      });
    }
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  void _backWithoutSave() {
    // 클릭 음성 피드백
    _speakText('뒤로가기');

    if (_hasChanged) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('변경사항이 저장되지 않았습니다.')));
    }
    // 선해제 후 Pop
    try {
      _voiceService?.stopAutoRecognitionCycle();
    } catch (_) {}
    if (!mounted) return;
    Navigator.pop(context); // 결과 없이 Pop → 저장 안 됨
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const inner = Color(0xFF151C2C);
    const divider = Color(0xFF22304A);
    const hint = Color(0xFF9AA3B2);

    // ✅ 설정에서 들어온 경우 변경 여부 판단 (소수 비교 안전하게 반올림)
    bool hasChanged() {
      final genderChanged = _gender != widget.initialGender;
      final speedChanged =
          (double.parse(_speed.toStringAsFixed(2)) !=
              double.parse(widget.initialSpeed.toStringAsFixed(2)));
      return genderChanged || speedChanged;
    }

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
                  '음성 설정',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              )
              : null,

      // ✅ 하단 버튼: 설정 경로면 SetButton, 온보딩 경로면 NextButton
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child:
            widget.fromSettings
                ? SetButton(
                  label: '완료',
                  hasChanged: hasChanged(),
                  onPressed: hasChanged() ? _saveAndPop : null,
                )
                : NextButton(label: '다음 단계', enabled: true, onPressed: _goNext),
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
                  subtitle: widget.fromSettings ? '음성 설정' : '2단계: 음성 설정',
                ),

                // ── 음성 설정 카드
                Container(
                  padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
                  decoration: BoxDecoration(
                    color: panel,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: divider.withValues(alpha: 0.25)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: const [
                          Icon(
                            Icons.volume_up_outlined,
                            color: Colors.white,
                            size: 20,
                          ),
                          SizedBox(width: 8),
                          AccessibleTitle(
                            '음성 설정',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 18),

                      const AccessibleTitle(
                        '음성 종류',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 12),

                      Row(
                        children: [
                          Expanded(
                            child: _ChoiceButton(
                              label: '여성 음성',
                              selected: _gender == 'F',
                              onTap: () {
                                setState(() => _gender = 'F');
                                // VoiceService에 성별 변경 알리기
                                try {
                                  _voiceService?.setVoiceGender('female');
                                } catch (e) {
                                  debugPrint('❌ 음성 성별 변경 실패: $e');
                                }
                                _speakText('여성 음성');
                              },
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            child: _ChoiceButton(
                              label: '남성 음성',
                              selected: _gender == 'M',
                              onTap: () {
                                setState(() => _gender = 'M');
                                // VoiceService에 성별 변경 알리기
                                try {
                                  _voiceService?.setVoiceGender('male');
                                } catch (e) {
                                  debugPrint('❌ 음성 성별 변경 실패: $e');
                                }
                                _speakText('남성 음성');
                              },
                            ),
                          ),
                        ],
                      ),

                      const SizedBox(height: 22),
                      AccessibleTitle(
                        '음성 속도: ${_speed.toStringAsFixed(1)}배속',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),

                      // 슬라이더 영역 배경
                      Container(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
                        decoration: BoxDecoration(
                          color: inner,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: divider.withValues(alpha: 0.45),
                          ),
                        ),
                        child: Column(
                          children: [
                            Slider(
                              value: _speed,
                              onChanged: (v) {
                                setState(() => _speed = v);
                                // VoiceService에 속도 변경 알리고 음성 출력
                                try {
                                  _voiceService?.setVoiceSpeed(v);
                                  // 새 값으로 음성 출력 (이전 음성 중단)                                                                                                                      │
                                  _speakText('속도 ${v.toStringAsFixed(1)}배');
                                } catch (e) {
                                  debugPrint('❌ 음성 속도/출력 변경 실패: $e');
                                }
                              },
                              min: 0.5,
                              max: 2.0,
                              divisions: 10,
                              label: '${_speed.toStringAsFixed(1)}x',
                            ),
                            Padding(
                              padding: const EdgeInsets.only(
                                top: 2,
                                left: 2,
                                right: 2,
                                bottom: 4,
                              ),
                              child: Row(
                                mainAxisAlignment:
                                    MainAxisAlignment.spaceBetween,
                                children: [
                                  AccessibleText(
                                    '느림 (0.5x)',
                                    style: TextStyle(
                                      color: hint,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  AccessibleText(
                                    '빠름 (2.0x)',
                                    style: TextStyle(
                                      color: hint,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 120),
              ],
            ),
          ),
        ),
      ),
      floatingActionButton: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          FloatingActionButton(
            onPressed: _toggleVoiceRecognition,
            backgroundColor: _isListening ? Colors.red : Colors.blue,
            elevation: 0,
            heroTag: 'mic_button', // Hero 태그 추가
            child: Icon(
              _isListening ? Icons.mic : Icons.mic_none,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 16),
          // 다시 듣기 버튼 추가
          FloatingActionButton(
            onPressed: () {
              _voiceService?.playLastRecording();
            },
            backgroundColor: Colors.amber,
            heroTag: 'playback_button', // Hero 태그 추가
            child: const Icon(Icons.replay, color: Colors.white),
          ),
        ],
      ),
    );
  }

  /// 음성인식 토글 함수
  void _toggleVoiceRecognition() async {
    if (_voiceService == null) return;

    setState(() {
      _isListening = !_isListening;
    });

    if (_isListening) {
      SystemSound.play(SystemSoundType.click);
      // STT 시작
      try {
        await _voiceService!.startListening();
        _voiceService!.addListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ STT 시작 실패: $e');
        setState(() => _isListening = false);
      }
    } else {
      SystemSound.play(SystemSoundType.alert);
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
      debugPrint('🎤 음성 설정 화면에서 인식된 텍스트: $recognizedText');

      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리
  void _processVoiceCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 음성 설정 화면 음성 명령 처리: $lowerCommand');

    if (lowerCommand.contains('여성') || lowerCommand.contains('여자')) {
      setState(() => _gender = 'F');
      _voiceService?.setVoiceGender('female');
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('여성 음성으로 설정');
    } else if (lowerCommand.contains('남성') || lowerCommand.contains('남자')) {
      setState(() => _gender = 'M');
      _voiceService?.setVoiceGender('male');
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('남성 음성으로 설정');
    } else if (lowerCommand.contains('빠르게') || lowerCommand.contains('빨리')) {
      setState(() => _speed = (_speed + 0.2).clamp(0.5, 2.0));
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('음성 속도 ${_speed.toStringAsFixed(1)}배');
    } else if (lowerCommand.contains('느리게') || lowerCommand.contains('천천히')) {
      setState(() => _speed = (_speed - 0.2).clamp(0.5, 2.0));
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('음성 속도 ${_speed.toStringAsFixed(1)}배');
    } else if (VoiceRecognitionHelper.isCompletionCommand(command)) {
      if (widget.fromSettings) {
        _saveAndPop();
      } else {
        _goNext();
      }
    } else if (VoiceRecognitionHelper.isBackCommand(command)) {
      _speakText('이전 화면으로 돌아갑니다.');
      if (widget.fromSettings) {
        _backWithoutSave();
      } else {
        Navigator.pop(context);
      }
    } else {
      _speakText(
        '현재 설정은 ${_gender == 'F' ? '여성' : '남성'} 음성, ${_speed.toStringAsFixed(1)}배속입니다.',
      );
    }
  }

  /// 초기 음성 안내 시작
  void _startInitialVoiceGuidance() async {
    if (_voiceService == null) return;

    await Future.delayed(const Duration(milliseconds: 500));

    if (widget.fromSettings) {
      _speakText('음성 설정 화면입니다.');
    }
  }

  /// 음성 출력 함수
  Future<void> _speakText(String text) async {
    await VoiceUtils.speakWithService(
      _voiceService,
      text,
      speed: _voiceService?.getCurrentSpeed() ?? widget.initialSpeed,
    );
  }
}

/// 선택 토글 버튼 (선택=흰 배경/검 텍스트, 비선택=짙은 배경/흰 텍스트)
class _ChoiceButton extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _ChoiceButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final Color selectedBg = Colors.white;
    final Color unselectedBg = const Color(0xFF3A465B);

    return SizedBox(
      height: 56,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: selected ? selectedBg : unselectedBg,
          foregroundColor: selected ? Colors.black : Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
        ),
        child: Text(label),
      ),
    );
  }
}
