import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';

class VoiceTestScreen extends StatelessWidget {
  const VoiceTestScreen({super.key});

  @override
  Widget build(BuildContext context) {
    // context.watch<VoiceService>()를 사용하면 VoiceService의 상태가
    // 변경될 때마다 이 화면이 자동으로 다시 그려집니다.
    final voiceService = context.watch<VoiceService>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('OpenAI 음성 인식 테스트'),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: () {
              // context.read는 메서드 호출에 사용됩니다.
              context.read<VoiceService>().clearLogs();
            },
            tooltip: '로그 지우기',
          )
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 디버그 로그 표시
            const Text('디버그 로그', style: TextStyle(fontWeight: FontWeight.bold)),
            Expanded(
              child: _buildLogView(voiceService),
            ),
          ],
        ),
      ),
      // 3. 상태에 따라 모양이 바뀌는 녹음 버튼
      floatingActionButton: _buildRecordButton(context, voiceService),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
    );
  }

  // 로그 뷰 위젯
  Widget _buildLogView(VoiceService service) {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ListView.builder(
        reverse: true, // 최신 로그가 맨 아래에 표시되도록
        itemCount: service.debugLogs.length,
        itemBuilder: (context, index) {
          final log = service.debugLogs.reversed.toList()[index];
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8.0, vertical: 4.0),
            child: Text(log, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          );
        },
      ),
    );
  }

  // 핵심 UI: 상태에 따라 다른 아이콘과 기능을 가진 버튼
  Widget _buildRecordButton(BuildContext context, VoiceService service) {
    // VoiceService의 currentState에 따라 버튼 모양과 동작을 결정
    switch (service.currentState) {
      case VoiceState.idle:
        return FloatingActionButton.large(
          onPressed: () => context.read<VoiceService>().startListening(),
          tooltip: '녹음 시작',
          child: const Icon(Icons.mic),
        );
      case VoiceState.listening:
        return FloatingActionButton.large(
          onPressed: () => context.read<VoiceService>().stopListeningAndProcess(),
          tooltip: '녹음 중단 및 처리',
          backgroundColor: Colors.red,
          child: const Icon(Icons.stop),
        );
      case VoiceState.processing:
        return const FloatingActionButton.large(
          onPressed: null, // 처리 중에는 비활성화
          tooltip: '처리 중...',
          backgroundColor: Colors.grey,
          child: CircularProgressIndicator(color: Colors.white),
        );
    }
  }
}