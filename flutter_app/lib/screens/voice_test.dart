import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';

class VoiceTestScreen extends StatefulWidget {
  const VoiceTestScreen({super.key});

  @override
  State<VoiceTestScreen> createState() => _VoiceTestScreenState();
}

class _VoiceTestScreenState extends State<VoiceTestScreen> {
  // Enhanced workflow state
  bool _isListening = false;
  String _recognizedText = 'Ready for voice commands';
  late VoiceService _voiceService;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _voiceService = context.read<VoiceService>();
    _voiceService.addListener(_onVoiceServiceStateChanged);
  }

  @override
  void dispose() {
    _voiceService.removeListener(_onVoiceServiceStateChanged);
    super.dispose();
  }

  void _onVoiceServiceStateChanged() {
    // VoiceService의 상태가 변경될 때 호출됩니다.
    // 음성 인식을 시작했고(isListening), 서비스 상태가 다시 유휴(idle) 상태가 되면
    // 모든 처리가 완료된 것입니다.
    if (_isListening && _voiceService.currentState == VoiceState.idle) {
      if (mounted) {
        setState(() {
          _recognizedText =
              _voiceService.lastRecognizedText.isNotEmpty
                  ? _voiceService.lastRecognizedText
                  : 'No speech detected';
          _isListening = false;
        });
        print('Voice workflow completed: $_recognizedText');
      }
    }
  }

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
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Workflow status display
            _buildRecognizedText(),
            const SizedBox(height: 16),
            // 디버그 로그 표시
            const Text('디버그 로그', style: TextStyle(fontWeight: FontWeight.bold)),
            Expanded(child: _buildLogView(voiceService)),
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
            child: Text(
              log,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          );
        },
      ),
    );
  }

  // Enhanced button press handler for measurement workflow
  void _onListenPressed() {
    setState(() {
      _isListening = true;
      _recognizedText = 'Listening...';
    });

    try {
      // Use existing voice service listening functionality
      // The listener _onVoiceServiceStateChanged will handle the result.
      _voiceService.startListening();
    } catch (e) {
      if (mounted) {
        setState(() {
          _recognizedText = 'Error: $e';
          _isListening = false;
        });
      }
    }
  }

  // UI feedback display for workflow status
  Widget _buildRecognizedText() {
    return Container(
      padding: const EdgeInsets.all(16.0),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.blue.shade300),
        borderRadius: BorderRadius.circular(8),
        color: Colors.blue.shade50,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Recognized Speech & Workflow Status',
            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
          ),
          const SizedBox(height: 8),
          Text(
            _recognizedText,
            style: const TextStyle(fontSize: 16, color: Colors.black),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  // Enhanced UI: 상태에 따라 다른 아이콘과 기능을 가진 버튼 with workflow support
  Widget _buildRecordButton(BuildContext context, VoiceService service) {
    // Use enhanced workflow if not in auto-recognition cycle
    if (!_isListening && service.currentState == VoiceState.idle) {
      return FloatingActionButton.large(
        onPressed: _onListenPressed,
        tooltip: '음성 인식 시작 (측정 명령 지원)',
        child: const Icon(Icons.mic),
      );
    }

    // Fall back to existing VoiceService behavior for other states
    switch (service.currentState) {
      case VoiceState.idle:
        return FloatingActionButton.large(
          onPressed:
              _isListening
                  ? null
                  : () => context.read<VoiceService>().startListening(),
          tooltip: '녹음 시작',
          child: const Icon(Icons.mic),
        );
      case VoiceState.listening:
        return FloatingActionButton.large(
          onPressed:
              () => context.read<VoiceService>().stopListeningAndProcess(),
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
