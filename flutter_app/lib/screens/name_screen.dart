import 'package:flutter/material.dart';
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
  late final TextEditingController _nameCtrl;
  bool _canNext = false;

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

  void _goNext() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const StepScreen()),
    );
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
          label: '다음 단계',
          enabled: _canNext,
          onPressed: _canNext ? _goNext : null,
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
                    const Text('이름',
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w700)),
                    const SizedBox(height: 10),
                    Container(
                      decoration: BoxDecoration(
                        color: field,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: divider.withOpacity(0.4)),
                      ),
                      child: TextField(
                        controller: _nameCtrl,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w600),
                        textInputAction: TextInputAction.done,
                        decoration: const InputDecoration(
                          contentPadding: EdgeInsets.symmetric(
                              horizontal: 16, vertical: 16),
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
