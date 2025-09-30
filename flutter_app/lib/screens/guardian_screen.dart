import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/onboarding_service.dart';
import '../services/api_service.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';
import '../utils/voice_recognition_helper.dart';
import 'package:flutter/services.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
import '../widgets/accessible_text.dart';
import 'mode_screen.dart';

class GuardianScreen extends StatefulWidget {
  const GuardianScreen({
    super.key,
    this.fromSettings = false, // 설정에서 진입 여부
    this.initialName = '',
    this.initialPhone = '',
  });

  final bool fromSettings;
  final String initialName;
  final String initialPhone;

  @override
  State<GuardianScreen> createState() => _GuardianScreenState();
}

class _GuardianScreenState extends State<GuardianScreen> {
  late final TextEditingController _nameCtrl;
  late final TextEditingController _phoneCtrl;

  // 음성인식 상태 관리
  bool _isListening = false;
  bool _autoVoiceCycleActive = false;
  VoiceService? _voiceService;

  // 확인 플로우 상태 관리
  bool _isConfirmingInfo = false;
  String _recognizedName = '';
  String _recognizedPhone = '';

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.initialName);
    _phoneCtrl = TextEditingController(text: widget.initialPhone);
    _nameCtrl.addListener(() => setState(() {}));
    _phoneCtrl.addListener(() => setState(() {}));
    _initializeVoiceService();

    // 화면 로드 후 자동 음성 안내
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _startInitialVoiceGuidance();
    });
  }

  void _initializeVoiceService() {
    try {
      _voiceService = Provider.of<VoiceService>(context, listen: false);
      debugPrint('✅ GuardianScreen VoiceService 초기화 성공');
    } catch (e) {
      debugPrint('❌ GuardianScreen VoiceService 초기화 실패: $e');
    }
  }

  @override
  void dispose() {
    _stopAutoVoiceCycle();
    _nameCtrl.dispose();
    _phoneCtrl.dispose();
    super.dispose();
  }

  bool get _nameOk => _nameCtrl.text.trim().isNotEmpty;

  // 010-1234-5678 / 01012345678 허용
  bool get _phoneOk =>
      RegExp(r'^010-?\d{4}-?\d{4}$').hasMatch(_phoneCtrl.text.trim());

  // 온보딩용 NextButton 활성화 조건
  bool get _canNext => _nameOk && _phoneOk;

  // 변경 여부(유효성과 무관하게 값만 비교)
  bool get _changedOnly =>
      _nameCtrl.text.trim() != widget.initialName.trim() ||
      _phoneCtrl.text.trim() != widget.initialPhone.trim();

  // 설정에서 진입 시 SetButton 활성화 조건(유효 + 변경됨)
  bool get _canSave => _nameOk && _phoneOk && _changedOnly;

  // 온보딩 플로우: 모드 선택으로 이동 (백엔드 연동)
  void _goNext() async {
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('다음 단계로 진행합니다.');
    // 선해제: 음성 인식/리스너 정리 후 화면 전환
    try {
      _voiceService?.stopAutoRecognitionCycle();
      _voiceService?.removeListener(_onVoiceServiceUpdate);
      _voiceService?.removeListener(_onAutoVoiceServiceUpdate);
    } catch (_) {}

    final name = _nameCtrl.text.trim();
    final phone = _phoneCtrl.text.trim();

    try {
      // 백엔드에 보호자 정보 등록
      await ApiService().createCaregiver(
        caregiversName: name,
        phoneNumber: phone,
      );

      // OnboardingService에도 데이터 저장
      if (mounted) {
        Provider.of<OnboardingService>(
          context,
          listen: false,
        ).setCaregiverInfo(name, phone);

        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const ModeScreen()),
        );

        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: AccessibleText('보호자 등록 완료: $name')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: AccessibleText('보호자 등록 실패: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  // 설정에서 진입: 값 저장 후 이전 화면으로 반환 (백엔드 연동)
  void _saveAndPop() async {
    // 클릭 음성 피드백 - 구체적 안내로 변경
    _speakText('완료합니다.');

    final name = _nameCtrl.text.trim();
    final phone = _phoneCtrl.text.trim();

    try {
      // 백엔드에 보호자 정보 수정
      await ApiService().updateCaregiver(name: name, phoneNumber: phone);

      if (mounted) {
        Navigator.pop<Map<String, String>>(context, {
          'name': name,
          'phone': phone,
        });

        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: AccessibleText('보호자 정보 수정 완료')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: AccessibleText('보호자 정보 수정 실패: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  Future<bool> _backWithoutSave() async {
    // 클릭 음성 피드백
    _speakText('뒤로가기');

    if (widget.fromSettings && _changedOnly) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: AccessibleText('변경사항이 저장되지 않았습니다.')),
      );
    }
    // 선해제 후 Pop
    try {
      _voiceService?.stopAutoRecognitionCycle();
      _voiceService?.removeListener(_onVoiceServiceUpdate);
      _voiceService?.removeListener(_onAutoVoiceServiceUpdate);
    } catch (_) {}
    if (!mounted) return false;
    Navigator.pop(context); // 결과 없이 Pop → 저장 안 됨
    return false; // PopScope에 의해 기본 pop 막기
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const field = Color(0xFF151C2C);
    const divider = Color(0xFF22304A);
    const hint = Color(0xFF9AA3B2);

    InputDecoration inputDec(String hintText) => InputDecoration(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: InputBorder.none,
      hintText: hintText,
      hintStyle: const TextStyle(
        color: hint,
        fontSize: 16,
        fontWeight: FontWeight.w600,
      ),
    );

    final BoxDecoration fieldBox = BoxDecoration(
      color: field,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: divider.withValues(alpha: 0.4)),
    );

    return PopScope(
      onPopInvokedWithResult:
          widget.fromSettings
              ? (didPop, _) async {
                if (!didPop) await _backWithoutSave();
              }
              : null,
      child: GestureDetector(
        onTap: () {
          // 배경 터치 시 키보드 내리기
          FocusScope.of(context).unfocus();
        },
        child: Scaffold(
          backgroundColor: bg,

          // 설정에서만 AppBar + 뒤로가기
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
                      '보호자 설정',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  )
                  : null,

          // 하단 버튼 분기
          bottomNavigationBar: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child:
                widget.fromSettings
                    ? SetButton(
                      label: '완료',
                      hasChanged: _canSave,
                      onPressed: _canSave ? _saveAndPop : null,
                    )
                    : NextButton(
                      label: 'A:EYE 시작하기',
                      enabled: _canNext,
                      onPressed: _canNext ? _goNext : null,
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
                    subtitle: widget.fromSettings ? '보호자 설정' : '3단계: 보호자 등록',
                  ),

                  // 안내 카드
                  Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: panel,
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(
                        color: divider.withValues(alpha: 0.25),
                      ),
                    ),
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
                                ? '보호자 정보를 수정하고 완료를 눌러 저장하세요.'
                                : '보호자 정보를 등록해주세요. 긴급 상황 시 연락할 분의 정보입니다.',
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

                  // 폼 카드
                  Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: panel,
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(
                        color: divider.withValues(alpha: 0.25),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: const [
                            Icon(
                              Icons.person_outline,
                              color: Colors.white,
                              size: 22,
                            ),
                            SizedBox(width: 8),
                            AccessibleTitle(
                              '보호자 정보',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 16,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),

                        const SizedBox(height: 22),
                        const AccessibleTitle(
                          '이름',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Container(
                          decoration: fieldBox,
                          child: TextField(
                            controller: _nameCtrl,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                            textInputAction: TextInputAction.next,
                            decoration: inputDec('보호자 이름을 입력하세요'),
                          ),
                        ),

                        const SizedBox(height: 22),
                        const AccessibleTitle(
                          '전화번호',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Container(
                          decoration: fieldBox,
                          child: TextField(
                            controller: _phoneCtrl,
                            keyboardType: TextInputType.phone,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                            decoration: inputDec('010-0000-0000'),
                          ),
                        ),

                        const SizedBox(height: 16),
                        AccessibleDescription(
                          '긴급 상황 시 GPS 위치와 함께 문자 메시지가 전송됩니다',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.75),
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                  ),

                  if (widget.fromSettings) ...[
                    const SizedBox(height: 12),
                    // 현재/변경 값 안내 (설정 진입 시에만)
                    AccessibleText(
                      _canSave ? '변경 사항이 있습니다. 완료를 눌러 저장하세요.' : '변경 사항이 없습니다.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: _canSave ? Colors.white : hint,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],

                  const SizedBox(height: 120),
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
      // 효과음으로 시작 알림 (딘레이 없음)
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
      // 효과음으로 중지 알림
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
      debugPrint('🎤 보호자 화면에서 인식된 텍스트: $recognizedText');

      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리 - 보호자 정보 인식 → 확인 → 자동 전환
  void _processVoiceCommand(String command) async {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 보호자 화면 음성 명령 처리: $lowerCommand');

    // 확인 단계인 경우
    if (_isConfirmingInfo) {
      if (VoiceRecognitionHelper.isConfirmationCommand(command)) {
        // 확인됨 - 자동으로 다음 단계로 전환
        setState(() {
          _nameCtrl.text = _recognizedName;
          _phoneCtrl.text = _recognizedPhone;
          _isConfirmingInfo = false;
        });
        await Future.delayed(const Duration(seconds: 1));
        if (widget.fromSettings) {
          _saveAndPop();
        } else {
          _goNext();
        }
        return;
      } else if (VoiceRecognitionHelper.isRejectionCommand(command)) {
        // 다시 인식
        setState(() {
          _isConfirmingInfo = false;
          _recognizedName = '';
          _recognizedPhone = '';
        });
        await _speakText('다시 보호자 정보를 말씀해주세요. 이름과 전화번호를 차례로 말씀하세요.');
        return;
      }
    }

    // 전화번호 패턴 확인 (숫자만 또는 하이픈 포함)
    final phonePattern = RegExp(r'^[\d\-\s]+$');

    // 기존 방식의 직접 완료 명령
    if (VoiceRecognitionHelper.isCompletionCommand(command)) {
      if (_canSave) {
        // _goNext()와 _saveAndPop()에서 이미 안내하므로 중복 제거
        if (widget.fromSettings) {
          _saveAndPop();
        } else {
          _goNext();
        }
      } else {
        _speakText('이름과 전화번호를 입력해주세요.');
      }
    } else if (VoiceRecognitionHelper.isBackCommand(command)) {
      _speakText('이전 화면으로 돌아갑니다.');
      if (widget.fromSettings) {
        _backWithoutSave();
      } else {
        Navigator.pop(context);
      }
    } else if (phonePattern.hasMatch(command.replaceAll(' ', ''))) {
      // 전화번호로 인식
      final cleanedPhone = command.replaceAll(RegExp(r'[^\d\-]'), '');
      if (_recognizedName.isEmpty) {
        // 이름이 없으면 일반 입력
        setState(() {
          _phoneCtrl.text = cleanedPhone;
        });
        _speakText('전화번호 $cleanedPhone 입력됨.');
      } else {
        // 이름이 있으면 확인 플로우 시작
        setState(() {
          _recognizedPhone = cleanedPhone;
          _isConfirmingInfo = true;
        });
        await _speakText('보호자 $_recognizedName님, 전화번호 $cleanedPhone이 맞습니까?');
      }
    } else if (command.trim().isNotEmpty && command.trim().length <= 20) {
      // 이름으로 인식
      if (_recognizedPhone.isEmpty) {
        setState(() {
          _recognizedName = command.trim();
        });
        _speakText('이름 ${command.trim()}님. 전화번호를 말씀해주세요.');
      } else {
        // 전화번호가 있으면 확인 플로우 시작
        setState(() {
          _recognizedName = command.trim();
          _isConfirmingInfo = true;
        });
        await _speakText(
          '보호자 ${command.trim()}님, 전화번호 $_recognizedPhone이 맞습니까?',
        );
      }
    } else {
      _speakText('이름, 전화번호를 말씀해주세요.');
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

  /// 초기 음성 안내 시작
  void _startInitialVoiceGuidance() async {
    if (_voiceService == null) return;

    // 2초 대기 후 안내 시작 (화면 렌더링 완료 대기)
    await Future.delayed(const Duration(seconds: 2));

    if (!mounted) return;

    if (widget.fromSettings) {
      _speakText('보호자 설정 화면입니다. 마이크 버튼을 눌러 음성으로 입력하세요.');
    } else {
      _speakText('보호자 등록 화면입니다. 마이크 버튼을 눌러 음성으로 입력하세요.');

      // 5초 후 자동 음성 사이클 시작
      Future.delayed(const Duration(seconds: 5), () {
        if (mounted && !_nameOk && !_phoneOk) {
          _startAutoVoiceCycle();
        }
      });
    }
  }

  /// 자동 음성 사이클 시작
  void _startAutoVoiceCycle() async {
    if (_voiceService == null || _autoVoiceCycleActive) return;

    _autoVoiceCycleActive = true;
    debugPrint('🎤 Guardian Screen - 자동 음성 사이클 시작');

    try {
      await _voiceService!.startAutoRecognitionCycle();
      _voiceService!.addListener(_onAutoVoiceServiceUpdate);

      // 간단한 안내
      if (!_nameOk) {
        _speakText("보호자 이름을 말씀해주세요.");
      } else if (!_phoneOk) {
        _speakText("전화번호를 말씀해주세요.");
      } else {
        _speakText("완료라고 말씀하세요.");
      }
    } catch (e) {
      debugPrint('❌ 자동 음성 사이클 시작 실패: $e');
      _autoVoiceCycleActive = false;
    }
  }

  /// 자동 음성 사이클 중지
  void _stopAutoVoiceCycle() {
    if (!_autoVoiceCycleActive || _voiceService == null) return;

    _autoVoiceCycleActive = false;
    debugPrint('🎤 Guardian Screen - 자동 음성 사이클 중지');

    try {
      _voiceService!.stopAutoRecognitionCycle();
      _voiceService!.removeListener(_onAutoVoiceServiceUpdate);
    } catch (e) {
      debugPrint('❌ 자동 음성 사이클 중지 실패: $e');
    }
  }

  /// 자동 음성 사이클용 리스너
  void _onAutoVoiceServiceUpdate() {
    if (_voiceService == null || !_autoVoiceCycleActive) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty) {
      debugPrint('🎤 Guardian Screen 자동 사이클 - 인식된 텍스트: $recognizedText');
      _processVoiceCommand(recognizedText);
    }
  }
}
