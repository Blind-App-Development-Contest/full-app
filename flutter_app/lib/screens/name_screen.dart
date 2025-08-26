import 'package:flutter/material.dart';
import '../widgets/next_button.dart';
import '../widgets/aeye_card.dart';
import 'step_screen.dart'; // ✅ 추가

// =======================
// 앱 시작 진입점
// =======================
void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'A:EYE',
      theme: ThemeData(useMaterial3: true),
      home: const UserScreen(), // ✅ 앱 시작화면
    );
  }
}

// =======================
// UserScreen 화면
// =======================
class UserScreen extends StatefulWidget {
  const UserScreen({super.key});

  @override
  State<UserScreen> createState() => _UserScreenState();
}

class _UserScreenState extends State<UserScreen> {
  final _nameController = TextEditingController();
  bool _enabled = false;

  @override
  void initState() {
    super.initState();
    _nameController.addListener(() {
      final ok = _nameController.text.trim().isNotEmpty;
      if (ok != _enabled) setState(() => _enabled = ok);
    });
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  void _onNext() {
    // ✅ StepScreen으로 이동
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => const StepScreen(),
      ),
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
          enabled: _enabled,
          onPressed: _enabled ? _onNext : null,
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 28, 24, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const AeyeCard(
                title: 'A:EYE',
                subtitle: '사용자 정보 입력',
              ),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(20, 22, 20, 22),
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
                            color: Colors.white, size: 24),
                        SizedBox(width: 8),
                        Text(
                          '사용자 이름',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 22),
                    const Text(
                      '이름을 입력해주세요',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Container(
                      decoration: BoxDecoration(
                        color: field,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: divider.withOpacity(0.4)),
                      ),
                      child: TextField(
                        controller: _nameController,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                        textInputAction: TextInputAction.done,
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
                    const SizedBox(height: 18),
                    Text(
                      '입력하신 이름은 음성 안내 시 사용됩니다',
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
