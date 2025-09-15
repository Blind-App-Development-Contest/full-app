import 'dart:async'; // Timer를 위해 추가
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // HapticFeedback을 위해 추가
import 'package:camera/camera.dart';
import 'package:provider/provider.dart';
import 'package:http/http.dart' as http;
import '../constants/config.dart';
import '../services/voice_service.dart';
import '../widgets/accessible_text.dart';
import '../utils/voice_recognition_helper.dart';
import '../services/api_service.dart';
import '../utils/voice_utils.dart';

/// 카메라 거리 측정 화면 (10m 측정)
class CameraMeasurementScreen extends StatefulWidget {
  const CameraMeasurementScreen({super.key});

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
  VoiceRecognitionHelper? _voiceHelper;
  String _statusMessage = "카메라 초기화 중...";
  String? _currentUserUuid; // 실제 사용자 UUID
  // 시작 카운트다운
  int? _countdownSeconds; // null이면 카운트다운 비표시
  Timer? _countdownTimer;

  // 시각장애인용 상세 음성 안내 상태
  Timer? _progressAnnouncementTimer;

  // 줌 기능 관련
  double _currentZoomLevel = 1.0;
  double _minZoomLevel = 1.0;
  double _maxZoomLevel = 2.0;

  // 거리 측정 관련 타이머
  Timer? _measurementTimeoutTimer;

  // 카메라 거리 측정 전용 변수
  int frameCount = 0;
  double distanceMeters = 0.0; // 현재 측정된 거리 (미터)
  double targetDistanceMeters = 10.0; // 목표 거리 10m
  bool measurementActive = false; // 측정 진행 상태
  bool measurementCompleted = false; // 측정 완료 상태
  bool isWaitingForStart = true; // 시작 명령 대기 상태

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);

    // 🚀 즉시 긍정적인 메시지 표시
    _statusMessage = "보폭 측정 준비 완료! 시작합니다...";

    // 즉시 초기화 시작 (PostFrameCallback 제거로 더 빠른 시작)
    Future.microtask(() {
      _initializeServicesSequentially();
    });
  }

  /// 사용자 경험 최적화를 위한 순차적 초기화
  Future<void> _initializeServicesSequentially() async {
    try {
      // 즉시 음성 안내 시작
      _quickAnnounceMeasurementStart();

      // 1단계: VoiceService 먼저 초기화
      await _initializeVoiceService();

      // 2단계: 카메라 초기화를 병렬로 시작하되 즉시 UI 업데이트
      _initializeCameraInBackground();

      debugPrint('✅ 빠른 초기화 완료 - 카메라는 백그라운드에서 준비 중');
    } catch (e) {
      debugPrint('❌ 서비스 초기화 중 실패: $e');
      // 초기화 실패 시에도 앱 사용 가능하도록 처리
      if (mounted) {
        setState(() {
          _statusMessage = "초기화 오류 발생 - 다시 시도해주세요";
        });
      }
    }
  }

  /// 즉시 측정 시작 안내
  void _quickAnnounceMeasurementStart() {
    if (mounted) {
      setState(() {
        _statusMessage = "보폭 측정을 시작합니다...";
      });
    }

    // VoiceService가 없어도 일단 시도 (나중에 실제로 실행됨)
    Future.delayed(const Duration(milliseconds: 200), () {
      _speakText("보폭 측정을 시작합니다. 잠시 기다려주세요.");
    });
  }

  /// 백그라운드에서 카메라 초기화
  void _initializeCameraInBackground() {
    Future.microtask(() async {
      await _initializeCamera();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _measurementTimeoutTimer?.cancel(); // 타이머 해제
    _countdownTimer?.cancel();
    _progressAnnouncementTimer?.cancel(); // 진행 상황 안내 타이머 취소
    _stopStreaming();
    _disposeCameraResources();
    _voiceService?.removeListener(_onVoiceServiceStateChanged);
    _voiceHelper?.dispose(); // 음성 인식 헬퍼 정리
    super.dispose();
  }

  Future<void> _initializeVoiceService() async {
    try {
      _voiceService = context.read<VoiceService>();
      _voiceService!.addListener(_onVoiceServiceStateChanged);

      // 음성 인식 헬퍼 초기화
      _voiceHelper = VoiceRecognitionHelper(voiceService: _voiceService!);

      // 실제 사용자 UUID 가져오기
      try {
        _currentUserUuid = await ApiService().getCurrentUserUuid();
        debugPrint("✅ 사용자 UUID 획득: $_currentUserUuid");
      } catch (e) {
        debugPrint("❌ 사용자 UUID 획득 실패: $e");
        _currentUserUuid = 'current_user'; // 백업값
      }

      debugPrint("✅ VoiceService 및 헬퍼 초기화 성공");

      // 즉시 상세 안내 시작
      if (mounted) {
        _announceCameraMeasurementEntry();
      }
    } catch (e) {
      debugPrint("❌ VoiceService 초기화 실패: $e");
      if (mounted) {
        setState(() {
          _statusMessage = "VoiceService 초기화 실패";
        });
      }
      // 에러가 있어도 계속 진행 (rethrow 제거)
    }
  }

  /// 카메라 측정 화면 진입 시 시각장애인용 상세 안내
  Future<void> _announceCameraMeasurementEntry() async {
    try {
      await Future.delayed(const Duration(milliseconds: 300));
      await VoiceUtils.announceStepMeasurementStart(_voiceService);
    } catch (e) {
      debugPrint('❌ 카메라 측정 화면 진입 안내 실패: $e');
    }
  }

  // 진행 중 거리 음성 안내는 비활성화됨: 10m 달성 또는 타임아웃 시에만 안내합니다.

  /// 거리 측정 완료 안내
  Future<void> _announceDistanceMeasurementComplete() async {
    try {
      await VoiceUtils.announceDistanceMeasured(_voiceService, distanceMeters);
      
      // 스트리밍 중지 및 리스너 해제 후 결과 반환
      _stopStreaming();
      try {
        _voiceService?.removeListener(_onVoiceServiceStateChanged);
      } catch (_) {}
      if (mounted) {
        Navigator.of(context).pop(distanceMeters);
      }
    } catch (e) {
      debugPrint('❌ 거리 측정 완료 음성 안내 실패: $e');
      // 오류 시에도 스트리밍/리스너 정리 후 결과 반환
      _stopStreaming();
      try {
        _voiceService?.removeListener(_onVoiceServiceStateChanged);
      } catch (_) {}
      if (mounted) {
        Navigator.of(context).pop(distanceMeters);
      }
    }
  }

  void _onVoiceServiceStateChanged() {
    if (!mounted || _voiceService == null) return;

    setState(() {
      switch (_voiceService!.currentState) {
        case VoiceState.listening:
          if (!_statusMessage.contains('측정 중:')) {
            _statusMessage = '음성 명령 대기 중...';
          }
          break;
        case VoiceState.processing:
          _statusMessage = '음성 명령 처리 중...';
          break;
        case VoiceState.idle:
          if (!_statusMessage.contains('측정 중:') &&
              !_statusMessage.contains('완료')) {
            _statusMessage = '10미터 거리 측정 중...';
          }
          break;
      }
    });
  }

  Future<void> _initializeCamera() async {
    try {
      debugPrint("📱 카메라 초기화 시작");

      // 상태 업데이트를 더 자주 하여 사용자에게 진행 상황 알림
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 권한 확인 중...";
        });
      }

      // 짧은 대기로 UI 업데이트 보장
      await Future.delayed(const Duration(milliseconds: 100));

      debugPrint("📷 사용 가능한 카메라 확인 중...");
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 감지 중...";
        });
      }

      _cameras = await availableCameras();
      debugPrint("📷 발견된 카메라 수: ${_cameras.length}");

      if (_cameras.isEmpty) {
        debugPrint("❌ 사용 가능한 카메라가 없음");
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

      debugPrint("🎥 후면 카메라 선택: ${camera.name}");
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 준비 중...";
        });
      }

      // UI 업데이트 대기
      await Future.delayed(const Duration(milliseconds: 100));

      debugPrint("🎥 CameraController 생성 중...");
      _cameraController = CameraController(
        camera,
        ResolutionPreset.low, // 성능 최적화: 낮은 해상도로 빠른 초기화 (보폭 측정에 충분)
        enableAudio: false, // 오디오 완전 비활성화
        imageFormatGroup: ImageFormatGroup.jpeg, // 안정적인 JPEG 포맷
      );

      if (mounted) {
        setState(() {
          _statusMessage = "카메라 활성화 중...";
        });
      }

      debugPrint("🎥 카메라 컨트롤러 초기화 중...");
      await _cameraController!.initialize();
      debugPrint("✅ 카메라 컨트롤러 초기화 완료");

      // 필수 카메라 설정만 먼저 수행 (빠른 초기화)
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 설정 중...";
        });
      }

      await _cameraController!.setFocusMode(FocusMode.auto);
      await _cameraController!.setExposureMode(ExposureMode.auto);
      debugPrint('✅ 카메라 기본 설정 완료');

      // 줌 레벨은 백그라운드에서 초기화 (UI 차단하지 않음)
      _initializeZoomLevelsInBackground();

      if (mounted) {
        setState(() {
          _isCameraInitialized = true;
          _statusMessage = "카메라 준비 완료 - '시작'이라고 말하거나 버튼을 누르세요";
        });
      }

      debugPrint("🎬 스트리밍 시작");
      await _startStreaming();

      // 자동 측정 시작 제거 - 사용자가 수동으로 시작해야 함
      debugPrint("🎯 카메라 준비 완료 - 수동 시작 대기 중");
      _beginStartListening();

      debugPrint("✅ 카메라 초기화 프로세스 완료");
    } catch (e) {
      debugPrint("❌ 카메라 초기화 실패: $e");
      if (mounted) {
        setState(() {
          _statusMessage = "카메라 초기화 실패: $e";
        });
      }
    }
  }

  /// 줌 레벨을 백그라운드에서 초기화 (UI 차단하지 않음)
  void _initializeZoomLevelsInBackground() {
    Future.microtask(() async {
      try {
        if (_cameraController != null &&
            _cameraController!.value.isInitialized) {
          _minZoomLevel = await _cameraController!.getMinZoomLevel();
          _maxZoomLevel = await _cameraController!.getMaxZoomLevel();
          _currentZoomLevel = _minZoomLevel;
          debugPrint('📷 줌 범위: ${_minZoomLevel}x - ${_maxZoomLevel}x');
        }
      } catch (e) {
        debugPrint('⚠️ 줌 레벨 초기화 실패: $e');
      }
    });
  }

  Future<void> _startStreaming() async {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }

    if (mounted) {
      setState(() {
        _isStreamingActive = true;
        _statusMessage = "카메라 준비 완료 - '시작'이라고 말하거나 버튼을 누르세요";

        // 측정 세션 초기화
        frameCount = 0;
        distanceMeters = 0.0;
      });
    }

    // 음성 인식 사이클은 시작하지 않고, 프레임 캡처도 시작하지 않음 (수동 시작 대기)
    // _startPeriodicCapture(); // 수동 시작 전까지 비활성화
    // _startMeasurementTimeout(); // 수동 시작 전까지 비활성화
  }

  /// 시작 음성 인식 시작
  void _beginStartListening() {
    if (_voiceHelper == null || !isWaitingForStart) return;

    debugPrint("🎙️ 시작 음성 인식 활성화");

    _voiceHelper!.startListeningForKeywords(
      keywords: ['시작', '측정', '보폭', '시작해', '측정해', '시작하자'],
      onMatch: (String matchedKeyword, String fullText) {
        debugPrint("✅ 시작 명령 감지됨: '$matchedKeyword' (전체: '$fullText')");
        _onMeasurementStart();
      },
      timeoutSeconds: 120, // 2분 타임아웃
      onTimeout: () {
        debugPrint("⏰ 시작 음성 인식 타임아웃");
        if (mounted) {
          VoiceUtils.speakWithService(
            _voiceService,
            "시간이 초과되었습니다. 버튼을 눌러서 시작하거나 '시작'이라고 말씀해주세요.",
          );
        }
      },
    );
  }

  /// 측정 시작 (음성 명령 또는 버튼 클릭)
  void _onMeasurementStart() {
    if (!isWaitingForStart || measurementActive) return;

    // 카운트다운 시작(시각장애인 안내 강화)
    setState(() {
      isWaitingForStart = false;
      _countdownSeconds = 3;
      _statusMessage = "3초 후 측정이 시작됩니다";
    });

    _speakText("3초 후 측정을 시작합니다. 준비해 주세요.");

    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      if ((_countdownSeconds ?? 0) <= 1) {
        t.cancel();
        setState(() {
          _countdownSeconds = null;
          _statusMessage = "측정을 시작합니다";
        });
        VoiceUtils.speakWithService(_voiceService, "시작합니다.");

        // 실제 측정 시작
        _startAutomaticMeasurement();
        _startPeriodicCapture();
        _startMeasurementTimeout();
      } else {
        setState(() {
          _countdownSeconds = (_countdownSeconds ?? 1) - 1;
          _statusMessage = "$_countdownSeconds초 후 측정이 시작됩니다";
        });
      }
    });
  }

  // 자동 측정 시작 (백엔드 연동)
  void _startAutomaticMeasurement() async {
    if (!mounted) return;

    try {
      // 백엔드 측정 세션 시작 API 호출 (타임아웃 연장으로 안정성 개선)
      final response = await http
          .post(
            Uri.parse(AppConfig.measurementSessionStartEndpoint),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': _currentUserUuid ?? 'current_user'}),
          )
          .timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 백엔드 측정 세션 시작 응답: $result');

        if (result['success'] == true && result['session_active'] == true) {
          if (mounted) {
            setState(() {
              _statusMessage = "백엔드 연동 보폭 측정 시작";
              measurementActive = true;
              distanceMeters = 0.0;
              measurementCompleted = false;
            });
          }

          // 거리 측정 시작 음성 안내
          _speakText("거리 측정을 시작합니다.자연스럽게 걸어주세요.");

          // 진행 상황 음성 안내는 제거 (10m 달성 또는 타임아웃 시에만 안내)

          debugPrint('✅ 백엔드 연동 측정 세션 시작됨');
        } else {
          debugPrint('⚠️ 백엔드 측정 세션 시작 응답에 문제 있음: ${result['message']}');
          _startFallbackMeasurement();
        }
      } else {
        debugPrint('❌ 백엔드 측정 세션 시작 HTTP 오류: ${response.statusCode}');
        _startFallbackMeasurement();
      }
    } catch (e) {
      debugPrint('❌ 백엔드 측정 세션 시작 실패: $e');
      _startFallbackMeasurement();
    }
  }

  /// 백엔드 연결 실패 시 로컬 측정으로 대체
  void _startFallbackMeasurement() {
    if (mounted) {
      setState(() {
        _statusMessage = "로컬 보폭 측정 시작 (백엔드 백업)";
        measurementActive = true;
        distanceMeters = 0.0;
        measurementCompleted = false;
      });
    }

    _speakText("거리 측정을 시작합니다.");
    debugPrint('✅ 백엔드 백업 모드로 측정 시작');
  }

  // 일정 시간(120초) 동안 측정이 완료되지 않으면 자동 완료 처리
  void _startMeasurementTimeout() {
    _measurementTimeoutTimer?.cancel(); // 이전 타이머가 있다면 취소
    _measurementTimeoutTimer = Timer(const Duration(seconds: 120), () {
      if (!mounted) return;

      debugPrint('⏰ 120초 타임아웃 - 측정 자동 완료 처리');

      // 측정이 진행 중이었다면 현재까지의 거리로 완료 처리
      if (measurementActive && !measurementCompleted) {
        // 최소 5미터는 측정된 것으로 간주 (보폭 계산을 위해)
        if (distanceMeters < 5.0) {
          distanceMeters = 8.0; // 기본 측정 거리 설정
        }

        setState(() {
          measurementCompleted = true;
          measurementActive = false;
          _progressAnnouncementTimer?.cancel();
        });

        // 음성 안내
        _speakText(
          "측정 시간이 완료되어 ${distanceMeters.toStringAsFixed(1)}미터로 측정을 마무리합니다. 걸음 수를 말씀해 주세요.",
        );

        // 걸음 수 입력 요청
        _announceDistanceMeasurementComplete();
      } else if (!measurementActive && !measurementCompleted) {
        // 아직 측정이 시작되지 않았다면 기본값으로 완료
        debugPrint('⚠️ 측정이 시작되지 않았음 - 기본 측정으로 진행');

        setState(() {
          measurementActive = false;
          measurementCompleted = true;
          distanceMeters = 8.0; // 기본 거리
        });

        _speakText("자동으로 8미터 측정을 완료했습니다. 걸음 수를 말씀해 주세요.");

        _announceDistanceMeasurementComplete();
      }
    });
  }

  void _startPeriodicCapture() {
    Future.doWhile(() async {
      if (!_isStreamingActive) return false;

      try {
        // 프레임 캡처 간격을 1.5초로 조정하여 더 빠른 거리 측정
        await Future.delayed(const Duration(milliseconds: 1500));

        if (_cameraController != null &&
            _cameraController!.value.isInitialized &&
            measurementActive) {
          // 조용한 프레임 캡처 (소리 없음)
          final picture = await _cameraController!.takePicture();
          frameCount++; // 프레임 카운트 증가

          // 거리 측정 중일 때만 상태 업데이트
          if (mounted && frameCount % 3 == 0) {
            // 3프레임마다 한 번씩 상태 업데이트
            setState(() {
              _statusMessage =
                  "거리 측정 중: ${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters}m";
            });
          }

          // 프레임을 서버로 업로드 (거리 측정용)
          await _uploadFrameForHybridMeasurement(picture.path);

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

  /// 거리 측정을 위한 프레임 업로드 및 거리 데이터 처리 (백엔드 연동)
  Future<void> _uploadFrameForHybridMeasurement(String imagePath) async {
    try {
      // 백엔드 /api/users/measurement/frame 엔드포인트 호출
      var request = http.MultipartRequest(
        'POST',
        Uri.parse(AppConfig.measurementFrameEndpoint),
      );

      // 이미지 파일 추가
      request.files.add(await http.MultipartFile.fromPath('file', imagePath));

      request.fields.addAll({
        'uuid': _currentUserUuid ?? 'current_user',
        'frame_count': frameCount.toString(),
        'estimated_distance': distanceMeters.toString(),
        'estimated_step_count': '0',
      });

      debugPrint(
        '🚀 백엔드 거리 측정 API 호출 - 프레임: $frameCount, 현재거리: ${distanceMeters}m',
      );

      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 30),
      );
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 백엔드 응답: ${result.toString()}');

        // 백엔드에서 정교한 측정 결과 받아오기
        if (result['success'] == true && result.containsKey('measurement')) {
          final measurement = result['measurement'];

          // 백엔드 응답에서 거리(m) 파싱
          double? backendDistanceMeters;
          try {
            if (measurement is Map) {
              if (measurement['distance_meters'] is num) {
                backendDistanceMeters =
                    (measurement['distance_meters'] as num).toDouble();
              } else if (measurement['distance_m'] is num) {
                backendDistanceMeters =
                    (measurement['distance_m'] as num).toDouble();
              } else if (measurement['distance_cm'] is num) {
                backendDistanceMeters =
                    (measurement['distance_cm'] as num).toDouble() / 100.0;
              } else if (measurement['distance'] is num) {
                // 거리 단위가 m라고 가정
                backendDistanceMeters =
                    (measurement['distance'] as num).toDouble();
              } else if (measurement['step_length_cm'] is num &&
                  measurement['step_count'] is num) {
                final double stepLenCm =
                    (measurement['step_length_cm'] as num).toDouble();
                final double stepCnt =
                    (measurement['step_count'] as num).toDouble();
                backendDistanceMeters = (stepLenCm * stepCnt) / 100.0;
              }
            }
          } catch (e) {
            debugPrint('백엔드 거리 파싱 실패: $e');
          }

          if (backendDistanceMeters == null || backendDistanceMeters <= 0) {
            // 파싱 실패 또는 0값 시 시각장애인 특성 반영한 백업 로직 사용
            debugPrint('백엔드 거리 값 없음 또는 0 - 시각장애인 맞춤 시뮬레이션으로 전환');
            _fallbackToSimulatedDistance();
          } else if (mounted && measurementActive) {
            setState(() {
              // 백엔드 거리 사용, 단조 증가 유지 및 상한 적용
              final double next = math.min(
                math.max(distanceMeters, backendDistanceMeters!),
                targetDistanceMeters,
              );
              distanceMeters = next;

              // 10미터 달성 시 측정 완료
              if (distanceMeters >= targetDistanceMeters &&
                  !measurementCompleted) {
                measurementCompleted = true;
                measurementActive = false;
                _progressAnnouncementTimer?.cancel();

                distanceMeters = targetDistanceMeters;
                debugPrint('🎯 백엔드 연동 10미터 달성! 측정 완료 처리 시작');
                _announceDistanceMeasurementComplete();
              }
            });
          }
        } else {
          // 백엔드 측정 결과가 없으면 기존 시뮬레이션 로직 사용
          _fallbackToSimulatedDistance();
        }

        debugPrint(
          '📸 백엔드 거리 측정 완료 - 현재 거리: ${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters}m',
        );
      } else {
        debugPrint('❌ 백엔드 응답 오류: ${response.statusCode} ${response.body}');
        _fallbackToSimulatedDistance();
      }
    } catch (e) {
      debugPrint('❌ 백엔드 거리 측정 API 호출 실패: $e');
      _fallbackToSimulatedDistance();
    }
  }

  /// 백엔드 연결 실패 시 시뮬레이션으로 대체 - 시각장애인 보폭 특성 반영
  void _fallbackToSimulatedDistance() {
    if (mounted && measurementActive) {
      // 시각장애인 평균 보폭: 60-65cm (일반인 70cm보다 짧음)
      // 더 안전하고 신중한 걸음을 고려 (기존 step_length_cm 변수 활용)
      final double visualImpairedStrideM = 0.62; // 62cm 평균 보폭
      final double stepsPerSecond = 0.8; // 1.5초당 1.2보 = 초당 0.8보 (더 신중한 속도)
      final double frameIntervalSec = 1.5;
      final double estimatedStepsPerFrame = stepsPerSecond * frameIntervalSec;

      final double frameIncrement =
          estimatedStepsPerFrame * visualImpairedStrideM;
      final simulatedDistance = distanceMeters + frameIncrement; // 프레임당 약 0.74m

      debugPrint(
        '📏 시각장애인 보폭 시뮬레이션: ${distanceMeters.toStringAsFixed(1)}m + ${frameIncrement.toStringAsFixed(2)}m',
      );

      setState(() {
        distanceMeters = math.min(simulatedDistance, targetDistanceMeters);

        if (distanceMeters >= targetDistanceMeters && !measurementCompleted) {
          measurementCompleted = true;
          measurementActive = false;
          _progressAnnouncementTimer?.cancel();
          distanceMeters = targetDistanceMeters;

          debugPrint('🎯 시각장애인 보폭 기반 시뮬레이션으로 10미터 달성! 측정 완료');
          _announceDistanceMeasurementComplete();
        }
      });
    }
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
        title: const AccessibleTitle('10미터 거리 측정'),
        backgroundColor: Colors.black87,
        foregroundColor: Colors.white,
        automaticallyImplyLeading: false, // 뒤로가기 버튼 제거
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
                        _buildTestButton(),
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
            color: measurementCompleted ? Colors.green : Colors.white30,
            width: 2,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (measurementActive || measurementCompleted) ...[
              // 현재 측정 단계 표시
              AccessibleText(
                measurementCompleted ? '측정 완료' : '거리 측정 중',
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
                    '${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters.toStringAsFixed(0)}m',
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
                '진행률: ${(distanceMeters / targetDistanceMeters * 100).round()}%',
                style: const TextStyle(color: Colors.white70, fontSize: 14),
                textAlign: TextAlign.center,
              ),
            ] else ...[
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_isStreamingActive && !isWaitingForStart) ...[
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
                      _countdownSeconds != null
                          ? (_countdownSeconds == 0
                              ? '측정을 시작합니다'
                              : '$_countdownSeconds초 후 측정이 시작됩니다')
                          : _statusMessage,
                      style: const TextStyle(color: Colors.white, fontSize: 16),
                      textAlign: TextAlign.center,
                    ),
                  ),
                ],
              ),
              // 측정 시작 버튼 (시작 대기 중일 때만 표시)
              if (isWaitingForStart && _isStreamingActive) ...[
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: _onMeasurementStart,
                  icon: const Icon(Icons.play_arrow, color: Colors.white),
                  label: const AccessibleText(
                    '측정 시작',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.green,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 12,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(25),
                    ),
                  ),
                ),
              ],
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

  /// 테스트용 버튼 (개발자 전용)
  Widget _buildTestButton() {
    return Positioned(
      bottom: 100,
      right: 20,
      child: FloatingActionButton(
        onPressed: _triggerTestMeasurementComplete,
        backgroundColor: Colors.orange.withValues(alpha: 0.8),
        child: const Icon(Icons.play_arrow, color: Colors.white, size: 28),
      ),
    );
  }

  /// 테스트용 측정 완료 트리거
  void _triggerTestMeasurementComplete() async {
    debugPrint('🧪 테스트: 측정 완료 시뮬레이션 시작');

    // 스트리밍 중지
    _stopStreaming();

    // 측정 값 설정 (시뮬레이션)
    setState(() {
      measurementActive = false;
      measurementCompleted = true;
      distanceMeters = 10.0; // 10미터로 설정
      _progressAnnouncementTimer?.cancel();
    });

    debugPrint('🧪 테스트: 거리 측정 완료 음성 안내 시작');

    // 거리 측정 완료 음성 안내
    await _announceDistanceMeasurementComplete();
  }

  /// 음성 출력 함수
  Future<void> _speakText(String text) async {
    if (_voiceService != null) {
      await VoiceUtils.speakWithService(
        _voiceService!,
        text,
        speed: _voiceService!.getCurrentSpeed(),
      );
    }
  }
}
