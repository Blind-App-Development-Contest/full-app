import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:provider/provider.dart';

import '../constants/config.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/accessible_text.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';
import '../utils/voice_recognition_helper.dart';
import 'step_screen.dart';
import 'package:flutter/services.dart';

class NameScreen extends StatefulWidget {
  const NameScreen({super.key, this.initialName});

  final String? initialName;

  @override
  State<NameScreen> createState() => _NameScreenState();
}

class _NameScreenState extends State<NameScreen> {
  static const String kUuidKey = 'app_uuid';
  static const String kUserNameKey = 'user_name';

  late final TextEditingController _nameCtrl;
  bool _canNext = false;
  bool _loading = false;

  // 음성인식 상태 관리
  bool _isListening = false;
  VoiceService? _voiceService;

  // 이름 인식 워크플로우 상태 관리
  bool _hasInitialVoiceGuidance = false;
  bool _isConfirmingName = false;
  String _recognizedName = '';

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.initialName ?? '');
    _canNext = _nameCtrl.text.trim().isNotEmpty;
    _nameCtrl.addListener(() {
      final ok = _nameCtrl.text.trim().isNotEmpty;
      if (ok != _canNext) setState(() => _canNext = ok);

      // 사용자가 직접 입력을 시작하면 확인 상태 초기화
      if (ok && _isConfirmingName) {
        setState(() {
          _isConfirmingName = false;
          _recognizedName = '';
        });
      }
    });
    _initializeVoiceService();

    // 화면 로드 후 자동 음성 안내 시작
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _startInitialVoiceGuidance();
    });
  }

  void _initializeVoiceService() {
    try {
      _voiceService = Provider.of<VoiceService>(context, listen: false);
      debugPrint('✅ NameScreen VoiceService 초기화 성공');
    } catch (e) {
      debugPrint('❌ NameScreen VoiceService 초기화 실패: $e');
    }
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    // VoiceService 자동 인식 중지
    try {
      _voiceService?.stopAutoRecognitionCycle();
      debugPrint('✅ NameScreen: 자동 인식 사이클 중지 완료');
    } catch (e) {
      debugPrint('❌ NameScreen: 자동 인식 중지 실패: $e');
    }

    // 리스너 해제
    try {
      _voiceService?.removeListener(_onVoiceServiceUpdate);
      debugPrint('✅ NameScreen: VoiceService 리스너 해제 완료');
    } catch (e) {
      debugPrint('❌ NameScreen: 리스너 해제 실패: $e');
    }

    // 음성 인식 상태 초기화
    if (_isListening) {
      try {
        _voiceService?.stopListeningAndProcess();
        debugPrint('✅ NameScreen: 진행 중인 음성 인식 중지 완료');
      } catch (e) {
        debugPrint('❌ NameScreen: 음성 인식 중지 실패: $e');
      }
    }
    super.dispose();
  }

  // ===== UUID 생성/보관 =====
  Future<String> _getOrCreateAppUuid() async {
    final prefs = await SharedPreferences.getInstance();
    final existed = prefs.getString(kUuidKey);
    if (existed != null && existed.isNotEmpty) return existed;

    final created = _randomUuidV4();
    await prefs.setString(kUuidKey, created);
    return created;
  }

  String _randomUuidV4() {
    final rand = Random.secure();
    final bytes = List<int>.generate(16, (_) => rand.nextInt(256));
    // version & variant bits
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-'
        '${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-'
        '${hex.substring(16, 20)}-'
        '${hex.substring(20)}';
  }

  Future<void> _goNext() async {
    final name = _nameCtrl.text.trim();
    if (name.isEmpty || _loading) return;

    // 클릭 음성 피드백 - 이름 포함
    _speakText('$name님, 다음 설정으로 이동합니다.');

    // 선해제: 음성 인식/리스너 정리 후 화면 전환 (레이스 방지)
    try {
      _voiceService?.stopAutoRecognitionCycle();
      _voiceService?.removeListener(_onVoiceServiceUpdate);
    } catch (_) {}

    setState(() => _loading = true);

    try {
      // 0) 앱 고유 UUID 확보/생성
      final appUuid = await _getOrCreateAppUuid();

      // 1) 서버에 사용자 등록 요청
      //    NOTE:
      //    - iOS 시뮬/맥에선 localhost OK
      //    - Android 에뮬레이터면 http://10.0.2.2:8000/users/register 사용
      //    - 실기기는 PC의 LAN IP 사용
      // final uri = Uri.parse('http://localhost:8000/users/register'); // 로컬 테스트
      final uri = Uri.parse(AppConfig.userRegisterEndpoint);
      final resp = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({
          'app_uuid': appUuid, // ✅ 서버가 요구(필수)
          'user_name': name,
        }),
      );

      if (resp.statusCode != 200 && resp.statusCode != 201) {
        throw Exception(
          '가입 실패: ${resp.statusCode} ${resp.reasonPhrase}\nURL: $uri\nBody: ${resp.body}',
        );
      }

      final body = jsonDecode(resp.body) as Map<String, dynamic>;

      // 2) 로컬 저장
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(kUserNameKey, name);
      // 서버가 추가 식별자를 주면 함께 저장(선택)
      if (body['user_id'] != null) {
        await prefs.setString('user_id', body['user_id'].toString());
      }
      if (body['uuid'] != null) {
        await prefs.setString('server_uuid', body['uuid'].toString());
      }

      if (!mounted) return;

      // 3) 다음 단계(보폭 측정)로 이동
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const StepScreen()),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: AccessibleText('$name님 가입 처리 중 오류: $e')),
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const field = Color(0xFF151C2C);
    const divider = Color(0xFF22304A);
    const hint = Color(0xFF9AA3B2);

    return Scaffold(
      backgroundColor: bg,
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: NextButton(
          label: _loading ? '처리 중...' : '다음 단계',
          enabled: _canNext && !_loading,
          onPressed: (_canNext && !_loading) ? _goNext : null,
        ),
      ),
      body: GestureDetector(
        onTap: () {
          // 배경 터치 시 키보드 내리기
          FocusScope.of(context).unfocus();
        },
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const AeyeCard(title: 'A:EYE', subtitle: '사용자 정보 입력'),
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: panel,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: divider.withValues(alpha: 0.25)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
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
                        decoration: BoxDecoration(
                          color: field,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(
                            color: divider.withValues(alpha: 0.4),
                          ),
                        ),
                        child: TextField(
                          controller: _nameCtrl,
                          enabled: !_loading,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          ),
                          textInputAction: TextInputAction.done,
                          onSubmitted: (_) {
                            if (_canNext && !_loading) _goNext();
                          },
                          decoration: const InputDecoration(
                            contentPadding: EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 16,
                            ),
                            border: InputBorder.none,
                            hintText: '예: 홍길동',
                            hintStyle: TextStyle(
                              color: hint,
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      AccessibleDescription(
                        '입력하신 이름은 음성 안내 시 사용됩니다.',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.75),
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
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
            _isListening
                ? Icons.mic
                : (_isConfirmingName ? Icons.help_outline : Icons.mic_none),
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
      // 효과음으로 시작 알림 (딜레이 없음)
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

  /// 초기 음성 안내 시작
  void _startInitialVoiceGuidance() async {
    if (_hasInitialVoiceGuidance || _voiceService == null) return;

    _hasInitialVoiceGuidance = true;
    await Future.delayed(const Duration(milliseconds: 500));

    // 기존에 입력된 이름이 있으면 포함하여 안내
    final currentName = _nameCtrl.text.trim();
    if (currentName.isNotEmpty) {
      _speakText(
        '이름 입력 화면입니다. 현재 $currentName이 입력되어 있습니다. 수정하시려면 마이크 버튼을 눌러 다시 말씀해주세요.',
      );
    } else {
      _speakText('이름 입력 화면입니다. 마이크 버튼을 눌러 이름을 말씀해주세요.');
    }
  }

  /// VoiceService 상태 변경 리스너
  void _onVoiceServiceUpdate() {
    if (_voiceService == null) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty && _isListening) {
      debugPrint('🎤 이름 화면에서 인식된 텍스트: $recognizedText');

      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);

      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리 - 이름 인식 → 확인 → 자동 전환
  void _processVoiceCommand(String command) async {
    final trimmedCommand = command.trim();
    debugPrint('🎯 이름 화면 음성 명령 처리: $trimmedCommand');

    // 확인 단계인 경우
    if (_isConfirmingName) {
      if (VoiceRecognitionHelper.isConfirmationCommand(command)) {
        // 확인됨 - 자동으로 다음 단계로 전환
        setState(() {
          _nameCtrl.text = _recognizedName;
          _isConfirmingName = false;
        });
        _goNext();
        return;
      } else if (VoiceRecognitionHelper.isRejectionCommand(command)) {
        // 다시 인식
        setState(() {
          _isConfirmingName = false;
          _recognizedName = '';
        });
        await _speakText('다시 이름을 말씀해주세요.');
        return;
      }
    }

    // 이름 인식 단계
    if (trimmedCommand.isNotEmpty && trimmedCommand.length <= 20) {
      setState(() {
        _recognizedName = trimmedCommand;
        _isConfirmingName = true;
      });
      await _speakText('$trimmedCommand님이 맞습니까? 맞으면 네, 틀리면 아니오라고 말씀해주세요.');
    } else if (trimmedCommand.length > 20) {
      await _speakText('이름이 너무 깁니다. 다시 말씀해주세요.');
    } else {
      await _speakText('이름을 다시 말씀해주세요.');
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
}
