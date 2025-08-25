import 'dart:io';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'package:provider/provider.dart';
import '../services/voice_service.dart';
import '../screens/step_measurement_result_screen.dart';
import '../models/step_measurement_result.dart';

/// 보폭 감지를 위한 카메라 측정 화면
/// 음성 명령 및 백엔드와 연동됩니다.
class CameraMeasurementScreen extends StatefulWidget {
  const CameraMeasurementScreen({super.key});

  @override
  State<CameraMeasurementScreen> createState() =>
      _CameraMeasurementScreenState();
}

class _CameraMeasurementScreenState extends State<CameraMeasurementScreen>
    with WidgetsBindingObserver {
  // === Camera 관련 변수 ===
  CameraController? _cameraController;
  List<CameraDescription> _cameras = [];
  bool _isCameraInitialized = false;
  bool _isStreamingActive = false;

  // === VoiceService 연동 ===
  VoiceService? _voiceService;

  // === Measurement 상태 관련 변수 ===
  String _statusMessage = "카메라 초기화 중...";
  double? _currentStepLength;

  // === Stream Control 관련 변수 ===
  DateTime? _lastFrameTime;
  static const int _frameIntervalMs = 1000; // takePicture() 방식을 위한 1 FPS 설정

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initializeVoiceService();
    _initializeCamera();
  }

  /// Provider로부터 VoiceService 초기화
  void _initializeVoiceService() {
    try {
      _voiceService = context.read<VoiceService>();
      
      // VoiceService 상태 변경 리스너 추가
      _voiceService!.addListener(_onVoiceServiceStateChanged);
      
      // 측정 완료 콜백 설정
      _voiceService!.setMeasurementCallbacks(
        onComplete: _onMeasurementComplete,
      );
      
      // 카메라 모드에서 음성 명령 대기 시작
      _voiceService!.startAutoRecognitionCycle();
      
      debugPrint("✅ VoiceService 초기화 성공");
    } catch (e) {
      debugPrint("❌ Failed to 초기화 실패: $e");
      setState(() {
        _statusMessage = "VoiceService 초기화 실패";
      });
    }
  }

  /// VoiceService 상태 변경 처리
  void _onVoiceServiceStateChanged() {
    if (!mounted || _voiceService == null) return;
    
    // VoiceService의 상태나 메시지가 변경되면 UI 업데이트
    setState(() {
      // 음성 인식 상태에 따라 상태 메시지 업데이트
      switch (_voiceService!.currentState) {
        case VoiceState.listening:
          if (_statusMessage.contains('측정 중:')) {
            // 측정 중일 때는 측정 상태 유지
            break;
          }
          _statusMessage = '음성 명령 대기 중... (완료라고 말하세요)';
          break;
        case VoiceState.processing:
          _statusMessage = '음성 명령 처리 중...';
          break;
        case VoiceState.idle:
          if (!_statusMessage.contains('측정 중:') && !_statusMessage.contains('완료')) {
            _statusMessage = '실시간 보폭 측정 중...';
          }
          break;
      }
    });
  }

  /// 측정 완료 콜백 처리
  void _onMeasurementComplete(Map<String, dynamic> result) {
    if (!mounted) return;
    
    debugPrint("📊 측정 완료 콜백 받음: $result");
    
    // 측정 완료 시 카메라 스트리밍 중지
    _stopStreaming();
    
    // 자동 음성 인식도 중지
    _voiceService?.stopAutoRecognitionCycle();
    
    // 측정 완료 음성 안내 후 결과 화면으로 전환
    _showMeasurementResult(result);
  }

  /// 측정 결과를 처리하고 결과 화면으로 전환
  void _showMeasurementResult(Map<String, dynamic> result) {
    // TODO: TTS 구현 - 측정 완료 음성 안내
    // await _voiceService?.speak("측정이 완료되었습니다.");
    
    // 측정 결과를 StepMeasurementResult 모델로 변환
    StepMeasurementResult measurementResult;
    
    if (result['final_result'] != null) {
      // 백엔드에서 받은 결과 사용
      measurementResult = StepMeasurementResult.fromJson(result['final_result']);
    } else {
      // 기본값으로 결과 생성 (임시)
      measurementResult = StepMeasurementResult(
        stepLength: 65.0,  // 임시 기본값
        confidence: 0.7,
        stepCount: result['total_steps'] ?? 10,
        trackingQuality: 'good',
        accuracyLevel: '보통',
        measurementMethod: 'kalman_filter',
      );
    }
    
    // 상태 업데이트
    setState(() {
      _statusMessage = '측정 완료! 결과를 확인하세요.';
    });
    
    // 짧은 딜레이 후 결과 화면으로 전환
    Future.delayed(const Duration(milliseconds: 500), () {
      if (mounted && context.mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (context) => StepMeasurementResultScreen(
              measurementResult: measurementResult,
              onContinue: () {
                // 다음 단계로 진행 (메인 화면으로 돌아가기)
                Navigator.of(context).pop();
              },
            ),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    
    // VoiceService 리스너 정리
    if (_voiceService != null) {
      _voiceService!.removeListener(_onVoiceServiceStateChanged);
      _voiceService!.onMeasurementComplete = null;
      _voiceService!.onMeasurementStart = null;
      
      // 자동 음성 인식 사이클 중지
      _voiceService!.stopAutoRecognitionCycle();
    }
    
    _disposeCameraResources();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    switch (state) {
      case AppLifecycleState.paused: // 앱이 백그라운드로 전환될 때
        _stopStreaming();
        _disposeCameraResources();
        break;
      case AppLifecycleState.resumed: // 앱이 다시 포그라운드로 돌아올 때
        _initializeCamera();
        break;
      default:
        break;
    }
  }

  /// 카메라 초기화하고 스트리밍 시작
  Future<void> _initializeCamera() async {
    try {
      setState(() {
        _statusMessage = "카메라 권한 확인 중...";
      });

      // 사용가능한 카메라 목록
      _cameras = await availableCameras();
      if (_cameras.isEmpty) {
        setState(() {
          _statusMessage = "사용 가능한 카메라가 없습니다";
        });
        return;
      }

      // 기본으로 후면, 없으면 첫 번째 카메라
      final camera = _cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.back,
        orElse: () => _cameras.first,
      );

      setState(() {
        _statusMessage = "카메라 초기화 중...";
      });

      // 카메라 컨트롤러 초기화
      _cameraController = CameraController(
        camera,
        ResolutionPreset.medium,
        enableAudio: false,
      );

      await _cameraController!.initialize();

      setState(() {
        _isCameraInitialized = true;
        _statusMessage = "카메라 준비 완료";
      });

      // 카메라 준비 완료 시 자동으로 스트리밍 시작
      await _startStreaming();
    } catch (e) {
      setState(() {
        _statusMessage = "카메라 초기화 실패: $e";
      });
    }
  }

  /// 측정을 위한 주기적인 프레임 캡처 시작
  Future<void> _startStreaming() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    setState(() {
      _isStreamingActive = true;
      _statusMessage = "실시간 보폭 측정 중...";
    });

    // 주기적인 프레임 캡처 시작 (1 FPS)
    _startPeriodicCapture();
  }

  /// 스트리밍 대신 주기적인 이미지 캡처 시작
  void _startPeriodicCapture() {
    Future.doWhile(() async {
      if (!_isStreamingActive) return false;

      // 캡처 속도 조절
      final now = DateTime.now();
      if (_lastFrameTime != null &&
          now.difference(_lastFrameTime!).inMilliseconds < _frameIntervalMs) {
        await Future.delayed(const Duration(milliseconds: 100));
        return true;
      }
      _lastFrameTime = now;

      try {
        await _captureAndProcessFrame();
      } catch (e) {
        debugPrint("Error in 주기적 캡처: $e");
      }

      // 스트리밍이 여전히 활성 상태이면 루프 계속
      return _isStreamingActive;
    });
  }

  /// 스트리밍 중지 및 정리
  Future<void> _stopStreaming() async {
    setState(() {
      _isStreamingActive = false;
      _statusMessage = "측정 중지됨";
    });
  }

  /// takePicture를 사용하여 프레임을 캡처하고 측정을 위해 처리
  Future<void> _captureAndProcessFrame() async {
    if (!_isStreamingActive ||
        _cameraController == null ||
        !_cameraController!.value.isInitialized ||
        _voiceService == null) {
      return;
    }

    try {
      // takePicture를 사용하여 프레임을 파일로 캡처
      final XFile picture = await _cameraController!.takePicture();
      final imageFile = File(picture.path);

      debugPrint("📸 Frame captured: ${imageFile.path}");

      // VoiceService를 사용하여 프레임 업로드
      final result = await _voiceService!.uploadMeasurementFrame(
        imageFile,
        'current_user',
      );

      // 측정 응답 처리
      _handleMeasurementResponse(result);

      // 임시 파일 정리
      try {
        await imageFile.delete();
        debugPrint("🗑️ 임시 파일 삭제 완료: ${imageFile.path}");
      } catch (e) {
        debugPrint("⚠️ 임시 파일 삭제 실패: $e");
      }
    } catch (e) {
      debugPrint("❌ 프레임 캡처/처리 중 오류 발생: $e");
      // Update UI with error status
      if (mounted) {
        setState(() {
          _statusMessage = "프레임 처리 오류: ${e.toString().substring(0, 50)}...";
        });
      }
    }
  }

  /// VoiceService로부터 받은 측정 응답 처리
  void _handleMeasurementResponse(Map<String, dynamic> data) {
    if (!mounted) return;

    setState(() {
      if (data['success'] == true && data['measurement'] != null) {
        // FastDepth 측정 결과
        final measurement = data['measurement'];

        _currentStepLength = measurement['step_length_cm']?.toDouble();

        if (_currentStepLength != null) {
          _statusMessage = "측정 중: ${_currentStepLength!.toStringAsFixed(1)}cm ";
        } else {
          _statusMessage = "측정 데이터 처리 중...";
        }

        debugPrint("✅ 측정 성공: ${_currentStepLength}cm");
      } else if (data['success'] == false) {
        // Measurement failed
        final errorMessage = data['message'] ?? data['error'] ?? '알 수 없는 오류';
        _statusMessage = "측정 실패: $errorMessage";

        // Clear previous measurements on error
        _currentStepLength = null;

        debugPrint("❌ 측정 실패: $errorMessage");
      } else {
        _statusMessage = "측정 응답 처리 중...";
        debugPrint("⚠️ 예상치 못한 응답 형식: $data");
      }
    });
  }

  /// 카메라 리소스 해제
  void _disposeCameraResources() {
    _cameraController?.dispose();
    _cameraController = null;
    setState(() {
      _isCameraInitialized = false;
      _isStreamingActive = false;
    });
  }

  /// 뒤로 가기 버튼 처리
  Future<void> _onWillPop() async {
    // 스트리밍 및 측정 세션 중지
    await _stopStreaming();

    // 이 부분은 사용자가 "측정 중지"라고 말했을 때 voice service가 처리합니다.
    // voice service가 측정 세션 정리를 자동으로 처리합니다.
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: true,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) {
          await _onWillPop();
        }
      },
      child: Scaffold(
        backgroundColor: Colors.black,
        appBar: AppBar(
          title: const Text('보폭 측정'),
          backgroundColor: Colors.black87,
          foregroundColor: Colors.white,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () async {
              await _onWillPop();
              if (context.mounted) {
                Navigator.of(context).pop();
              }
            },
          ),
        ),
        body: Column(
          children: [
            // Camera 미리보기
            Expanded(
              child:
                  _isCameraInitialized && _cameraController != null
                      ? Stack(
                        children: [
                          // Camera 미리보기
                          CameraPreview(_cameraController!),

                          // Measurement 결과 오버레이 (top)
                          _buildMeasurementOverlay(),

                          // 음성 제어 안내 오버레이 (bottom)
                          _buildVoiceControlHint(),
                        ],
                      )
                      : Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const CircularProgressIndicator(
                              color: Colors.white,
                            ),
                            const SizedBox(height: 16),
                            Text(
                              _statusMessage,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 16,
                              ),
                            ),
                          ],
                        ),
                      ),
            ),
          ],
        ),
      ),
    );
  }

  /// 측정 결과 오버레이 위젯 생성
  Widget _buildMeasurementOverlay() {
    return Positioned(
      top: 20,
      left: 20,
      right: 20,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [Colors.black87, Colors.black54],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: _currentStepLength != null ? Colors.green : Colors.white30,
            width: 2,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (_currentStepLength != null) ...[
              // Main measurement display
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.directions_walk, color: Colors.white, size: 24),
                  const SizedBox(width: 8),
                  Text(
                    '${_currentStepLength!.toStringAsFixed(1)}cm',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
            ] else ...[
              // Loading or status display
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_isStreamingActive) ...[
                    SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    ),
                    const SizedBox(width: 12),
                  ],
                  Flexible(
                    child: Text(
                      _statusMessage,
                      style: const TextStyle(color: Colors.white, fontSize: 16),
                      textAlign: TextAlign.center,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// 음성 제어 안내 오버레이 위젯 생성
  Widget _buildVoiceControlHint() {
    return Positioned(
      bottom: 20,
      left: 20,
      right: 20,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.black54,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          children: [
            Text(
              '음성 명령으로 측정을 제어하세요',
              style: const TextStyle(color: Colors.white, fontSize: 14),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 4),
            Text(
              '"보폭 측정 완료" 또는 "측정 끝"이라고 말하세요',
              style: const TextStyle(color: Colors.white70, fontSize: 12),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
