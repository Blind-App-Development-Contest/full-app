import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;
import 'package:provider/provider.dart';
import 'package:blind/services/api_service.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';

class CameraModeScreen extends StatefulWidget {
  const CameraModeScreen({super.key});

  @override
  State<CameraModeScreen> createState() => _CameraModeScreenState();
}

class _CameraModeScreenState extends State<CameraModeScreen> {
  final Completer<void> _cameraReadyCompleter = Completer<void>();
  WebSocketChannel? _channel;
  List<dynamic> _detectedObjects = [];
  String? _error;
  String? _userId;

  CameraController? _mobileController;
  bool _isProcessingFrame = false;
  
  // 음성인식 상태 관리
  bool _isListening = false;
  VoiceService? _voiceService;

  @override
  void initState() {
    super.initState();
    _initializeMobileCamera();
    _initializeVoiceService();
  }
  
  void _initializeVoiceService() {
    try {
      _voiceService = Provider.of<VoiceService>(context, listen: false);
      debugPrint('✅ CameraModeScreen VoiceService 초기화 성공');
    } catch (e) {
      debugPrint('❌ CameraModeScreen VoiceService 초기화 실패: $e');
    }
  }

  Future<void> _initializeMobileCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) throw Exception('사용 가능한 카메라가 없습니다.');
      final backCamera = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );

      _mobileController = CameraController(
        backCamera,
        ResolutionPreset.high,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );

      await _mobileController!.initialize();
      _userId = await ApiService().getCurrentUserUuid();
      if (_userId == null) {
        throw Exception('사용자 UUID를 가져올 수 없습니다.');
      }
      _initializeWebSocket();
      _startMobileFrameSending();

      if (!_cameraReadyCompleter.isCompleted) _cameraReadyCompleter.complete();
    } catch (e) {
      _handleInitError(e);
    }
  }

  void _handleInitError(dynamic e) {
    debugPrint('카메라 초기화 실패: $e');
    if (mounted) {
      setState(() => _error = "카메라 초기화 실패: ${e.toString()}");
      if (!_cameraReadyCompleter.isCompleted) {
        _cameraReadyCompleter.completeError(e);
      }
    }
  }

  void _initializeWebSocket() {
    if (_userId == null) {
      debugPrint('웹소켓 초기화 실패: 사용자 UUID가 없습니다.');
      return;
    }
    String backendBaseUrl = ApiService().baseUrl;
    if (backendBaseUrl.startsWith('https://')) {
      backendBaseUrl = backendBaseUrl.replaceFirst('https://', 'wss://');
    } else if (backendBaseUrl.startsWith('http://')) {
      backendBaseUrl = backendBaseUrl.replaceFirst('http://', 'ws://');
    }
    final wsUrl = Uri.parse('$backendBaseUrl/api/camera/stream/$_userId');
    _channel = WebSocketChannel.connect(wsUrl);

    _channel!.stream.listen(
      (data) {
        if (mounted) {
          final decoded = json.decode(data);
          setState(() {
            if (decoded is Map &&
                decoded.containsKey('objects') &&
                decoded['objects'] is List) {
              _detectedObjects = decoded['objects'];
            }
          });
        }
      },
      onError: (error) => setState(() => _error = "웹소켓 오류: $error"),
      onDone: () => setState(() => _error = "웹소켓 연결이 종료되었습니다."),
    );
  }

  void _startMobileFrameSending() {
    _mobileController!.startImageStream((CameraImage cameraImage) {
      if (_isProcessingFrame || !mounted) return;
      _isProcessingFrame = true;

      Future(() {
        try {
          final image = img.Image.fromBytes(
            width: cameraImage.width,
            height: cameraImage.height,
            bytes: cameraImage.planes[0].bytes.buffer,
            format: img.Format.uint8,
            numChannels: 1,
          );

          final List<int> jpeg = img.encodeJpg(image, quality: 75);
          final String base64String = base64Encode(jpeg);

          _channel?.sink.add(json.encode({
            'frame': base64String,
            'timestamp': DateTime.now().toIso8601String(),
          }));
        } catch (e) {
          debugPrint('모바일 프레임 처리 오류: $e');
        } finally {
          _isProcessingFrame = false;
        }
      });
    });
  }

  @override
  void dispose() {
    _mobileController?.stopImageStream();
    _mobileController?.dispose();
    _channel?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black.withValues(alpha: 0.7),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(
            Icons.arrow_back_ios_new,
            color: Colors.white,
          ),
          onPressed: () {
            _speakText('뒤로가기');
            Navigator.pop(context);
          },
          tooltip: '뒤로가기',
        ),
      ),
      body: SafeArea(
        child: Stack(
          fit: StackFit.expand,
          children: [
            FutureBuilder<void>(
              future: _cameraReadyCompleter.future,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.done &&
                    !snapshot.hasError) {
                  return CameraPreview(_mobileController!);
                }
                return Container();
              },
            ),
            FutureBuilder<void>(
              future: _cameraReadyCompleter.future,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.done &&
                    !snapshot.hasError) {
                  final previewSize = _mobileController!.value.previewSize;
                  final videoSize = Size(previewSize!.height, previewSize.width);
                  return CustomPaint(
                    painter: ObjectPainter(
                        objects: _detectedObjects, videoSize: videoSize),
                  );
                }
                return Container();
              },
            ),
            FutureBuilder<void>(
              future: _cameraReadyCompleter.future,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(
                    child: Container(
                      padding: const EdgeInsets.all(20),
                      color: Colors.black.withValues(alpha: 0.7),
                      child: Text(
                        _error ?? snapshot.error.toString(),
                        style: const TextStyle(color: Colors.red, fontSize: 16),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  );
                }
                return Container();
              },
            ),
            const Positioned(
              top: 20,
              left: 20,
              child: Text('카메라 모드',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      shadows: [Shadow(blurRadius: 5.0, color: Colors.black)])),
            ),
            Positioned(
              bottom: 20,
              left: 20,
              right: 20,
              child: Container(
                padding: const EdgeInsets.all(16.0),
                decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.7),
                    borderRadius: BorderRadius.circular(20)),
                child: ElevatedButton.icon(
                  onPressed: () {
                    _speakText(_isListening ? '음성인식 중지' : '음성인식 시작');
                    _toggleVoiceRecognition();
                  },
                  icon: Icon(_isListening ? Icons.mic : Icons.mic_none),
                  label: Text(_isListening ? '음성인식 중지' : '음성인식 시작'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _isListening ? Colors.red : Colors.blue,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                  ),
                ),
              ),
            ),
          ],
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
      _speakText('음성인식을 시작합니다. 물체 찾기, 뒤로가기 등의 명령을 말씀해주세요.');
      // STT 시작
      try {
        await _voiceService!.startListening();
        _voiceService!.addListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ STT 시작 실패: $e');
        setState(() => _isListening = false);
      }
    } else {
      _speakText('음성인식을 중지합니다.');
      // STT 중지
      try {
        await _voiceService!.stopListeningAndProcess();
        _voiceService!.removeListener(_onVoiceServiceUpdate);
      } catch (e) {
        debugPrint('❌ STT 중지 실패: $e');
      }
    }
  }

  /// VoiceService 상태 변경 리스너
  void _onVoiceServiceUpdate() {
    if (_voiceService == null) return;

    final recognizedText = _voiceService!.lastRecognizedText;
    if (recognizedText.isNotEmpty && _isListening) {
      debugPrint('🎤 카메라 화면에서 인식된 텍스트: $recognizedText');
      
      setState(() => _isListening = false);
      _voiceService!.removeListener(_onVoiceServiceUpdate);
      
      _processVoiceCommand(recognizedText);
    }
  }

  /// 음성 명령 처리
  void _processVoiceCommand(String command) {
    final lowerCommand = command.toLowerCase().trim();
    debugPrint('🎯 카메라 화면 음성 명령 처리: $lowerCommand');

    if (lowerCommand.contains('물체') || lowerCommand.contains('찾기') || lowerCommand.contains('탐지')) {
      if (_detectedObjects.isNotEmpty) {
        final objectNames = _detectedObjects.map((obj) => obj['name'] as String).join(', ');
        _speakText('현재 화면에서 $objectNames 을(를) 발견했습니다.');
      } else {
        _speakText('현재 화면에서 감지된 물체가 없습니다.');
      }
    } else if (lowerCommand.contains('뒤로') || lowerCommand.contains('돌아가') || lowerCommand.contains('나가기')) {
      _speakText('이전 화면으로 돌아갑니다.');
      Navigator.pop(context);
    } else if (lowerCommand.contains('설명') || lowerCommand.contains('화면')) {
      final statusText = _detectedObjects.isEmpty 
        ? '카메라 화면입니다. 현재 감지된 물체가 없습니다.' 
        : '카메라 화면입니다. ${_detectedObjects.length}개의 물체가 감지되었습니다.';
      _speakText(statusText);
    } else {
      _speakText('카메라 화면입니다. 물체 찾기, 화면 설명, 뒤로가기 등의 명령을 사용할 수 있습니다.');
    }
  }

  /// 음성 출력 함수
  void _speakText(String text) async {
    await VoiceUtils.speakWithService(_voiceService, text);
  }

}

class ObjectPainter extends CustomPainter {
  final List<dynamic> objects;
  final Size videoSize;

  ObjectPainter({required this.objects, required this.videoSize});

  @override
  void paint(Canvas canvas, Size size) {
    if (videoSize.isEmpty) return;

    final double scaleX = size.width / videoSize.width;
    final double scaleY = size.height / videoSize.height;
    final double scale = min(scaleX, scaleY);

    final double offsetX = (size.width - videoSize.width * scale) / 2;
    final double offsetY = (size.height - videoSize.height * scale) / 2;

    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0
      ..color = Colors.red;

    final textStyle = const TextStyle(
        color: Colors.white, fontSize: 14.0, backgroundColor: Colors.black54);

    for (var obj in objects) {
      if (obj is! Map || obj['box'] is! List || obj['box'].length != 4) {
        continue;
      }

      final double xCenter = obj['box'][0];
      final double yCenter = obj['box'][1];
      final double w = obj['box'][2];
      final double h = obj['box'][3];

      final Rect videoRect = Rect.fromCenter(
        center: Offset(xCenter * videoSize.width, yCenter * videoSize.height),
        width: w * videoSize.width,
        height: h * videoSize.height,
      );

      final Rect screenRect = Rect.fromLTRB(
        videoRect.left * scale + offsetX,
        videoRect.top * scale + offsetY,
        videoRect.right * scale + offsetX,
        videoRect.bottom * scale + offsetY,
      );

      canvas.drawRect(screenRect, paint);

      final textSpan = TextSpan(text: obj['name'], style: textStyle);
      final textPainter =
          TextPainter(text: textSpan, textAlign: TextAlign.left, textDirection: TextDirection.ltr);
      textPainter.layout();
      textPainter.paint(canvas, screenRect.topLeft + const Offset(4, 4));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}