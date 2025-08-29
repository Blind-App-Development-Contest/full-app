import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import 'step_screen.dart';

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

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.initialName ?? '');
    _canNext = _nameCtrl.text.trim().isNotEmpty;
    _nameCtrl.addListener(() {
      final ok = _nameCtrl.text.trim().isNotEmpty;
      if (ok != _canNext) setState(() => _canNext = ok);
    });
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
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

    setState(() => _loading = true);

    try {
      // 0) 앱 고유 UUID 확보/생성
      final appUuid = await _getOrCreateAppUuid();

      // 1) 서버에 사용자 등록 요청
      //    NOTE:
      //    - iOS 시뮬/맥에선 localhost OK
      //    - Android 에뮬레이터면 http://10.0.2.2:8000/users/register 사용
      //    - 실기기는 PC의 LAN IP 사용
      final uri = Uri.parse('http://localhost:8000/users/register');
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
        throw Exception('가입 실패: ${resp.statusCode} ${resp.reasonPhrase}\nURL: $uri\nBody: ${resp.body}');
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
        SnackBar(content: Text('가입 처리 중 오류: $e')),
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
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const AeyeCard(
                title: 'A:EYE',
                subtitle: '사용자 정보 입력',
              ),
              Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: panel,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: divider.withOpacity(0.25)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
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
                        border: Border.all(color: divider.withOpacity(0.4)),
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
                    Text(
                      '입력하신 이름은 음성 안내 시 사용됩니다.',
                      style: TextStyle(
                        color: Colors.white.withOpacity(0.75),
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
    );
  }
}
