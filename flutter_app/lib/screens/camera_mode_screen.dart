import 'dart:async';
import 'dart:convert';
import 'dart:html' hide VoidCallback; // VoidCallback 이름 충돌 해결
import 'dart:math'; // min 함수 사용을 위해 추가
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:uuid/uuid.dart'; // Added import

class CameraModeScreen extends StatefulWidget {
  const CameraModeScreen({super.key});

  @override
  State<CameraModeScreen> createState() => _CameraModeScreenState();
}

class _CameraModeScreenState extends State<CameraModeScreen> {
  late final String _viewId;
  late VideoElement _videoElement;
  final Completer<void> _cameraReadyCompleter = Completer<void>();

  WebSocketChannel? _channel;
  Timer? _frameSender;
  List<dynamic> _detectedObjects = [];
  String? _error;

  final String _userId = "3fa85f64-5717-4562-b3fc-2c963f66afa6"; // Modified to use specific UUID

  @override
  void initState() {
    super.initState();
    // 웹페이지에서 viewId가 중복되지 않도록 고유 ID 생성
    _viewId = 'web-camera-view-${DateTime.now().millisecondsSinceEpoch}';
    _registerViewFactory();
  }

  void _registerViewFactory() {
    ui_web.platformViewRegistry.registerViewFactory(_viewId, (int viewId) {
      _videoElement = VideoElement()
        ..id = _viewId
        ..autoplay = true
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.objectFit = 'cover';

      window.navigator.mediaDevices
          ?.getUserMedia({'video': true, 'audio': false})
          .then((stream) {
            _videoElement.srcObject = stream;
            // 비디오 데이터가 로드되면 Completer를 완료하여 FutureBuilder에 신호를 보냄
            _videoElement.onLoadedData.listen((event) {
              _initializeWebSocket();
              _startFrameSending();
              if (!_cameraReadyCompleter.isCompleted) {
                _cameraReadyCompleter.complete();
              }
            });
          })
          .catchError((error) {
            if (!_cameraReadyCompleter.isCompleted) {
              setState(() {
                _error = "카메라 접근 오류: ${error.toString()}";
              });
              _cameraReadyCompleter.completeError(error);
            }
          });

      return _videoElement;
    });
  }

  void _initializeWebSocket() {
    final wsUrl = Uri.parse('ws://localhost:8000/api/camera/stream/$_userId');
    _channel = WebSocketChannel.connect(wsUrl);

    _channel!.stream.listen(
      (data) {
        if (mounted) {
          final decoded = json.decode(data);
          setState(() {
            if (decoded is Map && decoded.containsKey('objects') && decoded['objects'] is List) {
              _detectedObjects = decoded['objects'];
            }
          });
        }
      },
      onError: (error) => setState(() => _error = "웹소켓 오류: $error"),
      onDone: () => setState(() => _error = "웹소켓 연결이 종료되었습니다."),
    );
  }

  void _startFrameSending() {
    _frameSender = Timer.periodic(const Duration(milliseconds: 100), (timer) {
      if (_channel == null || _videoElement.readyState < 2) return;

      final canvas = CanvasElement(
        width: _videoElement.videoWidth,
        height: _videoElement.videoHeight,
      );
      canvas.context2D.drawImage(_videoElement, 0, 0);
      final dataUrl = canvas.toDataUrl('image/jpeg', 0.75);
      final base64String = dataUrl.split(',')[1];

      final data = json.encode({
        'frame': base64String,
        'timestamp': DateTime.now().toIso8601String(),
      });

      _channel!.sink.add(data);
    });
  }

  @override
  void dispose() {
    _frameSender?.cancel();
    _channel?.sink.close();
    _videoElement.srcObject?.getTracks().forEach((track) => track.stop());
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
            // HtmlElementView를 항상 빌드하여 뷰 팩토리가 호출되도록 함
            HtmlElementView(viewType: _viewId),

            // FutureBuilder를 사용하여 카메라 준비 상태에 따라 UI를 분기
            FutureBuilder<void>(
              future: _cameraReadyCompleter.future,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.done) {
                  if (snapshot.hasError) {
                    // 에러가 발생하면 중앙에 에러 메시지 표시
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
                  // 카메라가 준비되면 객체 탐지 오버레이를 그림
                  return CustomPaint(
                    painter: ObjectPainter(
                      objects: _detectedObjects,
                      videoSize: Size(
                        _videoElement.videoWidth.toDouble(),
                        _videoElement.videoHeight.toDouble(),
                      ),
                    ),
                  );
                } else {
                  // 카메라 준비 중에는 로딩 인디케이터 표시
                  return const Center(child: CircularProgressIndicator());
                }
              },
            ),

            // 상단 '카메라 모드' 텍스트 (항상 표시)
            const Positioned(
              top: 20,
              left: 20,
              child: Text(
                '카메라 모드',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  shadows: [Shadow(blurRadius: 5.0, color: Colors.black)],
                ),
              ),
            ),

            // 하단 버튼 바 (항상 표시)
            Positioned(
              bottom: 20,
              left: 20,
              right: 20,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 15.0, horizontal: 10.0),
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.7),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _buildBottomButton(icon: Icons.text_fields, label: '주변 안내', onPressed: () {}),
                    _buildBottomButton(icon: Icons.navigation, label: '길찾기', onPressed: () {}),
                    _buildBottomButton(icon: Icons.phone, label: '보호자호출', onPressed: () {}),
                    _buildBottomButton(icon: Icons.settings, label: '설정', onPressed: () {}),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBottomButton({required IconData icon, required String label, required VoidCallback onPressed}) {
    return GestureDetector(
      onTap: onPressed,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white, size: 30),
          const SizedBox(height: 8),
          Text(
            label,
            style: const TextStyle(color: Colors.white, fontSize: 12),
          ),
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
    // 화면과 비디오의 가로세로 비율 중 더 작은 스케일을 사용하여 비율을 유지 (object-fit: cover 와 유사)
    final double scale = min(scaleX, scaleY);

    final double offsetX = (size.width - videoSize.width * scale) / 2;
    final double offsetY = (size.height - videoSize.height * scale) / 2;

    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0
      ..color = Colors.red;

    final textStyle = const TextStyle(
      color: Colors.white,
      fontSize: 14.0,
      backgroundColor: Colors.black54,
    );

    for (var obj in objects) {
      if (obj is! Map || obj['box'] is! List || obj['box'].length != 4) continue;

      final double xCenter = obj['box'][0];
      final double yCenter = obj['box'][1];
      final double w = obj['box'][2];
      final double h = obj['box'][3];

      final Rect videoRect = Rect.fromCenter(
        center: Offset(xCenter * videoSize.width, yCenter * videoSize.height),
        width: w * videoSize.width,
        height: h * videoSize.height,
      );

      // 화면에 맞게 스케일 및 오프셋 적용
      final Rect screenRect = Rect.fromLTRB(
        videoRect.left * scale + offsetX,
        videoRect.top * scale + offsetY,
        videoRect.right * scale + offsetX,
        videoRect.bottom * scale + offsetY,
      );

      canvas.drawRect(screenRect, paint);

      final textSpan = TextSpan(text: obj['name'], style: textStyle);
      final textPainter = TextPainter(text: textSpan, textAlign: TextAlign.left, textDirection: TextDirection.ltr);
      textPainter.layout();
      textPainter.paint(canvas, screenRect.topLeft + const Offset(4, 4));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) {
    return true;
  }
}
