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
import '../widgets/accessible_text.dart';
import 'voice_screen.dart';

/// 왕복 측정 단계
enum MeasurementPhase { forward, turnAround, backward, completed }

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

  // 왕복 5걸음 측정을 위한 변수
  MeasurementPhase _currentPhase = MeasurementPhase.forward;
  int _forwardSteps = 0;
  int _backwardSteps = 0;
  List<double> _forwardMeasurements = [];
  List<double> _backwardMeasurements = [];

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

      // 측정 완료 후 바로 음성 설정 온보딩으로 이동
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (context) => const VoiceScreen(fromSettings: false),
          )
        );
      }
    } catch (e) {
      debugPrint('❌ 측정 결과 처리 오류: $e');
      // 오류 발생 시에도 기본 결과로 반환
      _createFallbackResult();
    }
  }

  // 오류 시 기본 결과 반환 - 음성 설정 온보딩으로 이동
  void _createFallbackResult() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (context) => const VoiceScreen(fromSettings: false),
      )
    );
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
        ResolutionPreset.medium, // 성능 최적화를 위해 중간 해상도 사용 (보폭 측정에 충분)
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

        // 왕복 측정 시작 음성 안내
        _voiceService?.speak("보폭 측정을 시작합니다. 먼저 앞으로 5걸음 걸어주세요.", speed: 1.2);
        
        if (mounted) {
          setState(() {
            _currentPhase = MeasurementPhase.forward;
            _forwardSteps = 0;
            _backwardSteps = 0;
            _forwardMeasurements.clear();
            _backwardMeasurements.clear();
          });
        }

        debugPrint('✅ 자동 측정 세션 시작됨: ${result['status']}');
      }
    } catch (e) {
      debugPrint('❌ 자동 측정 시작 실패: $e');
    }
  }

  // 왕복 5걸음 측정 처리
  void _handleRoundTripMeasurement(double currentStepLength) {
    switch (_currentPhase) {
      case MeasurementPhase.forward:
        _forwardSteps++;
        _forwardMeasurements.add(currentStepLength);
        
        if (_forwardSteps >= 5) {
          setState(() {
            _currentPhase = MeasurementPhase.turnAround;
          });
          _voiceService?.speak("5걸음 완료! 제자리에서 뒤로 돌아주세요.", speed: 1.0);
          
          // 3초 후 뒤로 걷기 시작
          Timer(const Duration(seconds: 3), () {
            if (mounted) {
              setState(() {
                _currentPhase = MeasurementPhase.backward;
              });
              _voiceService?.speak("이제 원래 자리로 5걸음 걸어주세요.", speed: 1.0);
            }
          });
        } else {
          _voiceService?.speak("$_forwardSteps걸음", speed: 1.2);
        }
        break;

      case MeasurementPhase.backward:
        _backwardSteps++;
        _backwardMeasurements.add(currentStepLength);
        
        if (_backwardSteps >= 5) {
          setState(() {
            _currentPhase = MeasurementPhase.completed;
          });
          _completeRoundTripMeasurement();
        } else {
          _voiceService?.speak("$_backwardSteps걸음", speed: 1.2);
        }
        break;
        
      default:
        break;
    }
  }

  // 왕복 측정 완료 처리
  void _completeRoundTripMeasurement() async {
    if (!mounted) return;

    // 앞뒤 측정값 평균 계산
    final forwardAvg = _forwardMeasurements.isNotEmpty 
        ? _forwardMeasurements.reduce((a, b) => a + b) / _forwardMeasurements.length
        : StepMeasurementResult.defaultStepLengthCm;
    
    final backwardAvg = _backwardMeasurements.isNotEmpty 
        ? _backwardMeasurements.reduce((a, b) => a + b) / _backwardMeasurements.length
        : StepMeasurementResult.defaultStepLengthCm;
    
    // 왕복 평균값으로 최종 보폭 계산
    final finalStepLength = (forwardAvg + backwardAvg) / 2;
    
    debugPrint('🦶 왕복 측정 완료:');
    debugPrint('  - 앞으로: ${forwardAvg.toStringAsFixed(1)}cm (${_forwardMeasurements.length}개)');
    debugPrint('  - 뒤로: ${backwardAvg.toStringAsFixed(1)}cm (${_backwardMeasurements.length}개)');
    debugPrint('  - 최종 보폭: ${finalStepLength.toStringAsFixed(1)}cm');

    try {
      // 스트리밍 중단
      _stopStreaming();

      // 측정 완료 음성 안내
      _voiceService?.speak(
        "왕복 측정이 완료되었습니다. 보폭은 ${finalStepLength.round()}센티미터입니다.", 
        speed: 1.0
      );

      // 서버에 측정 완료 요청
      final response = await http
          .post(
            Uri.parse('${VoiceService.baseUrl}/api/users/measurement/session/stop'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        // 최종 측정 결과 생성 (왕복 데이터 포함)
        final finalResult = StepMeasurementResult(
          stepLength: finalStepLength,
          confidence: 0.9, // 왕복 측정으로 높은 신뢰도
          stepCount: _forwardSteps + _backwardSteps, // 총 10걸음
          trackingQuality: 'excellent',
          accuracyLevel: '매우 높음',
          measurementMethod: 'round_trip_5steps',
          distanceMeters: finalStepLength * (_forwardSteps + _backwardSteps) / 100,
        );

        // 측정 완료 후 설정 화면으로 직접 이동
        if (mounted) {
          // 음성 안내 시간을 위한 지연
          await Future.delayed(const Duration(seconds: 2));
          
          // 음성 설정 온보딩으로 직접 이동 (pushReplacement 사용)
          if (mounted) {
            Navigator.of(context).pushReplacement(
              MaterialPageRoute(
                builder: (context) => const VoiceScreen(fromSettings: false),
              )
            );
          }
        }

        debugPrint('✅ 왕복 측정 완료: ${finalResult.stepLength}cm, 신뢰도: ${finalResult.confidence}');
      }
    } catch (e) {
      debugPrint('❌ 왕복 측정 완료 처리 실패: $e');
      // 오류 발생 시에도 결과 화면으로 이동 (Navigator 안전 처리)
      if (mounted) {
        final fallbackResult = StepMeasurementResult(
          stepLength: finalStepLength,
          confidence: 0.8, // 오류 상황에서는 조금 낮은 신뢰도
          stepCount: _forwardSteps + _backwardSteps,
          trackingQuality: 'good',
          accuracyLevel: '높음',
          measurementMethod: 'round_trip_fallback',
          distanceMeters: finalStepLength * (_forwardSteps + _backwardSteps) / 100,
        );
        
        // 오류 시에도 음성 설정 온보딩으로 이동
        await Future.delayed(const Duration(milliseconds: 500));
        if (mounted) {
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(
              builder: (context) => const VoiceScreen(fromSettings: false),
            )
          );
        }
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

      // 스트리밍 중지 및 음성 설정 온보딩으로 이동
      _stopStreaming();
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (context) => const VoiceScreen(fromSettings: false),
          )
        );
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
        "인식이 시작되었습니다. 명치 높이에서 바닥을 향해 카메라를 고정하고 앞으로 5걸음 걸어주세요.",
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

          // 왕복 측정 로직
          _handleRoundTripMeasurement(stepLength);
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
        title: const AccessibleTitle('보폭 측정'),
        backgroundColor: Colors.black87,
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            Navigator.of(context).pushReplacement(
              MaterialPageRoute(
                builder: (context) => const VoiceScreen(fromSettings: false)
              )
            );
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
                          AccessibleDescription(
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
              // 현재 측정 단계 표시
              AccessibleText(
                _getCurrentPhaseText(),
                style: const TextStyle(
                  color: Colors.orange,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.directions_walk,
                    color: Colors.white,
                    size: 24,
                  ),
                  const SizedBox(width: 8),
                  AccessibleText(
                    '${stepLength.toStringAsFixed(1)}cm',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              AccessibleDescription(
                _getStepCountText(),
                style: const TextStyle(
                  color: Colors.white70,
                  fontSize: 14,
                ),
                textAlign: TextAlign.center,
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
                    child: AccessibleDescription(
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

  String _getCurrentPhaseText() {
    switch (_currentPhase) {
      case MeasurementPhase.forward:
        return '앞으로 걷기 ($_forwardSteps/5)';
      case MeasurementPhase.turnAround:
        return '뒤로 돌아주세요';
      case MeasurementPhase.backward:
        return '뒤로 걷기 ($_backwardSteps/5)';
      case MeasurementPhase.completed:
        return '측정 완료!';
    }
  }

  String _getStepCountText() {
    final totalSteps = _forwardSteps + _backwardSteps;
    return '총 걸음수: $totalSteps/10';
  }

  Widget _buildVoiceControlHint() {
    // 시각장애인을 위한 음성 안내만 사용 - 텍스트 팁 박스 제거
    return const SizedBox.shrink();
  }
}
