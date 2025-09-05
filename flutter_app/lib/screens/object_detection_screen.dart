import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:provider/provider.dart';
import '../constants/app_colors.dart';
import '../services/voice_service.dart';
import '../widgets/accessible_text.dart';

/// 객체 인식 전용 카메라 화면
class ObjectDetectionScreen extends StatefulWidget {
  const ObjectDetectionScreen({super.key});

  @override
  State<ObjectDetectionScreen> createState() => _ObjectDetectionScreenState();
}

class _ObjectDetectionScreenState extends State<ObjectDetectionScreen>
    with WidgetsBindingObserver {
  // Camera 관련
  CameraController? _controller;
  List<CameraDescription>? _cameras;
  bool _isCameraReady = false;
  VoiceService? _voiceService;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initializeVoiceService();
    _initializeCamera();
    
    // 화면 진입 안내
    Future.delayed(const Duration(milliseconds: 800), () {
      _announceScreenEntry();
    });
  }

  void _initializeVoiceService() {
    try {
      _voiceService = context.read<VoiceService>();
      debugPrint("✅ ObjectDetectionScreen VoiceService 초기화 성공");
    } catch (e) {
      debugPrint("❌ ObjectDetectionScreen VoiceService 초기화 실패: $e");
    }
  }

  Future<void> _announceScreenEntry() async {
    if (mounted && _voiceService != null) {
      await _voiceService!.speak(
        "객체 인식 카메라 모드입니다. 카메라를 통해 실시간으로 주변 객체와 위험요소를 감지합니다. 뒤로가기 버튼으로 메인 화면으로 돌아갈 수 있습니다.",
        speed: 0.9,
      );
    }
  }

  Future<void> _initializeCamera() async {
    try {
      _cameras = await availableCameras();
      if (_cameras!.isNotEmpty) {
        // 후면 카메라 선택 (객체 인식에 더 적합)
        final backCamera = _cameras!.firstWhere(
          (camera) => camera.lensDirection == CameraLensDirection.back,
          orElse: () => _cameras!.first,
        );

        _controller = CameraController(
          backCamera,
          ResolutionPreset.high,
          enableAudio: false,
        );

        await _controller!.initialize();

        if (mounted) {
          setState(() {
            _isCameraReady = true;
          });
        }

        // 객체 인식 시작
        _startObjectDetection();
      }
    } catch (e) {
      debugPrint('카메라 초기화 오류: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: AccessibleText('카메라를 초기화할 수 없습니다: $e')),
        );
      }
    }
  }

  void _startObjectDetection() {
    // TODO: 실제 객체 인식 로직 구현
    // 현재는 기본 구조만 제공
    debugPrint("🔍 객체 인식 시작됨");
    
    // 시연용: 주기적으로 더미 객체 감지 알림
    _simulateObjectDetection();
  }

  void _simulateObjectDetection() {
    // 시연용 더미 객체 감지 (실제 구현에서는 제거)
    Future.delayed(const Duration(seconds: 5), () {
      if (mounted && _voiceService != null) {
        _voiceService!.speak("주변에 장애물이 감지되었습니다.", speed: 1.0);
      }
      
      // 계속해서 감지 시뮬레이션
      Future.delayed(const Duration(seconds: 10), () {
        _simulateObjectDetection();
      });
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final CameraController? cameraController = _controller;

    if (cameraController == null || !cameraController.value.isInitialized) {
      return;
    }

    if (state == AppLifecycleState.inactive) {
      cameraController.dispose();
    } else if (state == AppLifecycleState.resumed) {
      _initializeCamera();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg.withValues(alpha: 0.7),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(
            Icons.arrow_back_ios_new,
            color: Colors.white,
          ),
          onPressed: () => Navigator.pop(context),
          tooltip: '뒤로가기',
        ),
        title: const AccessibleTitle(
          '객체 인식',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w900,
          ),
        ),
        centerTitle: true,
      ),
      body: Stack(
        children: [
          // 카메라 프리뷰
          if (_isCameraReady && _controller != null)
            Positioned.fill(
              child: CameraPreview(_controller!),
            )
          else
            const Center(
              child: CircularProgressIndicator(color: Colors.white),
            ),

          // 오버레이 UI
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.bottomCenter,
                  end: Alignment.topCenter,
                  colors: [
                    Colors.black.withValues(alpha: 0.8),
                    Colors.transparent,
                  ],
                ),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.panel.withValues(alpha: 0.9),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: AppColors.divider.withValues(alpha: 0.3),
                      ),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 12,
                          height: 12,
                          decoration: const BoxDecoration(
                            color: Colors.green,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        const AccessibleText(
                          '객체 인식 중...',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  AccessibleDescription(
                    '카메라가 주변 환경을 분석하여 객체와 위험요소를 감지합니다.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.8),
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}