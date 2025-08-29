import 'package:flutter/material.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart'; // ✅ 추가
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

  @override
  void initState() {
    super.initState();
    _gender = widget.initialGender;
    _speed = widget.initialSpeed;
  }

  bool get _hasChanged {
    final g = _gender != widget.initialGender;
    final s = double.parse(_speed.toStringAsFixed(2)) !=
        double.parse(widget.initialSpeed.toStringAsFixed(2));
    return g || s;
  }

  // 온보딩 플로우: 다음 단계(GuardianScreen) 이동
  void _goNext() {
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

  // 설정에서 진입: 값 저장 후 되돌아가기
  void _saveAndPop() {
    Navigator.pop<Map<String, dynamic>>(context, {
      'gender': _gender,
      'speed': _speed,
    });
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  void _backWithoutSave() {
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

      body: SafeArea(
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
                  border: Border.all(color: divider.withOpacity(0.25)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: const [
                        Icon(Icons.volume_up_outlined, color: Colors.white, size: 20),
                        SizedBox(width: 8),
                        Text(
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

                    const Text(
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
                            onTap: () => setState(() => _gender = 'F'),
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: _ChoiceButton(
                            label: '남성 음성',
                            selected: _gender == 'M',
                            onTap: () => setState(() => _gender = 'M'),
                          ),
                        ),
                      ],
                    ),

                    const SizedBox(height: 22),
                    Text(
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
                        border: Border.all(color: divider.withOpacity(0.45)),
                      ),
                      child: Column(
                        children: [
                          Slider(
                            value: _speed,
                            onChanged: (v) => setState(() => _speed = v),
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
                                Text('느림 (0.5x)',
                                    style: TextStyle(color: hint, fontWeight: FontWeight.w600)),
                                Text('빠름 (2.0x)',
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
