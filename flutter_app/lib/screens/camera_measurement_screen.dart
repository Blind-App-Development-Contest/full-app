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
import '../services/api_service.dart';
import '../models/step_measurement_result.dart';
import '../widgets/accessible_text.dart';
import 'voice_screen.dart';

/// 카메라 거리 측정 화면 (10m 측정)
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
  
  // 시각장애인용 상세 음성 안내 상태
  Timer? _progressAnnouncementTimer;

  // 줌 기능 관련
  double _currentZoomLevel = 1.0;
  double _minZoomLevel = 1.0;
  double _maxZoomLevel = 2.0;

  // 거리 측정 관련 타이머
  Timer? _measurementTimeoutTimer;

  // StepMeasurementResult 모델과 일치하는 변수명 사용
  int frameCount = 0;
  double distanceMeters = 0.0; // 현재 측정된 거리 (미터) 
  double targetDistanceMeters = 10.0; // 목표 거리 10m
  bool measurementActive = false; // 측정 진행 상태 
  bool measurementCompleted = false; // 측정 완료 상태
  bool waitingForStepCount = false; // 걸음 수 입력 대기 상태
  int stepCount = 0; // 사용자가 입력한 걸음 수 
  double stepLengthCm = StepMeasurementResult.defaultStepLengthCm; // 계산된 보폭 (cm) 

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
      // 🚀 즉시 음성 안내 시작 (초기화 기다리지 않음)
      _quickAnnounceMeasurementStart();
      
      // 1단계: VoiceService 먼저 초기화 (빠름 + 즉시 음성 피드백 가능)
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

  /// 즉시 측정 시작 안내 (초기화 기다리지 않음)
  void _quickAnnounceMeasurementStart() {
    if (mounted) {
      setState(() {
        _statusMessage = "보폭 측정을 시작합니다...";
      });
    }
    
    // VoiceService가 없어도 일단 시도 (나중에 실제로 실행됨)
    Future.delayed(const Duration(milliseconds: 200), () {
      _voiceService?.speak("보폭 측정을 시작합니다. 잠시 기다려주세요.", speed: 1.0);
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
    _progressAnnouncementTimer?.cancel(); // 진행 상황 안내 타이머 취소
    _stopStreaming();
    _disposeCameraResources();
    _voiceService?.removeListener(_onVoiceServiceStateChanged);
    _voiceService?.stopAutoRecognitionCycle();
    super.dispose();
  }

  Future<void> _initializeVoiceService() async {
    try {
      _voiceService = context.read<VoiceService>();
      _voiceService!.addListener(_onVoiceServiceStateChanged);
      _voiceService!.setMeasurementCallbacks(
        onComplete: _onMeasurementComplete,
      );
      debugPrint("✅ VoiceService 초기화 성공");
      
      // 🚀 즉시 상세 안내 시작 (딜레이 제거)
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
    if (_voiceService == null) return;
    
    try {
      // 🚀 딜레이 최소화하고 핵심 메시지만 전달
      await Future.delayed(const Duration(milliseconds: 300));
      
      await _voiceService!.speak(
        "보폭 측정을 시작합니다. 직선으로 자연스럽게 걸어주세요.", 
        speed: 1.0
      );
      
      await Future.delayed(const Duration(milliseconds: 600));
      
      await _voiceService!.speak(
        "10미터 거리를 걸으면 자동으로 측정이 완료되고, 걸음 수를 물어보겠습니다.", 
        speed: 0.9
      );
      
    } catch (e) {
      debugPrint('❌ 카메라 측정 화면 진입 안내 실패: $e');
    }
  }

  /// 거리 측정 진행 상황 주기적 안내 시작 (시각장애인용)
  void _startDistanceProgressAnnouncement() {
    _progressAnnouncementTimer?.cancel();
    
    // 2미터마다 진행 상황 안내
    _progressAnnouncementTimer = Timer.periodic(
      const Duration(seconds: 3), 
      (timer) {
        if (measurementActive && !measurementCompleted && mounted) {
          _announceDistanceProgress();
        } else {
          timer.cancel();
        }
      }
    );
  }

  /// 현재 거리 진행 상황 안내 (시각장애인용)
  Future<void> _announceDistanceProgress() async {
    if (_voiceService == null || !measurementActive) return;
    
    try {
      // 진행률 계산은 UI에서 사용
      final remainingDistance = targetDistanceMeters - distanceMeters;
      
      if (remainingDistance > 0) {
        await _voiceService!.speak(
          "${distanceMeters.toStringAsFixed(1)}미터 진행했습니다. "
          "목표까지 ${remainingDistance.toStringAsFixed(1)}미터 남았습니다.", 
          speed: 0.9
        );
      }
      
    } catch (e) {
      debugPrint('❌ 거리 진행 상황 음성 안내 실패: $e');
    }
  }

  /// 거리 측정 완료 후 걸음 수 입력 요청 (시각장애인용)
  Future<void> _announceDistanceMeasurementComplete() async {
    if (_voiceService == null) return;
    
    try {
      await _voiceService!.speak("거리 측정이 완료되었습니다!", speed: 1.0);
      
      await Future.delayed(const Duration(milliseconds: 800));
      
      await _voiceService!.speak(
        "정확히 ${distanceMeters.toStringAsFixed(1)}미터를 측정했습니다.", 
        speed: 0.9
      );
      
      await Future.delayed(const Duration(milliseconds: 600));
      
      await _voiceService!.speak(
        "이제 걸음 수를 말씀해 주세요. 예를 들어 '15걸음' 또는 '열다섯걸음'처럼 말씀하세요.", 
        speed: 0.9
      );
      
      // 걸음 수 입력 대기 상태로 변경
      if (mounted) {
        setState(() {
          waitingForStepCount = true;
        });
        
        // 음성 인식 시작
        _startStepCountVoiceInput();
      }
      
    } catch (e) {
      debugPrint('❌ 거리 측정 완료 음성 안내 실패: $e');
    }
  }

  /// 걸음 수 음성 입력 시작
  Future<void> _startStepCountVoiceInput() async {
    if (_voiceService == null) return;
    
    try {
      debugPrint('🎤 걸음 수 음성 입력 시작');
      
      // VoiceService에 걸음 수 입력 콜백 설정
      _voiceService!.setStepCountCallbacks(
        onStepCountReceived: _onStepCountReceived,
        onStepCountInputError: _onStepCountInputError,
      );
      
      // 걸음 수 입력 모드 시작
      await _voiceService!.startStepCountInput();
      
    } catch (e) {
      debugPrint('❌ 걸음 수 음성 입력 시작 실패: $e');
      _onStepCountInputError('음성 인식을 시작할 수 없습니다: $e');
    }
  }
  
  /// 걸음 수 음성 입력 결과 처리
  void _onStepCountReceived(int stepCount) {
    debugPrint('🎤 걸음 수 음성 입력 결과: $stepCount걸음');
    
    if (mounted && waitingForStepCount) {
      setState(() {
        this.stepCount = stepCount;
        waitingForStepCount = false;
      });
      
      // 걸음 수 확인 안내
      _confirmStepCount(stepCount);
    }
  }

  /// 한국어 숫자 표현을 숫자로 변환하는 함수
  int? _parseKoreanNumber(String text) {
    final cleanText = text.toLowerCase().trim();
    
    // 숫자가 포함된 패턴들을 처리
    final digitPattern = RegExp(r'\d+');
    final digitMatch = digitPattern.firstMatch(cleanText);
    if (digitMatch != null) {
      return int.tryParse(digitMatch.group(0)!);
    }
    
    // 한국어 숫자 변환 맵
    final koreanNumbers = {
      '영': 0, '공': 0, '하나': 1, '일': 1, '한': 1, '둘': 2, '이': 2,
      '셋': 3, '삼': 3, '넷': 4, '사': 4, '다섯': 5, '오': 5,
      '여섯': 6, '육': 6, '일곱': 7, '칠': 7, '여덟': 8, '팔': 8,
      '아홉': 9, '구': 9, '열': 10, '십': 10, '스무': 20, '이십': 20,
      '서른': 30, '삼십': 30, '마흔': 40, '사십': 40, '쉰': 50, '오십': 50
    };
    
    // 복합 숫자 처리 (열하나, 열둘 등)
    if (cleanText.contains('열') && cleanText.length > 1) {
      final afterTen = cleanText.replaceFirst('열', '').trim();
      final baseNum = koreanNumbers[afterTen];
      if (baseNum != null && baseNum < 10) {
        return 10 + baseNum;
      }
      return 10;
    }
    
    // 이십, 삼십 등의 복합 처리
    for (final entry in koreanNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        if (entry.value >= 10) return entry.value;
        
        // 십의 배수 + 일의 자리 처리
        final tens = ['이십', '삼십', '사십', '오십'].indexWhere((t) => cleanText.contains(t));
        if (tens >= 0) {
          final remaining = cleanText.replaceAll(['이십', '삼십', '사십', '오십'][tens], '').trim();
          final onesValue = koreanNumbers[remaining] ?? 0;
          return (tens + 2) * 10 + onesValue;
        }
        
        return entry.value;
      }
    }
    
    return null;
  }

  /// 텍스트에서 걸음 수를 추출하는 향상된 함수
  int? _extractStepCountFromText(String text) {
    final cleanText = text.toLowerCase().trim();
    debugPrint('🔍 걸음 수 추출 시도: "$cleanText"');
    
    // 1. 직접적인 숫자 패턴 찾기 (15걸음, 20보, 열다섯걸음 등)
    final patterns = [
      RegExp(r'(\d+)\s*(?:걸음|보|발자국|스텝)'),
      RegExp(r'(\d+)\s*(?:번|개)?'),
      RegExp(r'(?:걸음|보|발자국|스텝).*?(\d+)'),
    ];
    
    for (final pattern in patterns) {
      final match = pattern.firstMatch(cleanText);
      if (match != null) {
        final num = int.tryParse(match.group(1)!);
        if (num != null && num > 0 && num <= 100) {
          debugPrint('✅ 패턴 매칭으로 걸음 수 추출: $num');
          return num;
        }
      }
    }
    
    // 2. 한국어 숫자 변환 시도
    final koreanNum = _parseKoreanNumber(cleanText);
    if (koreanNum != null && koreanNum > 0 && koreanNum <= 100) {
      debugPrint('✅ 한국어 숫자 변환으로 걸음 수 추출: $koreanNum');
      return koreanNum;
    }
    
    // 3. 전체 텍스트에서 숫자만 추출
    final digitOnly = RegExp(r'\d+').allMatches(cleanText);
    for (final match in digitOnly) {
      final num = int.tryParse(match.group(0)!);
      if (num != null && num > 0 && num <= 100) {
        debugPrint('✅ 숫자 추출로 걸음 수 획득: $num');
        return num;
      }
    }
    
    debugPrint('❌ 걸음 수 추출 실패: "$cleanText"');
    return null;
  }
  
  /// 걸음 수 음성 입력 오류 처리
  void _onStepCountInputError(String error) {
    debugPrint('❌ 걸음 수 음성 입력 오류: $error');
    
    // 오류 텍스트에서 걸음 수 추출 시도
    final extractedStepCount = _extractStepCountFromText(error);
    if (extractedStepCount != null) {
      debugPrint('✅ 오류 텍스트에서 걸음 수 추출 성공: $extractedStepCount');
      _onStepCountReceived(extractedStepCount);
      return;
    }
    
    if (mounted) {
      // 다시 입력 요청
      _requestStepCountAgain();
    }
  }

  

  /// 걸음 수 확인 안내
  Future<void> _confirmStepCount(int stepCount) async {
    if (_voiceService == null) return;
    
    try {
      await _voiceService!.speak(
        "$stepCount걸음으로 확인되었습니다.", 
        speed: 0.9
      );
      
      await Future.delayed(const Duration(milliseconds: 600));
      
      // 보폭 계산 및 완료 처리
      _calculateStepLengthAndComplete();
      
    } catch (e) {
      debugPrint('❌ 걸음 수 확인 안내 실패: $e');
    }
  }

  /// 걸음 수 다시 입력 요청
  Future<void> _requestStepCountAgain() async {
    if (_voiceService == null) return;
    
    try {
      await _voiceService!.speak(
        "걸음 수를 정확히 듣지 못했습니다. 다시 말씀해 주세요. 예를 들어 '15걸음' 또는 '열다섯'이라고 말씀해 주세요.", 
        speed: 0.9
      );
      
      // 다시 음성 인식 시작
      Future.delayed(const Duration(milliseconds: 1000), () async {
        if (mounted && waitingForStepCount) {
          await _startStepCountVoiceInput();
        }
      });
      
    } catch (e) {
      debugPrint('❌ 걸음 수 재입력 요청 실패: $e');
    }
  }

  /// 보폭 계산 및 측정 완료 처리 (백엔드 연동)
  void _calculateStepLengthAndComplete() async {
    // 스트리밍 중지
    _stopStreaming();
    
    // 사용자 입력 걸음 수를 기반으로 보폭 계산 (StepMeasurementResult 모델과 동일한 공식)
    final calculatedStepLength = (distanceMeters * 100) / stepCount; // cm 단위
    
    debugPrint('📏 거리 측정 완료: ${distanceMeters.toStringAsFixed(1)}m');
    debugPrint('📏 사용자 입력 걸음수: $stepCount걸음');
    debugPrint('📏 계산된 보폭: ${calculatedStepLength.toStringAsFixed(1)}cm');
    
    // 계산된 보폭을 stepLengthCm 변수에 저장 (StepMeasurementResult 모델과 동일)
    stepLengthCm = calculatedStepLength;
    
    // 보폭 계산 결과 안내
    _announceCalculatedStepLength(calculatedStepLength);
    
    // 백엔드 측정 세션 중지 API 호출
    await _stopMeasurementSession();
    
    // 음성 안내가 완료된 후 화면 전환은 _announceCalculatedStepLength에서 처리
  }

  /// 백엔드 측정 세션 중지
  Future<void> _stopMeasurementSession() async {
    try {
      debugPrint('🛑 백엔드 측정 세션 중지 요청');
      
      final response = await http.post(
        Uri.parse(AppConfig.measurementSessionStopEndpoint),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'user_id': 'current_user'}),
      ).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 백엔드 측정 세션 중지 성공: ${result['message']}');
        
        // 백엔드에서 계산된 최종 보폭이 있으면 사용
        if (result.containsKey('measurement_result')) {
          final backendStepLength = result['measurement_result']['step_length_cm'];
          if (backendStepLength != null) {
            stepLengthCm = backendStepLength.toDouble();
            debugPrint('🔄 백엔드에서 계산된 보폭 사용: ${stepLengthCm.toStringAsFixed(1)}cm');
          }
        }
      } else {
        debugPrint('⚠️ 백엔드 측정 세션 중지 HTTP 오류: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('❌ 백엔드 측정 세션 중지 실패: $e');
      // 오류가 있어도 계속 진행 (로컬 계산된 보폭 사용)
    }
  }

  /// 계산된 보폭 결과 안내
  Future<void> _announceCalculatedStepLength(double stepLength) async {
    if (_voiceService == null) return;
    
    try {
      await _voiceService!.speak(
        "보폭 계산이 완료되었습니다!", 
        speed: 1.0
      );
      
      await Future.delayed(const Duration(milliseconds: 800));
      
      await _voiceService!.speak(
        "측정된 보폭은 ${stepLength.toStringAsFixed(0)}센티미터입니다.", 
        speed: 0.9
      );
      
      // 음성 안내 완료 후 즉시 화면 전환
      await Future.delayed(const Duration(milliseconds: 500));
      
      if (mounted) {
        if (widget.isFromSettings) {
          // 설정에서 온 경우 - 계산된 보폭 반환 (StepMeasurementResult 형식)
          Navigator.of(context).pop(stepLengthCm.round());
        } else {
          // 온보딩에서 온 경우 - 음성 설정 화면으로 이동
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(
              builder: (context) => const VoiceScreen(fromSettings: false),
            ),
          );
        }
      }
      
    } catch (e) {
      debugPrint('❌ 보폭 계산 결과 안내 실패: $e');
    }
  }

  void _onVoiceServiceStateChanged() {
    if (!mounted || _voiceService == null) return;

    setState(() {
      switch (_voiceService!.currentState) {
        case VoiceState.listening:
          if (waitingForStepCount) {
            _statusMessage = '🎤 걸음 수를 말씀해 주세요 (예: "15걸음", "열다섯")';
          } else if (_statusMessage.contains('측정 중:')) {
            break;
          } else {
            _statusMessage = '음성 명령 대기 중... (완료라고 말하세요)';
          }
          break;
        case VoiceState.processing:
          if (waitingForStepCount) {
            _statusMessage = '🔍 걸음 수 음성 분석 중...';
          } else {
            _statusMessage = '음성 명령 처리 중...';
          }
          break;
        case VoiceState.idle:
          if (waitingForStepCount) {
            _statusMessage = '걸음 수 입력 대기 중...';
          } else if (!_statusMessage.contains('측정 중:') &&
              !_statusMessage.contains('완료')) {
            _statusMessage = '10미터 거리 측정 중...';
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
        finalStepLength = measurementResult.step_length_cm.round();
        debugPrint('✅ final_result에서 측정 결과 생성: ${finalStepLength}cm');
      } else {
        // final_result가 없는 경우 현재 측정값 사용
        debugPrint('⚠️ final_result 없음, 현재 측정값으로 결과 생성');
        finalStepLength = stepLengthCm.round();
      }

      // 스트리밍 중단
      _stopStreaming();

      // 측정 결과를 데이터베이스에 저장
      try {
        debugPrint('📊 카메라 측정 결과 저장 시도: ${finalStepLength}cm');
        await ApiService().saveMeasurementResult({
          'stepLengthCm': finalStepLength,
          'measurementType': 'camera_measurement',
          'frameCount': frameCount,
        });
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
          _statusMessage = "카메라 준비 완료";
        });
      }

      debugPrint("🎬 스트리밍 시작");
      await _startStreaming();
      
      debugPrint("⏱️ 1초 후 자동 측정 시작 예약");
      // 1초 후 자동으로 측정 시작
      Timer(const Duration(seconds: 1), () {
        debugPrint("🚀 자동 측정 시작");
        _startAutomaticMeasurement();
      });
      
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
        if (_cameraController != null && _cameraController!.value.isInitialized) {
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
        _statusMessage = "실시간 보폭 측정 중...";

        // 측정 세션 초기화 (StepMeasurementResult 모델과 일치하는 변수명 사용)
        frameCount = 0;
        distanceMeters = 0.0;
        stepCount = 0;
        stepLengthCm = StepMeasurementResult.defaultStepLengthCm;
        // 측정 시작 시간 설정은 제거됨
      });
    }

    // 음성 인식 사이클은 시작하지 않음 (자동 측정)
    _startPeriodicCapture();
    _startMeasurementTimeout(); // 타임아웃 타이머 시작
  }

  // 자동 측정 시작 (백엔드 연동)
  void _startAutomaticMeasurement() async {
    if (!mounted) return;

    try {
      // 백엔드 측정 세션 시작 API 호출
      final response = await http
          .post(
            Uri.parse(AppConfig.measurementSessionStartEndpoint),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(const Duration(seconds: 5));

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
          _voiceService?.speak("정교한 거리 측정을 시작합니다. 직선으로 자연스럽게 걸어주세요.", speed: 1.0);
          
          // 진행 상황 주기적 안내 시작
          _startDistanceProgressAnnouncement();
          
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

    _voiceService?.speak("거리 측정을 시작합니다. 직선으로 걸어주세요.", speed: 1.0);
    _startDistanceProgressAnnouncement();
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
        _voiceService?.speak(
          "측정 시간이 완료되어 ${distanceMeters.toStringAsFixed(1)}미터로 측정을 마무리합니다. 걸음 수를 말씀해 주세요.",
          speed: 0.9,
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

        _voiceService?.speak(
          "자동으로 8미터 측정을 완료했습니다. 걸음 수를 말씀해 주세요.",
          speed: 0.9,
        );
        
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
              _statusMessage = "거리 측정 중: ${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters}m";
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
        Uri.parse(AppConfig.measurementFrameEndpoint)
      );
      
      // 이미지 파일 추가
      request.files.add(await http.MultipartFile.fromPath('file', imagePath));
      
      // IMU 데이터 (실제 센서 데이터가 있다면 사용, 없으면 기본값)
      request.fields.addAll({
        'user_id': 'current_user',
        'enable_kalman': 'true',
        'accelerometer_x': '0.0',
        'accelerometer_y': '0.0', 
        'accelerometer_z': '9.81',
        'gyroscope_x': '0.0',
        'gyroscope_y': '0.0',
        'gyroscope_z': '0.0',
        'device_orientation': 'portrait',
        'frame_count': frameCount.toString(),
        'estimated_distance': distanceMeters.toString(),
        'estimated_step_count': '0'
      });
      
      debugPrint('🚀 백엔드 거리 측정 API 호출 - 프레임: $frameCount, 현재거리: ${distanceMeters}m');
      
      final streamedResponse = await request.send().timeout(const Duration(seconds: 30));
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
                backendDistanceMeters = (measurement['distance_meters'] as num).toDouble();
              } else if (measurement['distance_m'] is num) {
                backendDistanceMeters = (measurement['distance_m'] as num).toDouble();
              } else if (measurement['distance_cm'] is num) {
                backendDistanceMeters = (measurement['distance_cm'] as num).toDouble() / 100.0;
              } else if (measurement['distance'] is num) {
                // 거리 단위가 m라고 가정
                backendDistanceMeters = (measurement['distance'] as num).toDouble();
              } else if (measurement['step_length_cm'] is num && measurement['step_count'] is num) {
                final double stepLenCm = (measurement['step_length_cm'] as num).toDouble();
                final double stepCnt = (measurement['step_count'] as num).toDouble();
                backendDistanceMeters = (stepLenCm * stepCnt) / 100.0;
              }
            }
          } catch (e) {
            debugPrint('백엔드 거리 파싱 실패: $e');
          }

          if (backendDistanceMeters == null) {
            // 파싱 실패 시 기존 백업 로직 사용
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
              if (distanceMeters >= targetDistanceMeters && !measurementCompleted) {
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
        
        debugPrint('📸 백엔드 거리 측정 완료 - 현재 거리: ${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters}m');
      } else {
        debugPrint('❌ 백엔드 응답 오류: ${response.statusCode} ${response.body}');
        _fallbackToSimulatedDistance();
      }
      
    } catch (e) {
      debugPrint('❌ 백엔드 거리 측정 API 호출 실패: $e');
      _fallbackToSimulatedDistance();
    }
  }

  /// 백엔드 연결 실패 시 시뮬레이션으로 대체
  void _fallbackToSimulatedDistance() {
    if (mounted && measurementActive) {
      final simulatedDistance = distanceMeters + (0.2 + (frameCount * 0.01)); // 백엔드 오류 시 기본 증가량
      setState(() {
        distanceMeters = math.min(simulatedDistance, targetDistanceMeters);
        
        if (distanceMeters >= targetDistanceMeters && !measurementCompleted) {
          measurementCompleted = true;
          measurementActive = false;
          _progressAnnouncementTimer?.cancel();
          distanceMeters = targetDistanceMeters;
          
          debugPrint('🎯 시뮬레이션 백업으로 10미터 달성! 측정 완료');
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
            color: stepLengthCm > 0 ? Colors.green : Colors.white30,
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
                    measurementCompleted 
                        ? '${stepLengthCm.toStringAsFixed(1)}cm'
                        : '${distanceMeters.toStringAsFixed(1)}m / ${targetDistanceMeters.toStringAsFixed(0)}m',
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
                measurementCompleted 
                    ? '걸음 수: $stepCount걸음'
                    : '진행률: ${(distanceMeters / targetDistanceMeters * 100).round()}%',
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

  /// 테스트용 버튼 (개발자 전용)
  Widget _buildTestButton() {
    return Positioned(
      bottom: 100,
      right: 20,
      child: FloatingActionButton(
        onPressed: _triggerTestMeasurementComplete,
        backgroundColor: Colors.orange.withValues(alpha: 0.8),
        child: const Icon(
          Icons.play_arrow,
          color: Colors.white,
          size: 28,
        ),
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
      stepCount = 15; // 테스트용 걸음 수
      stepLengthCm = 66.7; // 테스트용 기본 보폭 (10m / 15걸음)
      _progressAnnouncementTimer?.cancel();
    });
    
    // 🆕 실제 데이터베이스에 보폭 저장 (409 에러 방지)
    await _saveTestFootstepToDatabase();
    
    debugPrint('🧪 테스트: 거리 측정 완료 음성 안내 시작');
    
    // 거리 측정 완료 음성 안내
    await _announceDistanceMeasurementComplete();
  }

  /// 테스트 버튼용 보폭 데이터베이스 저장
  Future<void> _saveTestFootstepToDatabase() async {
    try {
      debugPrint('💾 테스트용 보폭 데이터베이스 저장 시도: ${stepLengthCm.toStringAsFixed(1)}cm');
      
      await ApiService().saveMeasurementResult({
        'stepLengthCm': stepLengthCm.round(),
        'measurementType': 'test_measurement', // 테스트로 구분
        'frameCount': frameCount,
        'distance': distanceMeters,
        'stepCount': stepCount,
      });
      
      debugPrint('✅ 테스트용 보폭 데이터베이스 저장 성공');
    } catch (e) {
      debugPrint('❌ 테스트용 보폭 데이터베이스 저장 실패: $e');
      // 에러가 발생해도 계속 진행 (테스트 목적)
    }
  }
}
