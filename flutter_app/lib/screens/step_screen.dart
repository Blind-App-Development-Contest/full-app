import 'package:flutter/material.dart';
import '../widgets/aeye_card.dart';
import '../widgets/next_button.dart';
import '../widgets/set_button.dart'; // ✅ 추가
import 'voice_screen.dart';

class StepScreen extends StatefulWidget {
  const StepScreen({
    super.key,
    this.fromSettings = false,      // ✅ 설정에서 진입 여부
    this.initialStepLengthCm,       // ✅ 기존 보폭(cm) — 설정에서 진입 시 비교용
  });

  final bool fromSettings;
  final int? initialStepLengthCm;

  @override
  State<StepScreen> createState() => _StepScreenState();
}

class _StepScreenState extends State<StepScreen> {
  bool _measured = false;                 // 온보딩용: 측정 완료 여부
  int? _measuredStepLength;               // 설정용: 새로 측정된 보폭(cm)

  bool get _hasChangedFromSettings =>
      widget.fromSettings &&
      _measuredStepLength != null &&
      _measuredStepLength != widget.initialStepLengthCm;

  void _startMeasure() {
    // TODO: 실제 보폭 측정 로직으로 대체
    setState(() {
      _measured = true;
      _measuredStepLength = 80; // 예시 값 (센서/카메라 연동 시 실제 측정치로 대체)
    });

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('보폭 측정을 시작합니다. 평소처럼 10걸음 걸어주세요.')),
    );
  }

  // 온보딩 플로우: 다음 단계(VoiceScreen)로
  void _goNext() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const VoiceScreen()),
    );
  }

  // 설정에서 진입: 변경사항 저장 후 값 반환
  void _saveAndPop() {
    if (_measuredStepLength != null) {
      Navigator.pop<int>(context, _measuredStepLength);
    }
  }

  // 뒤로가기(설정 경로): 저장 없이 나감
  void _backWithoutSave() {
    if (_hasChangedFromSettings) {
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

    // 설정 진입 시: 변경되었는지 여부 판단
    final bool hasChangedFromSettings = widget.fromSettings
        ? (_measuredStepLength != null &&
        _measuredStepLength != widget.initialStepLengthCm)
        : false;

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
              title: const Text('보폭 설정',
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
            )
          : null,

      // ✅ 하단 버튼 분기
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: widget.fromSettings
            ? SetButton(
          label: '완료',
          hasChanged: hasChangedFromSettings,
          onPressed: hasChangedFromSettings ? _saveAndPop : null,
        )
            : NextButton(
          label: '다음 단계',
          enabled: _measured,
          onPressed: _measured ? _goNext : null,
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
                subtitle: widget.fromSettings ? '보폭 재측정' : '1단계: 보폭 측정',
              ),

              // ── 안내 카드
              _InfoCard(
                panel: panel,
                divider: divider,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.volume_up_outlined,
                        color: Colors.white, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        widget.fromSettings
                            ? '보폭을 다시 측정해 저장할 수 있습니다.'
                            : 'A아이 앱에 오신 것을 환영합니다. 먼저 보폭을 측정해주세요.',
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
                    Row(
                      children: const [
                        Icon(Icons.near_me_outlined,
                            color: Colors.white, size: 20),
                        SizedBox(width: 8),
                        Text(
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
                          vertical: 14, horizontal: 16),
                      decoration: BoxDecoration(
                        color: inner,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: divider.withOpacity(0.45)),
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
                          child: const Text('보폭 측정 시작'),
                        ),
                      ),
                    ),

                    const SizedBox(height: 14),
                    Text(
                      widget.fromSettings
                          ? (_measuredStepLength == null
                          ? '현재 설정된 보폭: ${widget.initialStepLengthCm ?? '-'} cm'
                          : '새 보폭: ${_measuredStepLength} cm')
                          : '평소처럼 자연스럽게 10걸음을 걸어주세요',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: hint,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 120), // 스크롤 여유
            ],
          ),
        ),
      ),
    );
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
        border: Border.all(color: divider.withOpacity(0.25)),
      ),
      child: child,
    );
  }
}
