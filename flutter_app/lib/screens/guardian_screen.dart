import 'package:flutter/material.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart';
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

  @override
  void initState() {
    super.initState();
    _nameCtrl = TextEditingController(text: widget.initialName);
    _phoneCtrl = TextEditingController(text: widget.initialPhone);
    _nameCtrl.addListener(() => setState(() {}));
    _phoneCtrl.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
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

  // 온보딩 플로우: 모드 선택으로 이동
  void _goNext() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const ModeScreen()),
    );
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content:
        Text('보호자 등록: ${_nameCtrl.text} / ${_phoneCtrl.text}'),
      ),
    );
  }

  // 설정에서 진입: 값 저장 후 이전 화면으로 반환
  void _saveAndPop() {
    Navigator.pop<Map<String, String>>(context, {
      'name': _nameCtrl.text.trim(),
      'phone': _phoneCtrl.text.trim(),
    });
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  Future<bool> _backWithoutSave() async {
    if (widget.fromSettings && _changedOnly) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('변경사항이 저장되지 않았습니다.')),
      );
    }
    Navigator.pop(context); // 결과 없이 Pop → 저장 안 됨
    return false; // WillPopScope에 의해 기본 pop 막기
  }

  @override
  Widget build(BuildContext context) {
    const bg = Color(0xFF000000);
    const panel = Color(0xFF0D1320);
    const field = Color(0xFF151C2C);
    const divider = Color(0xFF22304A);
    const hint = Color(0xFF9AA3B2);

    InputDecoration inputDec(String hintText) => InputDecoration(
      contentPadding:
      const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
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
      border: Border.all(color: divider.withOpacity(0.4)),
    );

    return WillPopScope(
      onWillPop: widget.fromSettings ? _backWithoutSave : null,
      child: Scaffold(
        backgroundColor: bg,

        // 설정에서만 AppBar + 뒤로가기
        appBar: widget.fromSettings
            ? AppBar(
          backgroundColor: bg,
          elevation: 0,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back_ios_new,
                color: Colors.white),
            onPressed: _backWithoutSave,
          ),
          title: const Text(
            '보호자 설정',
            style: TextStyle(
                color: Colors.white, fontWeight: FontWeight.w900),
          ),
        )
            : null,

        // 하단 버튼 분기
        bottomNavigationBar: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: widget.fromSettings
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
                    border: Border.all(color: divider.withOpacity(0.25)),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.volume_up_outlined,
                          color: Colors.white, size: 20),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
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
                    border: Border.all(color: divider.withOpacity(0.25)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: const [
                          Icon(Icons.person_outline,
                              color: Colors.white, size: 22),
                          SizedBox(width: 8),
                          Text(
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
                      const Text(
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
                      Text(
                        '긴급 상황 시 GPS 위치와 함께 문자 메시지가 전송됩니다',
                        style: TextStyle(
                          color: Colors.white.withOpacity(0.75),
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
                  Text(
                    _canSave
                        ? '변경 사항이 있습니다. 완료를 눌러 저장하세요.'
                        : '변경 사항이 없습니다.',
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
      ),
    );
  }
}
