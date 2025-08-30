import 'dart:async'; // Timer를 위해 추가
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // HapticFeedback을 위해 추가
import 'package:camera/camera.dart';
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../services/voice_service.dart';
import '../services/api_service.dart';
import '../models/step_measurement_result.dart';

/// 보폭 측정 전용 카메라 화면
class CameraMeasurementScreen extends StatefulWidget {
  final bool isFromSettings; // 설정에서 온 것인지 온보딩에서 온 것인지 구분

  const CameraMeasurementScreen({
    super.key,
    this.isFromSettings = false, // 기본값은 온보딩
  });

  @override
  State<CameraMeasurementScreen> createState() =>
      _CameraMeasurementScreenState();
}

class _CameraMeasurementScreenState extends State<CameraMeasurementScreen>
    with WidgetsBindingObserver {
  // Camera 관련
  CameraController? _cameraController;
  List<CameraDescription> _cameras = [];
  bool _isCameraInitialized = false;
  bool _isStreamingActive = false;

  // VoiceService 연동
  VoiceService? _voiceService;
  String _statusMessage = "카메라 초기화 중...";

  // 줌 기능 관련
  double _currentZoomLevel = 1.0;
  double _minZoomLevel = 1.0;
  double _maxZoomLevel = 2.0;

  //  발 인식 실패 처리를 위한 변수 추가
  Timer? _detectionTimeoutTimer;
  bool _isFirstDetectionSuccessful = false;

  // 통일된 변수명 사용 (시각장애인 접근성 고려)
  int _frameCount = 0;
  int _failedDetectionCount = 0; // 발 인식 실패 카운터
  double distanceMeters = 0.0; // 총 이동거리 (통일된 이름)
  int stepCount = 0; // 걸음 수 (통일된 이름)
  double stepLength = StepMeasurementResult.defaultStepLengthCm; // 현재 측정 보폭
  DateTime? _measurementStartTime;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initializeVoiceService();
    _initializeCamera();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _detectionTimeoutTimer?.cancel(); // 타이머 해제
    _stopStreaming();
    _disposeCameraResources();
    _voiceService?.removeListener(_onVoiceServiceStateChanged);
    _voiceService?.stopAutoRecognitionCycle();
    super.dispose();
  }

  void _initializeVoiceService() {
    try {
      _voiceService = context.read<VoiceService>();
      _voiceService!.addListener(_onVoiceServiceStateChanged);
      _voiceService!.setMeasurementCallbacks(
        onComplete: _onMeasurementComplete,
      );
      debugPrint("✅ VoiceService 초기화 성공");
    } catch (e) {
      debugPrint("❌ VoiceService 초기화 실패: $e");
      if (mounted) {
        setState(() {
          _statusMessage = "VoiceService 초기화 실패";
        });
      }
    }
  }

  void _onVoiceServiceStateChanged() {
    if (!mounted || _voiceService == null) return;

    setState(() {
      switch (_voiceService!.currentState) {
        case VoiceState.listening:
          if (_statusMessage.contains('측정 중:')) break;
          _statusMessage = '음성 명령 대기 중... (완료라고 말하세요)';
          break;
        case VoiceState.processing:
          _statusMessage = '음성 명령 처리 중...';
          break;
        case VoiceState.idle:
          if (!_statusMessage.contains('측정 중:') &&
              !_statusMessage.contains('완료')) {
            _statusMessage = '실시간 보폭 측정 중...';
          }
          break;
      }
    });
  }

  void _onMeasurementComplete(Map<String, dynamic> result) async {
    if (!mounted) return;

    try {
      debugPrint('🔍 측정 완료 결과 수신: $result');

      // final_result가 있으면 사용, 없으면 기본값으로 측정 결과 생성
      final finalResult = result['final_result'];
      int finalStepLength;

      if (finalResult != null) {
        final measurementResult = StepMeasurementResult.fromJson(finalResult);
        finalStepLength = measurementResult.stepLength.round();
        debugPrint('✅ final_result에서 측정 결과 생성: ${finalStepLength}cm');
      } else {
        // final_result가 없는 경우 현재 측정값 사용
        debugPrint('⚠️ final_result 없음, 현재 측정값으로 결과 생성');
        finalStepLength = stepLength.round();
      }

      // 스트리밍 중단
      _stopStreaming();

      // 측정 결과를 데이터베이스에 저장
      try {
        debugPrint('📊 카메라 측정 결과 저장 시도: ${finalStepLength}cm');
        await ApiService().saveMeasurementResult(
          stepLengthCm: finalStepLength,
          measurementType: 'camera_measurement',
          frameCount: _frameCount,
        );
        debugPrint('✅ 카메라 측정 결과 저장 성공');
      } catch (e) {
        debugPrint('❌ 카메라 측정 결과 저장 실패: $e');
        // 저장 실패해도 계속 진행 (오프라인 모드 고려)
      }

      // 측정값을 step_screen으로 반환
      if (mounted) {
        Navigator.of(context).pop(finalStepLength);
      }
    } catch (e) {
      debugPrint('❌ 측정 결과 처리 오류: $e');
      // 오류 발생 시에도 기본 결과로 반환
      _createFallbackResult();
    }
  }

  // 오류 시 기본 결과 반환
  void _createFallbackResult() {
    final fallbackStepLength = stepLength.round();
    Navigator.of(context).pop(fallbackStepLength);
  }

  Future<void> _initializeCamera() async {
    try {
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 권한 확인 중...";
        });
      }

      _cameras = await availableCameras();
      if (_cameras.isEmpty) {
        if (mounted) {
          setState(() {
            _statusMessage = "사용 가능한 카메라가 없습니다";
          });
        }
        return;
      }

      final camera = _cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.back,
        orElse: () => _cameras.first,
      );

      if (mounted) {
        setState(() {
          _statusMessage = "카메라 초기화 중...";
        });
      }

      _cameraController = CameraController(
        camera,
        ResolutionPreset.veryHigh, // 발 인식 개선을 위해 최고 해상도 사용
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg, // 안정적인 JPEG 포맷
      );

      await _cameraController!.initialize();

      // 발 인识을 위한 카메라 최적화 설정
      try {
        await _cameraController!.setFocusMode(FocusMode.auto);
        await _cameraController!.setExposureMode(ExposureMode.auto);

        // 줌 레벨 초기화
        _minZoomLevel = await _cameraController!.getMinZoomLevel();
        _maxZoomLevel = await _cameraController!.getMaxZoomLevel();
        _currentZoomLevel = _minZoomLevel;

        debugPrint('✅ 카메라 자동 초점/노출 설정 완료');
        debugPrint('📷 줌 범위: ${_minZoomLevel}x - ${_maxZoomLevel}x');
      } catch (e) {
        debugPrint('⚠️ 카메라 설정 실패: $e');
      }

      if (mounted) {
        setState(() {
          _isCameraInitialized = true;
          _statusMessage = "카메라 준비 완료";
        });
      }

      await _startStreaming();
      // 1초 후 자동으로 측정 시작
      Timer(const Duration(seconds: 1), () {
        _startAutomaticMeasurement();
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 초기화 실패: $e";
        });
      }
    }
  }

  Future<void> _startStreaming() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    if (mounted) {
      setState(() {
        _isStreamingActive = true;
        _statusMessage = "실시간 보폭 측정 중...";

        // 측정 세션 초기화 (통일된 변수명 사용)
        _frameCount = 0;
        distanceMeters = 0.0;
        stepCount = 0;
        stepLength = StepMeasurementResult.defaultStepLengthCm;
        _measurementStartTime = DateTime.now();
      });
    }

    // 음성 인식 사이클은 시작하지 않음 (자동 측정)
    _startPeriodicCapture();
    _startDetectionTimeout(); // 타임아웃 타이머 시작
  }

  // 자동 측정 시작
  void _startAutomaticMeasurement() async {
    if (!mounted) return;

    try {
      // 서버에 측정 시작 요청
      final response = await http
          .post(
            Uri.parse(
              '${VoiceService.baseUrl}/api/users/measurement/session/start',
            ),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        if (mounted) {
          setState(() {
            _statusMessage = "보폭 측정을 시작합니다";
          });
        }

        // 측정 시작 음성 안내
        _voiceService?.speak("보폭 측정을 시작합니다. 자연스럽게 걸어주세요.", speed: 1.2);

        debugPrint('✅ 자동 측정 세션 시작됨: ${result['status']}');
      }
    } catch (e) {
      debugPrint('❌ 자동 측정 시작 실패: $e');
    }
  }

  // 자동 측정 완료 (9-10걸음 데이터 수집 완료시 호출)
  void _completeAutomaticMeasurement() async {
    if (!mounted) return;

    try {
      // 스트리밍 중단
      _stopStreaming();

      // 측정 완료 음성 안내
      _voiceService?.speak("측정이 완료되었습니다. 결과를 확인해보세요.", speed: 1.2);

      // 서버에 측정 완료 요청
      final response = await http
          .post(
            Uri.parse(
              '${VoiceService.baseUrl}/api/users/measurement/session/stop',
            ),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        jsonDecode(utf8.decode(response.bodyBytes));

        // 최종 측정 결과 생성
        final finalResult = StepMeasurementResult(
          stepLength: stepLength,
          confidence: 0.8, // 자동 측정 기본 신뢰도
          stepCount: stepCount,
          trackingQuality: 'good',
          accuracyLevel: '높음',
          measurementMethod: 'automatic',
          distanceMeters: distanceMeters,
        );

        // 결과 화면으로 이동
        if (mounted) {
          Navigator.of(context).pop(finalResult);
        }

        debugPrint(
          '✅ 자동 측정 완료: ${finalResult.stepLength}cm, ${finalResult.stepCount}걸음',
        );
      }
    } catch (e) {
      debugPrint('❌ 자동 측정 완료 처리 실패: $e');
      // 오류 발생 시에도 결과 화면으로 이동
      if (mounted) {
        final fallbackResult = StepMeasurementResult(
          stepLength: stepLength,
          confidence: 0.6, // 오류 상황에서는 낮은 신뢰도
          stepCount: stepCount,
          trackingQuality: 'fair',
          accuracyLevel: '보통',
          measurementMethod: 'automatic_fallback',
          distanceMeters: distanceMeters,
        );
        Navigator.of(context).pop(fallbackResult);
      }
    }
  }

  // 일정 시간(60초) 동안 인식이 안 되면 피드백을 주는 함수
  void _startDetectionTimeout() {
    _detectionTimeoutTimer?.cancel(); // 이전 타이머가 있다면 취소
    _detectionTimeoutTimer = Timer(const Duration(seconds: 60), () {
      if (!mounted || _isFirstDetectionSuccessful) return;

      // 음성 안내
      _voiceService?.speak(
        "발 인식에 어려움이 있습니다. 명치 높이에서 발을 향해 카메라를 비추고, 화면을 줌인하여 측정해주세요. 밝은 곳에서 측정하면 더 정확합니다.",
        speed: 0.85,
      );

      // 햅틱 피드백
      HapticFeedback.heavyImpact();

      // 스트리밍 중지 및 이전 화면으로 자동 복귀
      _stopStreaming();
      if (mounted) {
        Navigator.of(context).pop(); // 결과 없이 pop하여 실패 전달
      }
    });
  }

  void _handleMeasurementResponse(Map<String, dynamic> data) {
    if (!mounted) return;

    // 첫 성공 응답 시 타임아웃 타이머를 해제하고 사용자에게 긍정적 피드백
    if (data['success'] == true &&
        data['measurement'] != null &&
        !_isFirstDetectionSuccessful) {
      _detectionTimeoutTimer?.cancel();
      if (mounted) {
        setState(() {
          _isFirstDetectionSuccessful = true;
        });
      }
      _voiceService?.speak(
        "인식이 시작되었습니다. 명치 높이에서 바닥을 향해 카메라를 고정하고 자연스럽게 걸어주세요. 9걸음 후 자동으로 측정이 완료됩니다.",
        speed: 0.9,
      );
    }

    if (mounted) {
      setState(() {
        if (data['success'] == true && data['measurement'] != null) {
          final measurement = data['measurement'];
          // 통일된 변수명으로 측정값 업데이트
          stepLength =
              measurement['step_length_cm']?.toDouble() ??
              StepMeasurementResult.defaultStepLengthCm;

          // 칼만 필터 적용 여부 확인
          final isKalmanUsed = measurement['kalman_applied'] == true;
          final processingMethod =
              measurement['processing_method'] ?? 'unknown';

          String kalmanStatus = isKalmanUsed ? " (칼만 필터 적용)" : " (단순 처리)";
          _statusMessage =
              "측정 중: ${stepLength.toStringAsFixed(1)}cm$kalmanStatus";

          // 걸음 수와 거리 추정값 업데이트 (통일된 변수명)
          if (measurement['estimated_steps'] != null) {
            stepCount = measurement['estimated_steps'];
          }
          if (measurement['estimated_distance'] != null) {
            distanceMeters =
                measurement['estimated_distance']?.toDouble() ?? 0.0;
          }

          debugPrint(
            '📊 측정 결과: ${stepLength}cm, 처리방법: $processingMethod, 칼만필터: $isKalmanUsed, 걸음수: $stepCount',
          );

          // 성공적인 측정 시 실패 카운터 리셋
          _failedDetectionCount = 0;

          // 9-10걸음 데이터 수집 시 자동 완료
          if (stepCount >= 9) {
            _completeAutomaticMeasurement();
          }
        } else if (data['success'] == false) {
          // 서버에서 오는 실패 메시지는 그대로 표시 (예: "너무 가까움")
          final errorMsg = data['message'] ?? '알 수 없는 오류';
          _statusMessage = "측정 중... (발 인식 시도중)";

          // 발 인식 실패 카운터 증가
          _failedDetectionCount++;
          
          // 연속 실패가 3회 미만일 때만 안내 (너무 빈번한 안내 방지)
          if (_failedDetectionCount == 3) {
            if (errorMsg.contains('가까') || errorMsg.contains('거리')) {
              _voiceService?.speak("카메라와 발 사이 거리를 조정해주세요.", speed: 0.9);
            } else if (errorMsg.contains('인식') || errorMsg.contains('발견') || errorMsg.contains('키포인트')) {
              _voiceService?.speak("발이 화면 중앙에 잘 보이도록 카메라 각도를 조정해주세요.", speed: 0.9);
            }
            _failedDetectionCount = 0; // 카운터 리셋
          }

          // 실패 시에도 측정 계속 진행 (기본값 유지)
          debugPrint('발 인식 실패: $errorMsg (시도 계속)');
        }
      });
    }
  }

  void _startPeriodicCapture() {
    Future.doWhile(() async {
      if (!_isStreamingActive) return false;

      try {
        await Future.delayed(const Duration(milliseconds: 2000));

        if (_cameraController != null &&
            _cameraController!.value.isInitialized) {
          // 셔터 소리 없이 사진 촬영
          final picture = await _cameraController!.takePicture();
          _frameCount++; // 프레임 카운트 증가

          if (_voiceService != null) {
            final result = await _voiceService!
                .uploadMeasurementFrameWithMetadata(
                  File(picture.path),
                  'current_user',
                  frameCount: _frameCount,
                  estimatedDistance: distanceMeters,
                  estimatedStepCount: stepCount,
                  sessionStartTime: _measurementStartTime,
                );
            _handleMeasurementResponse(result);
          }

          try {
            await File(picture.path).delete();
          } catch (e) {
            debugPrint('임시 파일 삭제 실패: $e');
          }
        }
      } catch (e) {
        debugPrint('프레임 캡처 오류: $e');
      }

      return _isStreamingActive;
    });
  }

  void _stopStreaming() {
    if (_isStreamingActive && mounted) {
      setState(() {
        _isStreamingActive = false;
      });
    }
  }

  Future<void> _disposeCameraResources() async {
    try {
      await _cameraController?.dispose();
      _cameraController = null;
      if (mounted) {
        setState(() {
          _isCameraInitialized = false;
        });
      }
    } catch (e) {
      debugPrint('카메라 해제 오류: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text('보폭 측정'),
        backgroundColor: Colors.black87,
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            Navigator.of(context).pop();
          },
        ),
      ),
      body: Column(
        children: [
          // 카메라 프리뷰
          Expanded(
            child:
                _isCameraInitialized && _cameraController != null
                    ? Stack(
                      children: [
                        GestureDetector(
                          onScaleUpdate: _handleZoomGesture,
                          child: CameraPreview(_cameraController!),
                        ),
                        _buildMeasurementOverlay(),
                        _buildVoiceControlHint(),
                      ],
                    )
                    : Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const CircularProgressIndicator(color: Colors.white),
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
    );
  }

  Widget _buildMeasurementOverlay() {
    return Positioned(
      top: 20,
      left: 20,
      right: 20,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [Colors.black87, Colors.black54],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: stepLength > 0 ? Colors.green : Colors.white30,
            width: 2,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (stepLength > 0) ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.directions_walk,
                    color: Colors.white,
                    size: 24,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    '${stepLength.toStringAsFixed(1)}cm',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ] else ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_isStreamingActive) ...[
                    const SizedBox(
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

  void _handleZoomGesture(ScaleUpdateDetails details) {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    const desiredMaxZoom = 2.0;

    final newZoom =
        (_currentZoomLevel * details.scale)
            .clamp(
              _minZoomLevel,
              math.min(_maxZoomLevel, desiredMaxZoom).toDouble(),
            )
            .toDouble();

    _cameraController!.setZoomLevel(newZoom);

    if ((newZoom - _currentZoomLevel).abs() > 0.01) {
      _cameraController!.setZoomLevel(newZoom);
      setState(() {
        _currentZoomLevel = newZoom;
      });

      // 줌 변경 시 햅틱 피드백
      HapticFeedback.lightImpact();
    }
  }

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
        child: const Column(
          children: [
            Text(
              '📱 정확한 인식을 위한 촬영 팁',
              style: TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.bold,
              ),
              textAlign: TextAlign.center,
            ),
            SizedBox(height: 4),
            Text(
              '• 명치 높이에서 바닥을 향해 카메라를 비추세요\n• 화면을 줌인하여 측정해주세요\n• 발이 화면 중앙에 선명하게 보이도록 하세요\n• 천천히 걸어주세요',
              style: TextStyle(color: Colors.white70, fontSize: 10.5),
              textAlign: TextAlign.center,
            ),
            SizedBox(height: 6),
            Text(
              '"측정 완료"라고 말하면 종료됩니다',
              style: TextStyle(color: Colors.orange, fontSize: 12),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
