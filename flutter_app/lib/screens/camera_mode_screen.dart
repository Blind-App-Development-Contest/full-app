import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;
import 'package:blind/services/api_service.dart';

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

  @override
  void initState() {
    super.initState();
    _initializeMobileCamera();
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
    final wsUrl = Uri.parse('ws://10.0.2.2:8000/api/camera/stream/$_userId');
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
                      color: Colors.black.withOpacity(0.7),
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
                padding: const EdgeInsets.symmetric(
                    vertical: 15.0, horizontal: 10.0),
                decoration: BoxDecoration(
                    color: Colors.black.withOpacity(0.7),
                    borderRadius: BorderRadius.circular(20)),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    Expanded(
                        child: _buildBottomButton(
                            icon: Icons.text_fields,
                            label: '주변 안내',
                            onPressed: () {})),
                    Expanded(
                        child: _buildBottomButton(
                            icon: Icons.navigation,
                            label: '길찾기',
                            onPressed: () {})),
                    Expanded(
                        child: _buildBottomButton(
                            icon: Icons.phone,
                            label: '보호자호출',
                            onPressed: () {})),
                    Expanded(
                        child: _buildBottomButton(
                            icon: Icons.settings,
                            label: '설정',
                            onPressed: () {})),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBottomButton(
      {required IconData icon, required String label, required VoidCallback onPressed}) {
    return GestureDetector(
      onTap: onPressed,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white, size: 30),
          const SizedBox(height: 8),
          Text(label, style: const TextStyle(color: Colors.white, fontSize: 12)),
        ],
      ),
    );
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
      if (obj is! Map || obj['box'] is! List || obj['box'].length != 4)
        continue;

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