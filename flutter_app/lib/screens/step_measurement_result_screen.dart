import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/voice_service.dart';
import '../models/step_measurement_result.dart';

class StepMeasurementResultScreen extends StatefulWidget {
  final StepMeasurementResult measurementResult;
  final VoidCallback? onContinue;

  const StepMeasurementResultScreen({
    super.key,
    required this.measurementResult,
    this.onContinue,
  });

  @override
  State<StepMeasurementResultScreen> createState() =>
      _StepMeasurementResultScreenState();
}

class _StepMeasurementResultScreenState
    extends State<StepMeasurementResultScreen> {
  final VoiceService _voiceService = VoiceService(
    navigatorKey: GlobalKey<NavigatorState>(),
  );
  bool _isAnnouncementComplete = false;

  StepMeasurementResult get measurementResult => widget.measurementResult;

  @override
  void initState() {
    super.initState();
    _announceResults();
  }

  Future<void> _announceResults() async {
    // TODO: TTS 구현 - 음성 안내
    // await _voiceService.speak("측정이 완료되었습니다.");
    // await _voiceService.speak(
    //   "측정된 보폭은 ${measurementResult.stepLength.toStringAsFixed(1)}센티미터입니다. "
    //   "총 ${measurementResult.stepCount}걸음을 측정했습니다."
    // );
    // await _voiceService.speak("화면을 터치하면 다음 단계로 진행합니다.");

    setState(() {
      _isAnnouncementComplete = true;
    });
  }

  void _handleScreenTap(TapUpDetails details) {
    if (!_isAnnouncementComplete) return;

    // 전체 화면 터치로 다음 단계 진행
    _onContinue();
  }

  void _onContinue() async {
    HapticFeedback.lightImpact();
    // TODO: TTS 구현 - 진행 안내
    // await _voiceService.speak("다음 단계로 진행합니다.");
    if (widget.onContinue != null) {
      widget.onContinue!();
    }
  }

  @override
  Widget build(BuildContext context) {

    return Scaffold(
      backgroundColor: Colors.black,
      body: GestureDetector(
        onTapUp: _handleScreenTap,
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              children: [
                // 헤더
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.grey[900],
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Column(
                    children: [
                      Icon(
                        Icons.check_circle_outline,
                        size: 48,
                        color: Colors.white,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        '측정 완료',
                        style: TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 32),

                // 측정 결과
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      // 보폭 결과
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(24),
                        decoration: BoxDecoration(
                          color: Colors.grey[900],
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          children: [
                            Text(
                              '측정된 보폭',
                              style: TextStyle(
                                fontSize: 20,
                                color: Colors.grey[400],
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              '${measurementResult.stepLength.toStringAsFixed(1)} cm',
                              style: TextStyle(
                                fontSize: 48,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                          ],
                        ),
                      ),

                      const SizedBox(height: 24),

                      // 걸음 수 정보
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                          color: Colors.grey[900],
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          children: [
                            Text(
                              '측정된 걸음 수',
                              style: TextStyle(
                                fontSize: 18,
                                color: Colors.grey[400],
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              '${measurementResult.stepCount}걸음',
                              style: TextStyle(
                                fontSize: 32,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                // 하단 안내 버튼
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.grey[900],
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 20),
                    decoration: BoxDecoration(
                      color: Colors.blue.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.touch_app, color: Colors.blue, size: 32),
                        const SizedBox(width: 16),
                        Text(
                          '화면 터치하여 다음 단계로',
                          style: TextStyle(
                            fontSize: 20,
                            color: Colors.blue,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _voiceService.dispose();
    super.dispose();
  }
}
