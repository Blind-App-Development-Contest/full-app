import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart'; // ✅ 추가
import '../widgets/accessible_text.dart';
import '../services/api_service.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';
import 'guardian_screen.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({
    super.key,
    this.fromSettings = false,  // ✅ 설정 화면에서 진입 여부
    this.initialGender = 'F',   // 'F' or 'M'
    this.initialSpeed = 1.0,    // 0.5 ~ 2.0
  });

  final bool fromSettings;
  final String initialGender;
  final double initialSpeed;

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  late String _gender; // 'F' or 'M'
  late double _speed;  // 0.5 ~ 2.0
  
  // 음성인식 상태 관리
  bool _isListening = false;
  VoiceService? _voiceService;

  @override
  void initState() {
    super.initState();
    _gender = widget.initialGender;
    _speed = widget.initialSpeed;
    
    // VoiceService에 초기 속도 설정
    WidgetsBinding.instance.addPostFrameCallback((_) {
      try {
        _voiceService = context.read<VoiceService>();
        _voiceService!.setVoiceSpeed(_speed);
        debugPrint('🎙️ VoiceScreen 초기화: 음성 속도 ${_speed}x 설정');
      } catch (e) {
        debugPrint('❌ VoiceScreen 초기화: VoiceService 음성 속도 설정 실패: $e');
      }
    });
  }

  bool get _hasChanged {
    final g = _gender != widget.initialGender;
    final s = double.parse(_speed.toStringAsFixed(2)) !=
        double.parse(widget.initialSpeed.toStringAsFixed(2));
    return g || s;
  }

  // 온보딩 플로우: 다음 단계(GuardianScreen) 이동
  void _goNext() async {
    // 클릭 음성 피드백
    _speakText('다음');
    
    // 음성 설정 저장 (온보딩 플로우)
    try {
      debugPrint('🎙️ 온보딩 음성 설정 저장 시도: ${_gender == 'F' ? 'female' : 'male'}, ${_speed}x');
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
          content: Text('설정 저장: ${_gender == 'F' ? '여성' : '남성'}, ${_speed.toStringAsFixed(1)}x'),
        ),
      );
    }
  }

  // 설정에서 진입: 값 저장 후 되돌아가기
  void _saveAndPop() async {
    // 클릭 음성 피드백
    _speakText('저장');
    
    if (_hasChanged) {
      // 음성 설정 저장 (설정 화면에서 진입)
      try {
        debugPrint('🎙️ 설정 음성 변경 저장 시도: ${_gender == 'F' ? 'female' : 'male'}, ${_speed}x');
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('변경사항이 저장되지 않았습니다.')),
      );
    }
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
      appBar: widget.fromSettings
          ? AppBar(
              backgroundColor: bg,
              elevation: 0,
              leading: IconButton(
                icon: const Icon(Icons.arrow_back_ios_new, color: Colors.white),
                onPressed: _backWithoutSave,
              ),
              title: const Text('음성 설정',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
            )
          : null,

      // ✅ 하단 버튼: 설정 경로면 SetButton, 온보딩 경로면 NextButton
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: widget.fromSettings
            ? SetButton(
          label: '완료',
          hasChanged: hasChanged(),
          onPressed: hasChanged() ? _saveAndPop : null,
        )
            : NextButton(
          label: '다음 단계',
          enabled: true,
          onPressed: _goNext,
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
                        Icon(Icons.volume_up_outlined, color: Colors.white, size: 20),
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
                              _speakText('여성 음성');
                              setState(() => _gender = 'F');
                            },
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: _ChoiceButton(
                            label: '남성 음성',
                            selected: _gender == 'M',
                            onTap: () {
                              _speakText('남성 음성');
                              setState(() => _gender = 'M');
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
                        border: Border.all(color: divider.withValues(alpha: 0.45)),
                      ),
                      child: Column(
                        children: [
                          Slider(
                            value: _speed,
                            onChanged: (v) {
                              setState(() => _speed = v);
                              // VoiceService에 속도 변경 알리기
                              try {
                                final voiceService = context.read<VoiceService>();
                                voiceService.setVoiceSpeed(v);
                                debugPrint('🎙️ 음성 속도 변경: ${v}x');
                              } catch (e) {
                                debugPrint('❌ 음성 속도 변경 실패: $e');
                              }
                            },
                            min: 0.5,
                            max: 2.0,
                            divisions: 15, // 0.1 단위
                            label: '${_speed.toStringAsFixed(1)}x',
                          ),
                          Padding(
                            padding: const EdgeInsets.only(top: 2, left: 2, right: 2, bottom: 4),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                AccessibleText('느림 (0.5x)',
                                    style: TextStyle(color: hint, fontWeight: FontWeight.w600)),
                                AccessibleText('빠름 (2.0x)',
                                    style: TextStyle(color: hint, fontWeight: FontWeight.w600)),
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
      _speakText('음성인식을 시작합니다. 여성, 남성, 빠르게, 느리게, 또는 다음을 말씀해주세요.');
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
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('여성 음성으로 설정되었습니다.');
    } else if (lowerCommand.contains('남성') || lowerCommand.contains('남자')) {
      setState(() => _gender = 'M');
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('남성 음성으로 설정되었습니다.');
    } else if (lowerCommand.contains('빠르게') || lowerCommand.contains('빨리')) {
      setState(() => _speed = (_speed + 0.2).clamp(0.5, 2.0));
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('음성 속도가 ${_speed.toStringAsFixed(1)}배로 설정되었습니다.');
    } else if (lowerCommand.contains('느리게') || lowerCommand.contains('천천히')) {
      setState(() => _speed = (_speed - 0.2).clamp(0.5, 2.0));
      _voiceService?.setVoiceSpeed(_speed);
      _speakText('음성 속도가 ${_speed.toStringAsFixed(1)}배로 설정되었습니다.');
    } else if (lowerCommand.contains('다음') || lowerCommand.contains('완료') || lowerCommand.contains('저장')) {
      _speakText('음성 설정을 저장하고 다음 단계로 진행합니다.');
      if (widget.fromSettings) {
        _saveAndPop();
      } else {
        _goNext();
      }
    } else if (lowerCommand.contains('뒤로') || lowerCommand.contains('취소')) {
      _speakText('이전 화면으로 돌아갑니다.');
      if (widget.fromSettings) {
        _backWithoutSave();
      } else {
        Navigator.pop(context);
      }
    } else {
      _speakText('현재 설정은 ${_gender == 'F' ? '여성' : '남성'} 음성, ${_speed.toStringAsFixed(1)}배속입니다. 여성, 남성, 빠르게, 느리게, 다음 중 하나를 말씀해주세요.');
    }
  }

  /// 음성 출력 함수
  void _speakText(String text) async {
    await VoiceUtils.speakWithService(_voiceService, text);
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
          textStyle: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w900,
          ),
        ),
        child: Text(label),
      ),
    );
  }
}
