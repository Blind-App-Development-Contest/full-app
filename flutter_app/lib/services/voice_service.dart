import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;
import 'package:just_audio/just_audio.dart';
import 'package:http_parser/http_parser.dart';
import 'package:sensors_plus/sensors_plus.dart';
import 'api_service.dart';

/// 음성 인식 상태

enum VoiceState { idle, listening, processing }

class VoiceService with ChangeNotifier {
  final AudioRecorder _audioRecorder = AudioRecorder();
  // AudioPlayer 싱글톤 관리 클래스
  static final _AudioPlayerManager _playerManager = _AudioPlayerManager();
  AudioPlayer get _audioPlayer => _playerManager.player;

  // --- http.Client를 멤버 변수로 선언하여 재사용 ---
  final http.Client _httpClient = http.Client();

  // === 서버 설정 ===
  // String get baseUrl => dotenv.env['BACKEND_BASE_URL'] ?? 'http://localhost:8000';
String get baseUrl => dotenv.env['BACKEND_BASE_URL'] ?? 'https://aeye-gvu9.onrender.com';

  // === 상태 관리 ===
  VoiceState _currentState = VoiceState.idle;
  String _lastRecognizedText = "";
  String _statusMessage = "초기화 중...";
  final List<String> _debugLogs = [];

  // === 녹음 관련 ===
  String? _currentRecordingPath;

  // === 자동 인식 사이클 제어 ===
  bool _isCycleRunning = false;

  // === TTS 구독 관리 ===
  StreamSubscription? _ttsSubscription;
  bool _isSpeaking = false; // 현재 음성 출력 중인지 확인

  // === Measurement Callbacks ===
  Function(Map<String, dynamic>)? onMeasurementComplete;
  Function(Map<String, dynamic>)? onMeasurementStart;
  
  // === IMU 기반 거리 측정 + 걸음수 입력 ===
  bool _isAwaitingStepCount = false;
  int? _userCountedSteps;
  DateTime? _measurementStartTime;
  
  // === 걸음 수 입력 전용 콜백 ===
  Function(int)? onStepCountReceived;
  Function(String)? onStepCountInputError;

  // IMU 센서 데이터
  double _totalDistance = 0.0;
  final List<double> _accelerationHistory = [];
  Timer? _sensorTimer;
  
  // 실제 IMU 센서 스트림 구독
  StreamSubscription<AccelerometerEvent>? _accelerometerSubscription;
  StreamSubscription<GyroscopeEvent>? _gyroscopeSubscription;
  
  // IMU 데이터 처리용 변수들
  final List<double> _velocityHistory = [];
  double _currentVelocity = 0.0;
  DateTime? _lastSensorUpdate;
  
  // 걸음 감지용 변수들
  int _detectedSteps = 0;
  double _lastPeakTime = 0.0;
  final double _stepThreshold = 12.0; // 걸음 감지 임계값

  // === 음성 속도 설정 ===
  double? _currentVoiceSpeed; // 사용자가 설정한 음성 속도
  static const double _defaultSpeed = 0.9; // 기본 속도 (사용자 설정 전)

  // === Getters ===
  VoiceState get currentState => _currentState;
  String get lastRecognizedText => _lastRecognizedText;
  String get statusMessage => _statusMessage;
  List<String> get debugLogs => _debugLogs;

  /// 현재 음성 속도 반환
  /// 사용자가 설정한 속도가 있으면 해당 속도, 없으면 기본 속도 0.9 반환
  double getCurrentSpeed() {
    return _currentVoiceSpeed ?? _defaultSpeed;
  }

  /// 음성 속도 설정 (사용자가 VoiceScreen에서 설정)
  void setVoiceSpeed(double speed) {
    _currentVoiceSpeed = speed;
    debugPrint('🔊 음성 속도 설정됨: ${speed}x');
  }

  /// 서비스 초기화 및 환경 체크
  Future<void> _initialize() async {
    _addDebugLog("=== VoiceService 초기화 시작 ===");

    // 마이크 권한 확인
    await _checkMicrophonePermission();
    
    // 사용자 설정 로드
    await _loadUserSettings();

    _setStatus("초기화 완료 - 음성 인식 및 출력 준비됨");
    _addDebugLog("=== 초기화 완료 ===");
  }

  /// 마이크 권한 확인
  Future<void> _checkMicrophonePermission() async {
    _addDebugLog("2. 마이크 권한 확인 중...");

    final hasPermission = await _audioRecorder.hasPermission();
    if (hasPermission) {
      _addDebugLog("✅ 마이크 권한 허용됨");
    } else {
      _addDebugLog("❌ 마이크 권한 없음 - 권한 요청 필요");
    }
  }

  /// 자동 인식 사이클 시작
  Future<void> startAutoRecognitionCycle() async {
    if (_isCycleRunning) {
      _addDebugLog("🔄 자동 인식 사이클이 이미 실행중입니다");
      return; // 이미 실행중이면 무시
    }

    _addDebugLog("🎙️ 자동 인식 사이클 시작 요청");

    // 1. 마이크 권한 확인
    final hasPermission = await _audioRecorder.hasPermission();
    if (!hasPermission) {
      _addDebugLog("❌ 마이크 권한 없음 - 자동 인식 시작 할 수 없음");
      _setStatus("마이크 권한이 필요합니다");
      return;
    }
    _addDebugLog(" 마이크 권한 허용됨");

    _isCycleRunning = true;
    _setStatus("자동 인식 사이클 시작");
    _runSingleRecognition();
  }

  /// 자동 인식 사이클 중단
  void stopAutoRecognitionCycle() {
    if (!_isCycleRunning) return;
    _isCycleRunning = false;
    forceStop(); // 현재 진행 중인 녹음/처리 강제 중단
    _setStatus("자동 인식 사이클 중단");
    _addDebugLog("자동 인식 사이클 중단됨");
  }

  /// 자동 인식 사이클 1회를 실행하는 내부 함수
  Future<void> _runSingleRecognition() async {
    // 사이클 실행 플래그가 꺼지면 모든 동작 중단
    if (!_isCycleRunning) return;

    // 기존 녹음 시작 함수 호출(타임아웃 20초 걸어놧음)
    await startListening();
  }

  /// 자동 인식 사이클 내부 단일 인식 실행

  /// 음성 녹음 시작
  Future<void> startListening() async {
    if (_currentState != VoiceState.idle) return;

    _addDebugLog("\n=== 음성 녹음 시작 ===");

    // 사전 검증
    if (!(await _audioRecorder.hasPermission())) {
      _setStatus("마이크 권한이 필요합니다");
      _addDebugLog("❌ 마이크 권한 없음");
      return;
    }

    try {
      // 녹음 파일 경로 설정
      final directory = await getApplicationDocumentsDirectory();
      final timestamp = DateTime.now().millisecondsSinceEpoch;
      _currentRecordingPath = '${directory.path}/voice_test_$timestamp.m4a';

      _addDebugLog("녹음 파일 경로: $_currentRecordingPath");

      _addDebugLog("녹음 설정: AAC-LC, 128kbps, 44.1kHz");

      // 녹음 시작
      await _audioRecorder.start(const RecordConfig(), path: _currentRecordingPath!);

      _setState(VoiceState.listening);
      _setStatus("녹음 중... (최대 20초)");
      _addDebugLog("녹음 시작됨");

      // 3초 타임아웃으로 더 단축 (빠른 응답)
      Future.delayed(const Duration(seconds: 3), () {
        if (_currentState == VoiceState.listening) {
          stopListeningAndProcess();
        }
      });
    } catch (e) {
      _setStatus("녹음 시작 실패: $e");
      _addDebugLog("❌ 녹음 시작 오류: $e");
      _setState(VoiceState.idle);
    }
  }

  /// 음성 녹음 중단 및 OpenAI 처리
  Future<void> stopListeningAndProcess() async {
    if (_currentState != VoiceState.listening) return;

    _addDebugLog("\n=== 음성 처리 시작 ===");

    try {
      // 녹음 중단
      final path = await _audioRecorder.stop();
      if (path == null) {
        _addDebugLog("❌ 녹음 파일 경로가 null");
        _setStatus("녹음 파일을 찾을 수 없습니다");
        _setState(VoiceState.idle);
        return;
      }

      _setState(VoiceState.processing);
      // 1. STT 서버 호출하여 텍스트 얻기 (재시도 로직 포함)
      _setStatus("음성을 텍스트로 변환 중...");
      final sttResult = await _convertSpeechToTextWithRetry(path);
      final String transcribedText = sttResult['text'] ?? '';

      if (transcribedText.isEmpty) {
        _addDebugLog("❌ STT 실패 또는 빈 텍스트 수신");
        _setStatus("음성 인식 실패");
        _setState(VoiceState.idle);
        return;
      }
      _lastRecognizedText = transcribedText;
      _addDebugLog(
        "✅ STT 성공: '$transcribedText' (길이: ${transcribedText.length})",
      );

      // 걸음 수 입력 모드인지 확인
      if (_isAwaitingStepCount) {
        _processStepCountInput(transcribedText);
        return;
      }

      // 2. NLU 서버 호출하여 의도 분석
      _setStatus("의도 분석 중...");
      final nluResult = await _getIntentFromText(transcribedText);
      final String intent = nluResult['intent'] ?? 'unknown';

      _addDebugLog("NLU 성공: 의도='$intent', 엔티티='${nluResult['entities']}'");
      _setStatus("분석된 명령: $intent");

      // 3. 의도에 따른 동작 수행
      await _executeCommand(intent, nluResult['entities']);
    } catch (e) {
      _addDebugLog("❌ 음성 처리 오류: $e");
      _setStatus("음성 처리 중 오류 발생");
    } finally {
      _setState(VoiceState.idle);

      if (_isCycleRunning) {
        // 자동 인식 사이클이 활성화 상태일 때, 0.5초 후 다음 인식 시작 (더 빠른 응답)
        Future.delayed(const Duration(milliseconds: 500), () {
          _runSingleRecognition();
        });
      }
    }
  }

  // 생성자 - NavigatorKey는 더 이상 사용하지 않음 (StepScreen에서 직접 카메라 관리)
  VoiceService({GlobalKey<NavigatorState>? navigatorKey}) {
    _initialize();
  }

  /// 측정 콜백 설정 메서드
  void setMeasurementCallbacks({
    Function(Map<String, dynamic>)? onStart,
    Function(Map<String, dynamic>)? onComplete,
  }) {
    onMeasurementStart = onStart;
    onMeasurementComplete = onComplete;
    _addDebugLog('측정 콜백이 설정되었습니다.');
  }
  
  /// 걸음 수 입력 콜백 설정
  void setStepCountCallbacks({
    Function(int)? onStepCountReceived,
    Function(String)? onStepCountInputError,
  }) {
    this.onStepCountReceived = onStepCountReceived;
    this.onStepCountInputError = onStepCountInputError;
    _addDebugLog('걸음 수 입력 콜백이 설정되었습니다.');
  }
  
  /// 걸음 수 입력 모드 시작
  Future<void> startStepCountInput() async {
    _isAwaitingStepCount = true;
    _addDebugLog("🎤 걸음 수 입력 모드 시작");
    
    try {
      await startListening();
    } catch (e) {
      _addDebugLog("❌ 걸음 수 입력 시작 실패: $e");
      onStepCountInputError?.call("음성 인식을 시작할 수 없습니다: $e");
      _isAwaitingStepCount = false;
    }
  }
  
  /// 걸음 수 입력 처리
  void _processStepCountInput(String transcribedText) {
    _addDebugLog("🎤 걸음 수 입력 처리: '$transcribedText'");
    
    try {
      // 숫자 추출 시도
      final stepCount = _extractStepCountFromSpeech(transcribedText);
      
      if (stepCount > 0) {
        _addDebugLog("✅ 걸음 수 인식 성공: $stepCount걸음");
        _userCountedSteps = stepCount;
        _isAwaitingStepCount = false;
        _setState(VoiceState.idle);
        
        // 콜백 호출
        onStepCountReceived?.call(stepCount);
      } else {
        _addDebugLog("❌ 걸음 수 인식 실패: 숫자를 찾을 수 없음");
        _setState(VoiceState.idle);
        onStepCountInputError?.call("걸음 수를 정확히 듣지 못했습니다. 다시 말씀해 주세요.");
      }
    } catch (e) {
      _addDebugLog("❌ 걸음 수 처리 오류: $e");
      _isAwaitingStepCount = false;
      _setState(VoiceState.idle);
      onStepCountInputError?.call("걸음 수 처리 중 오류가 발생했습니다: $e");
    }
  }
  
  /// 음성에서 걸음 수 추출 (강화된 버전)
  int _extractStepCountFromSpeech(String speech) {
    final cleanText = speech.toLowerCase().trim();
    _addDebugLog('🔍 걸음 수 추출 시도: "$cleanText"');
    
    // 확장된 한국어 숫자 매핑
    final koreanNumbers = {
      '영': 0, '공': 0, '하나': 1, '일': 1, '한': 1, '둘': 2, '이': 2,
      '셋': 3, '삼': 3, '넷': 4, '사': 4, '다섯': 5, '오': 5,
      '여섯': 6, '육': 6, '일곱': 7, '칠': 7, '여덟': 8, '팔': 8,
      '아홉': 9, '구': 9, '열': 10, '십': 10, '스무': 20, '이십': 20,
      '서른': 30, '삼십': 30, '마흔': 40, '사십': 40, '쉰': 50, '오십': 50
    };
    
    // 복합 숫자 매핑 (자주 사용되는 것들)
    final compositeNumbers = {
      '열하나': 11, '열한': 11, '열둘': 12, '열두': 12, '열셋': 13, '열세': 13,
      '열넷': 14, '열네': 14, '열다섯': 15, '열여섯': 16, '열일곱': 17,
      '열여덟': 18, '열아홉': 19, '스물하나': 21, '스물한': 21, '스물둘': 22,
      '스물두': 22, '스물셋': 23, '스물세': 23, '스물넷': 24, '스물네': 24,
      '스물다섯': 25
    };
    
    // 1. 직접적인 숫자 패턴 찾기 (15걸음, 20보 등)
    final patterns = [
      RegExp(r'(\d+)\s*(?:걸음|보|발자국|스텝|개|번|회)'),
      RegExp(r'(\d+)\s*(?:번|개)?'),
      RegExp(r'(?:걸음|보|발자국|스텝).*?(\d+)'),
    ];
    
    for (final pattern in patterns) {
      final match = pattern.firstMatch(cleanText);
      if (match != null) {
        final num = int.tryParse(match.group(1)!);
        if (num != null && num > 0 && num <= 100) {
          _addDebugLog('✅ 패턴 매칭으로 걸음 수 추출: $num');
          return num;
        }
      }
    }
    
    // 2. 복합 한국어 숫자 변환 시도 (우선순위 높음)
    for (final entry in compositeNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        _addDebugLog('✅ 복합 한국어 숫자 변환으로 걸음 수 추출: ${entry.value}');
        return entry.value;
      }
    }
    
    // 3. 기본 한국어 숫자 변환 시도
    if (cleanText.contains('열') && cleanText.length > 1) {
      // 열 + 숫자 조합 처리
      final afterTen = cleanText.replaceFirst('열', '').trim();
      final baseNum = koreanNumbers[afterTen];
      if (baseNum != null && baseNum < 10) {
        _addDebugLog('✅ 열+숫자 조합으로 걸음 수 추출: ${10 + baseNum}');
        return 10 + baseNum;
      }
      _addDebugLog('✅ 열로 걸음 수 추출: 10');
      return 10;
    }
    
    for (final entry in koreanNumbers.entries) {
      if (cleanText.contains(entry.key)) {
        _addDebugLog('✅ 기본 한국어 숫자 변환으로 걸음 수 추출: ${entry.value}');
        return entry.value;
      }
    }
    
    // 4. 전체 텍스트에서 숫자만 추출
    final digitOnly = RegExp(r'\d+').allMatches(cleanText);
    for (final match in digitOnly) {
      final num = int.tryParse(match.group(0)!);
      if (num != null && num > 0 && num <= 100) {
        _addDebugLog('✅ 숫자 추출로 걸음 수 획득: $num');
        return num;
      }
    }
    
    _addDebugLog('❌ 걸음 수 추출 실패: "$cleanText"');
    return 0;
  }

  Future<void> _executeCommand(
    String command,
    Map<String, dynamic> entities,
  ) async {
    _addDebugLog("🎯 인식된 명령: $command, 엔티티: $entities");
    _setStatus("명령 실행: $command");

    // 보폭 측정 관련 명령들 상세 로깅
    final stepMeasureCommands = [
      'MEASURE_STEP',
      'BEGIN_WALKING',
      'FOOTSTEP_MEASUREMENT_START',
      'FOOTSTEP_MEASUREMENT_BEGIN',
    ];
    if (stepMeasureCommands.contains(command)) {
      _addDebugLog("🚶‍♂️ 보폭 측정 명령 감지됨: $command");
    }

    switch (command) {
      case 'MEASURE_STEP':
      case 'BEGIN_WALKING':
      case 'FOOTSTEP_MEASUREMENT_START':
      case 'FOOTSTEP_MEASUREMENT_BEGIN':
        _setStatus("보폭 측정을 시작하겠습니다");
        // 개선된 10m 측정 방식 안내
        await speak("보폭 측정을 시작합니다. 10미터를 직선으로 걸으면서 걸음수를 세어주세요.", speed: 1.0);
        await speak("측정을 시작하려면 '시작'이라고 말씀하세요.", speed: 1.0);
        _setStatus("측정 시작 대기 중...");
        break;
      case 'START':
      case 'START_WALKING':
        if (!_isAwaitingStepCount) {
          await _start10mMeasurement();
        }
        break;
      case 'FOOTSTEP_MEASUREMENT_COMPLETE':
      case 'STOP_MEASUREMENT':
      case 'FINISH_MEASURING':
      case 'END_WALKING':
      case 'MEASUREMENT_COMPLETE':
        if (_isAwaitingStepCount) {
          await speak("먼저 걸음수를 말씀해주세요.", speed: 1.0);
        } else {
          await speak("현재 진행 중인 측정이 없습니다.", speed: 1.0);
        }
        break;
      case 'STOP_LISTENING':
      case 'FOOTSTEP_MEASUREMENT_CANCEL':
        _setStatus("측정을 중단하겠습니다");
        _isAwaitingStepCount = false;
        _userCountedSteps = null;
        _measurementStartTime = null;
        stopAutoRecognitionCycle();
        speak("측정을 중단하겠습니다.", speed: 1.2);
        break;
      default:
        // 걸음수 입력 대기 중인지 확인
        if (_isAwaitingStepCount) {
          final stepCount = _extractStepCountFromText(_lastRecognizedText);
          if (stepCount != null && stepCount > 0) {
            _userCountedSteps = stepCount;
            _isAwaitingStepCount = false;
            await _complete10mMeasurement();
            break;
          } else {
            await speak("걸음수를 다시 말씀해주세요. 예: 열 걸음, 15걸음", speed: 1.0);
            break;
          }
        }
        _setStatus("알 수 없는 명령: $command");
        _addDebugLog('알 수 없는 명령: $command');
        break;
    }
  }

  // 기존 측정 관련 메서드들은 10m 측정으로 대체됨

  /// IMU + 카메라 융합 측정 시작 (최고 정확도)
  Future<void> _start10mMeasurement() async {
    try {
      _measurementStartTime = DateTime.now();
      _setStatus("IMU + 카메라 융합 보폭 측정을 시작합니다");
      
      await speak("IMU 센서와 카메라를 함께 사용한 정밀 보폭 측정을 시작합니다.", speed: 1.0);
      await speak("휴대폰을 손에 들고 직선으로 걸으면서 걸음수를 세어주세요.", speed: 1.0);
      await speak("두 센서가 함께 거리를 측정해 더 정확한 결과를 얻습니다.", speed: 1.0);
      await Future.delayed(const Duration(seconds: 1));
      await speak("시작!", speed: 1.2);
      
      // IMU + 카메라 융합 측정 시작
      await _startHybridMeasurement();
      
      // 측정 시작 콜백 호출
      if (onMeasurementStart != null) {
        onMeasurementStart!({'status': 'started', 'method': '10m_measurement'});
        _addDebugLog('10m 측정 시작 콜백 호출됨');
      }
      
      // 30초 후 완료 안내
      Future.delayed(const Duration(seconds: 30), () async {
        if (_measurementStartTime != null && !_isAwaitingStepCount) {
          await speak("10미터 걷기가 완료되었습니다. 총 몇 걸음 걸으셨는지 말씀해주세요.", speed: 1.0);
          _isAwaitingStepCount = true;
          _setStatus("걸음수 입력 대기 중...");
        }
      });
      
      _addDebugLog("IMU + 카메라 융합 측정 시작");
      
    } catch (e) {
      _addDebugLog("❌ 융합 측정 시작 오류: $e");
      _setStatus("측정 시작 중 오류 발생");
    }
  }

  /// IMU + 카메라 하이브리드 측정 시작
  Future<void> _startHybridMeasurement() async {
    try {
      // 1. IMU 센서 시작
      _initializeIMUSensors();
      
      // 2. 카메라 기반 측정 세션 시작
      await _startMeasurementSession();
      
      // 30초 후 측정 완료 및 걸음수 입력 요청
      Future.delayed(const Duration(seconds: 30), () async {
        if (_measurementStartTime != null && !_isAwaitingStepCount) {
          await _stopHybridMeasurement();
          await speak("측정이 완료되었습니다. 총 몇 걸음 걸으셨는지 말씀해주세요.", speed: 1.0);
          _isAwaitingStepCount = true;
          _setStatus("걸음수 입력 대기 중...");
        }
      });
      
      _addDebugLog("하이브리드 측정 세션 시작됨");
      
    } catch (e) {
      _addDebugLog("❌ 하이브리드 측정 시작 오류: $e");
      _setStatus("하이브리드 측정 시작 실패");
    }
  }

  /// IMU 센서 초기화 및 시작
  void _initializeIMUSensors() {
    try {
      // 초기화
      _totalDistance = 0.0;
      _currentVelocity = 0.0;
      _detectedSteps = 0;
      _accelerationHistory.clear();
      _velocityHistory.clear();
      _lastSensorUpdate = DateTime.now();
      
      // 가속도계 구독 시작 (100Hz)
      _accelerometerSubscription = accelerometerEventStream().listen(
        _onAccelerometerEvent,
        onError: (error) {
          _addDebugLog("❌ 가속도계 오류: $error");
        },
      );
      
      // 자이로스코프 구독 시작 (추가 안정성을 위해)
      _gyroscopeSubscription = gyroscopeEventStream().listen(
        _onGyroscopeEvent,
        onError: (error) {
          _addDebugLog("❌ 자이로스코프 오류: $error");
        },
      );
      
      _addDebugLog("✅ IMU 센서 초기화 완료 (가속도계 + 자이로스코프)");
    } catch (e) {
      _addDebugLog("❌ IMU 센서 초기화 오류: $e");
    }
  }

  /// 가속도계 이벤트 처리
  void _onAccelerometerEvent(AccelerometerEvent event) {
    if (_measurementStartTime == null) return;
    
    final now = DateTime.now();
    final deltaTime = _lastSensorUpdate != null 
        ? now.difference(_lastSensorUpdate!).inMicroseconds / 1000000.0
        : 0.01; // 기본 10ms
    
    _lastSensorUpdate = now;
    
    // 중력 보정된 가속도 계산 (지구 중력: 9.8m/s²)
    final magnitude = math.sqrt(
      event.x * event.x + event.y * event.y + event.z * event.z
    );
    
    final linearAccel = (magnitude - 9.8).abs();
    _accelerationHistory.add(linearAccel);
    
    // 가속도 히스토리 관리 (최근 100개 샘플만 유지)
    if (_accelerationHistory.length > 100) {
      _accelerationHistory.removeAt(0);
    }
    
    // 걸음 감지 (피크 감지 알고리즘)
    _detectStep(linearAccel, now.millisecondsSinceEpoch / 1000.0);
    
    // 속도 및 거리 적분 계산
    _currentVelocity += linearAccel * deltaTime;
    _velocityHistory.add(_currentVelocity);
    
    // 속도 히스토리 관리 및 드리프트 보정
    if (_velocityHistory.length > 50) {
      _velocityHistory.removeAt(0);
      // 속도 드리프트 보정 (평균값으로 중심화)
      final avgVelocity = _velocityHistory.reduce((a, b) => a + b) / _velocityHistory.length;
      _currentVelocity -= avgVelocity * 0.1; // 드리프트 보정 계수
    }
    
    // 거리 적분
    _totalDistance += _currentVelocity.abs() * deltaTime;
    
    // 로그 출력 (5초마다)
    if (now.millisecond % 5000 < 50) { // 대략 5초마다
      _addDebugLog("IMU: ${_totalDistance.toStringAsFixed(1)}m, 걸음: $_detectedSteps, 가속도: ${linearAccel.toStringAsFixed(2)}m/s²");
    }
  }
  
  /// 자이로스코프 이벤트 처리 (회전 보정용)
  void _onGyroscopeEvent(GyroscopeEvent event) {
    // 걷는 중 회전에 대한 보정을 위해 사용
    // 현재는 기본 구현, 필요시 고도화 가능
  }
  
  /// 걸음 감지 알고리즘
  void _detectStep(double acceleration, double timestamp) {
    // 간단한 피크 감지: 임계값 초과 & 최소 간격
    if (acceleration > _stepThreshold && 
        (timestamp - _lastPeakTime) > 0.3) { // 최소 300ms 간격
      
      _detectedSteps++;
      _lastPeakTime = timestamp;
      
      // 걸음 감지시 로그
      _addDebugLog("🚶 걸음 감지: $_detectedSteps걸음");
    }
  }

  /// 하이브리드 측정 중지
  Future<void> _stopHybridMeasurement() async {
    try {
      // IMU 센서 구독 해제
      await _accelerometerSubscription?.cancel();
      _accelerometerSubscription = null;
      
      await _gyroscopeSubscription?.cancel();
      _gyroscopeSubscription = null;
      
      // 기존 타이머도 정리
      _sensorTimer?.cancel();
      _sensorTimer = null;
      
      // 카메라 측정 중지는 기존 시스템 활용 (서버에서 처리)
      _addDebugLog("✅ 하이브리드 측정 중지됨 (IMU 센서 구독 해제)");
      
    } catch (e) {
      _addDebugLog("❌ 하이브리드 측정 중지 오류: $e");
    }
  }

  /// IMU + 카메라 융합 측정 완료 및 보폭 계산
  Future<void> _complete10mMeasurement() async {
    try {
      if (_userCountedSteps == null || _userCountedSteps! <= 0) {
        await speak("유효하지 않은 걸음수입니다.", speed: 1.0);
        return;
      }

      _setStatus("하이브리드 센서 데이터를 융합하여 보폭을 계산하고 있습니다...");
      
      // 센서 융합: IMU 거리와 카메라 거리를 결합
      final fusedDistance = await _calculateFusedDistance();
      // ignore: non_constant_identifier_names
      final step_length_cm = (fusedDistance * 100) / _userCountedSteps!; // m를 cm로 변환
      
      _addDebugLog("✅ 하이브리드 측정 완료: $_userCountedSteps 걸음, 융합거리: ${fusedDistance.toStringAsFixed(1)}m, 보폭: ${step_length_cm.toStringAsFixed(1)}cm");
      
      await speak("센서 융합 계산 완료! 총 $_userCountedSteps 걸음, 측정거리 ${fusedDistance.toStringAsFixed(1)}미터로 보폭은 ${step_length_cm.toStringAsFixed(1)}센티미터입니다.", speed: 1.0);
      
      // 서버에 결과 전송 (기존 API 사용)
      await _sendStepLengthResult(step_length_cm);
      
      // 측정 완료 콜백 호출
      if (onMeasurementComplete != null) {
        onMeasurementComplete!({
          'step_length_cm': step_length_cm,
          'step_count': _userCountedSteps,
          'fused_distance': fusedDistance,
          'method': 'imu_camera_fusion',
          'confidence': 0.92 // 융합 측정이므로 더 높은 신뢰도
        });
      }
      
      // 초기화
      _userCountedSteps = null;
      _measurementStartTime = null;
      _totalDistance = 0.0;
      _setStatus("하이브리드 보폭 측정 완료");
      
    } catch (e) {
      _addDebugLog("❌ 하이브리드 측정 완료 오류: $e");
      _setStatus("측정 완료 중 오류 발생");
    }
  }

  /// IMU와 카메라 데이터를 융합하여 최종 거리 계산
  Future<double> _calculateFusedDistance() async {
    try {
      // 1. IMU 센서 거리
      final imuDistance = _totalDistance;
      
      // 2. 카메라 기반 거리 (서버에서 계산된 값 가져오기)
      double cameraDistance = 0.0;
      try {
        final cameraResult = await _getCameraDistance();
        cameraDistance = cameraResult;
      } catch (e) {
        _addDebugLog("카메라 거리 측정 실패: $e");
        cameraDistance = 0.0;
      }
      
      _addDebugLog("IMU 거리: ${imuDistance.toStringAsFixed(1)}m, 카메라 거리: ${cameraDistance.toStringAsFixed(1)}m");
      
      // 3. 센서 융합 알고리즘
      double fusedDistance;
      
      if (cameraDistance > 0 && imuDistance > 0) {
        // 두 센서 모두 유효한 데이터가 있는 경우 가중평균
        // IMU는 60%, 카메라는 40% 가중치 (IMU가 더 안정적)
        fusedDistance = (imuDistance * 0.6) + (cameraDistance * 0.4);
        _addDebugLog("센서 융합 성공 (IMU 60% + 카메라 40%)");
      } else if (imuDistance > 0) {
        // IMU만 유효한 경우
        fusedDistance = imuDistance;
        _addDebugLog("IMU 센서만 사용");
      } else if (cameraDistance > 0) {
        // 카메라만 유효한 경우
        fusedDistance = cameraDistance;
        _addDebugLog("카메라 센서만 사용");
    } else {
        // 둘 다 실패한 경우 평균 걷기 속도 추정
        final elapsedTime = DateTime.now().difference(_measurementStartTime!).inSeconds;
        fusedDistance = elapsedTime * 1.2; // 평균 걷기 속도 1.2m/s
        _addDebugLog("센서 융합 실패, 시간 기반 추정 사용");
    }
      
      // 합리적인 범위 체크 (0.5m ~ 100m)
      fusedDistance = math.max(0.5, math.min(100.0, fusedDistance));
      
      _addDebugLog("최종 융합 거리: ${fusedDistance.toStringAsFixed(1)}m");
      return fusedDistance;
      
    } catch (e) {
      _addDebugLog("❌ 센서 융합 계산 오류: $e");
      return 10.0; // 기본값 10m
    }
  }

  /// 카메라 기반 측정 거리 가져오기
  Future<double> _getCameraDistance() async {
    try {
      // 기존 측정 세션에서 결과 가져오기
      final response = await http.get(
        Uri.parse('$baseUrl/api/users/measurement/distance'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        final distance = result['total_distance_meters']?.toDouble() ?? 0.0;
        _addDebugLog("카메라 측정 거리: ${distance.toStringAsFixed(1)}m");
        return distance;
      } else {
        _addDebugLog("카메라 거리 조회 실패: ${response.statusCode}");
        return 0.0;
      }
    } catch (e) {
      _addDebugLog("카메라 거리 조회 오류: $e");
      return 0.0;
    }
  }

  /// 기존 API를 사용하여 보폭 결과 전송 (백엔드와 동일한 변수명)
  // ignore: non_constant_identifier_names
  Future<void> _sendStepLengthResult(double step_length_cm) async {
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/users/step-length'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'user_id': 'current_user',
              'step_length': step_length_cm,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        _addDebugLog('✅ 개선된 보폭 측정 결과 전송 성공 (기존 API 사용)');
        } else {
        _addDebugLog('❌ 보폭 결과 전송 실패: ${response.statusCode}');
      }
    } catch (e) {
      _addDebugLog('❌ 보폭 결과 전송 오류: $e');
    }
  }

  /// 한국어 텍스트에서 걸음수 추출
  int? _extractStepCountFromText(String text) {
    try {
      final cleanText = text.toLowerCase().trim();
      
      // 한국어 숫자 매핑
      final koreanNumbers = {
        '하나': 1, '둘': 2, '셋': 3, '넷': 4, '다섯': 5,
        '여섯': 6, '일곱': 7, '여덟': 8, '아홉': 9, '열': 10,
        '열하나': 11, '열둘': 12, '열셋': 13, '열넷': 14, '열다섯': 15,
        '열여섯': 16, '열일곱': 17, '열여덟': 18, '열아홉': 19, '스무': 20,
        '스물하나': 21, '스물둘': 22, '스물셋': 23, '스물넷': 24, '스물다섯': 25,
        '서른': 30, '마흔': 40, '쉰': 50
      };
      
      // 아라비아 숫자 패턴
      final arabicPattern = RegExp(r'\d+');
      final arabicMatch = arabicPattern.firstMatch(cleanText);
      if (arabicMatch != null) {
        return int.parse(arabicMatch.group(0)!);
      }
      
      // 한국어 숫자 패턴
      for (final entry in koreanNumbers.entries) {
        if (cleanText.contains(entry.key)) {
          return entry.value;
        }
      }
      
      // "걸음" 앞의 숫자 추출 시도
      final stepPattern = RegExp(r'(\d+)\s*걸음');
      final stepMatch = stepPattern.firstMatch(cleanText);
      if (stepMatch != null) {
        return int.parse(stepMatch.group(1)!);
      }
      
      _addDebugLog("걸음수 추출 실패: $text");
      return null;
      
    } catch (e) {
      _addDebugLog("걸음수 추출 오류: $e");
      return null;
    }
  }


  /// STT API 호출을 재시도 로직과 함께 실행
  Future<Map<String, dynamic>> _convertSpeechToTextWithRetry(
    String filePath,
  ) async {
    const int maxRetries = 1;
    for (int attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        _addDebugLog('STT 시도 $attempt/$maxRetries');
        return await _convertSpeechToText(filePath);
      } catch (e) {
        _addDebugLog('STT 시도 $attempt 실패: $e');
        if (attempt == maxRetries) rethrow;
        final delaySeconds = 2 * attempt; // 지수 백오프
        _addDebugLog('$delaySeconds초 후 재시도...');
        await Future.delayed(Duration(seconds: delaySeconds));
      }
    }
    throw Exception('All STT attempts failed');
  }

  /// STT API 호출 및 상세 디버깅 (타임아웃 20초)
  Future<Map<String, dynamic>> _convertSpeechToText(String filePath) async {
    final url = '$baseUrl/api/users/speech/transcribe';

    _addDebugLog('📡 서버 주소: $baseUrl');
    _addDebugLog('⏱️ 요청 타임아웃: 20초');
    _addDebugLog("📤 STT 서버 호출 시작: $url");

    // 파일 상태 확인
    final file = File(filePath);
    if (!await file.exists()) {
      _addDebugLog("❌ 오디오 파일이 존재하지 않음: $filePath");
      throw Exception('오디오 파일을 찾을 수 없습니다');
    }

    final fileSize = await file.length();

    if (fileSize == 0) {
      _addDebugLog("❌ 오디오 파일이 비어있음");
      throw Exception('오디오 파일이 비어있습니다');
    }

    try {
      final request = http.MultipartRequest('POST', Uri.parse(url));

      // 파일 포맷 자동 감지
      String contentTypeMain = 'audio';
      String contentTypeSub = 'm4a'; // 기본값

      final extension = filePath.split('.').last.toLowerCase();
      switch (extension) {
        case 'm4a':
          contentTypeSub = 'm4a';
          break;
        case 'wav':
          contentTypeSub = 'wav';
          break;
        case 'mp3':
          contentTypeSub = 'mpeg';
          break;
        case 'aac':
          contentTypeSub = 'aac';
          break;
        default:
          _addDebugLog("⚠️ 알 수 없는 오디오 포맷: $extension, m4a로 처리");
      }

      // 파일 첨부
      _addDebugLog("📎 오디오 파일 첨부 시작... (포맷: $contentTypeMain/$contentTypeSub)");
      request.files.add(
        await http.MultipartFile.fromPath(
          'file',
          filePath,
          contentType: MediaType(contentTypeMain, contentTypeSub),
        ),
      );
      _addDebugLog("✅ 오디오 파일 첨부 완료");

      // 헤더 설정
      request.headers.addAll({
        'Accept': 'application/json',
        'User-Agent': 'Flutter-App/1.0',
      });

      // 요청 전송 및 응답 받기 (20초 타임아웃으로 단축)
      _addDebugLog("🚀 STT 서버로 요청 전송 중...");
      final startTime = DateTime.now();

      final streamedResponse = await _httpClient
          .send(request)
          .timeout(
            const Duration(seconds: 8),
            onTimeout: () {
              throw TimeoutException('STT request timed out after 8 seconds');
            },
          );

      final endTime = DateTime.now();
      final duration = endTime.difference(startTime);
      _addDebugLog("⏱️ 요청 전송 완료 (소요시간: ${duration.inMilliseconds}ms)");

      _addDebugLog("📥 응답 스트림을 Response 객체로 변환 중...");
      final response = await http.Response.fromStream(streamedResponse);

      _addDebugLog("📊 서버 응답 수신: ${response.statusCode}");
      _addDebugLog("🕐 응답 시간: ${DateTime.now().toIso8601String()}");
      _addDebugLog("📦 응답 본문 크기: ${response.bodyBytes.length} bytes");
      _addDebugLog("📋 응답 헤더: ${response.headers}");

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        return result;
      } else {
        _addDebugLog("❌ STT 서버 오류: ${response.statusCode}");
        _addDebugLog("📄 서버 응답: ${response.body}");
        throw HttpException('STT server error: ${response.statusCode}');
      }
    } catch (e) {
      _addDebugLog("❌ STT 요청 중 오류 발생: $e");
      _addDebugLog("🔍 오류 타입: ${e.runtimeType}");

      if (e is TimeoutException) {
        _addDebugLog("⏰ 타임아웃 오류 - 서버 응답이 20초 내에 오지 않음");
        _addDebugLog("💡 해결책: 네트워크 연결 상태나 서버 상태를 확인해주세요");
      } else if (e is SocketException) {
        _addDebugLog("🌐 네트워크 연결 오류 - 서버에 연결할 수 없음");
        _addDebugLog("💡 해결책: WiFi/모바일 데이터 연결과 서버 주소($baseUrl)를 확인해주세요");
      } else if (e is HttpException) {
        _addDebugLog("📡 HTTP 프로토콜 오류");
        _addDebugLog("💡 해결책: API 엔드포인트와 요청 형식을 확인해주세요");
      } else {
        _addDebugLog("💡 해결책: 앱을 재시작하거나 네트워크 설정을 확인해주세요");
      }

      rethrow;
    }
  }

  /// NLU 백엔드 서버를 호출하는 함수 (타임아웃 15초)
  /// 백엔드에서 다음 측정 관련 패턴들을 인식해야 함:
  /// - '측정 시작', '보폭 측정' → START_MEASUREMENT
  Future<Map<String, dynamic>> _getIntentFromText(String commandText) async {
    final url = '$baseUrl/api/users/speech/recognition';
    _addDebugLog("NLU 서버 호출: $url");
    _addDebugLog("분석할 텍스트: $commandText");

    try {
      final response = await _httpClient
          .post(
            Uri.parse(url),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'command_text': commandText}),
          )
          .timeout(
            const Duration(seconds: 5),
            onTimeout: () {
              throw TimeoutException('NLU request timed out after 5 seconds');
            },
          );

      _addDebugLog("NLU 응답 상태: ${response.statusCode}");

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog("✅ NLU 성공: $result");
        return result;
      } else {
        _addDebugLog("❌ NLU 서버 오류: ${response.statusCode} ${response.body}");
        throw HttpException('NLU server error: ${response.statusCode}');
      }
    } on TimeoutException catch (e) {
      _addDebugLog("❌ NLU 타임아웃: $e");
      return {'intent': 'timeout_error'};
    } on SocketException catch (e) {
      _addDebugLog("❌ NLU 네트워크 연결 오류: $e");
      return {'intent': 'network_error'};
    } catch (e) {
      _addDebugLog("❌ NLU 서버 연결 예외: $e");
      return {'intent': 'error'};
    }
  }

  /// 앱 시작 시 사용자 설정 불러오기
  Future<void> _loadUserSettings() async {
    try {
      final settings = await ApiService().getUserSettings();
      if (settings != null) {
        // 음성 속도 설정
        if (settings.containsKey('voice_speed') && settings['voice_speed'] != null) {
          final int serverSpeed = settings['voice_speed'];
          // 서버 값(1-20)을 앱 내부 속도(0.5-1.5)로 변환
          final double appSpeed = 0.5 + (serverSpeed - 1) * 0.05;
          _currentVoiceSpeed = appSpeed;
          _addDebugLog('✅ 서버에서 음성 속도 로드: $serverSpeed -> ${appSpeed.toStringAsFixed(2)}x');
        }

        // 보폭 설정 로드
        if (settings.containsKey('step_length_cm') && settings['step_length_cm'] != null) {
          // ignore: non_constant_identifier_names
          final double step_length_cm = (settings['step_length_cm'] as num).toDouble();
          _addDebugLog('✅ 서버에서 보폭 로드: ${step_length_cm.toStringAsFixed(1)}cm');
          // 보폭 정보는 필요시 콜백으로 전달하거나 별도 저장소에 저장
        }
        
        // 사용자 이름 로드
        if (settings.containsKey('user_name') && settings['user_name'] != null) {
          final String userName = settings['user_name'];
          _addDebugLog('✅ 서버에서 사용자 이름 로드: $userName');
        }

        notifyListeners();
      }
    } catch (e) {
      _addDebugLog('❌ 사용자 설정 로드 실패: $e');
    }
  }

  /// 디버그 로그 추가
  void _addDebugLog(String message) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 23);
    _debugLogs.add("[$timestamp] $message");
    // 콘솔에도 출력 (개발용)
    notifyListeners();
  }

  /// 상태 메시지 설정
  void _setStatus(String message) {
    _statusMessage = message;
    notifyListeners();
  }

  /// 상태 변경
  void _setState(VoiceState newState) {
    if (_currentState != newState) {
      _currentState = newState;
      notifyListeners();
    }
  }

  /// 카메라 기반 측정 세션 시작 (하이브리드 모드용)
  Future<bool> _startMeasurementSession() async {
    try {
      _addDebugLog("=== 카메라 측정 세션 시작 요청 (하이브리드 모드) ===");

      final response = await _httpClient
          .post(
            Uri.parse('$baseUrl/api/users/measurement/session/start'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user', 'mode': 'hybrid_imu_camera'}),
          )
          .timeout(
            const Duration(seconds: 5),
            onTimeout: () {
              throw TimeoutException(
                'Hybrid measurement start request timed out after 5 seconds',
              );
            },
          );

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog('✅ 하이브리드 측정이 시작되었습니다');
        _addDebugLog('세션 상태: ${result['status']}');
        _addDebugLog('모드: ${result.containsKey('mode') ? result['mode'] : 'hybrid'}');
        _setStatus("카메라 + IMU 하이브리드 측정 세션 시작됨");
        return true;
      } else {
        _addDebugLog('❌ 하이브리드 측정 시작 실패: ${response.statusCode}');
        _addDebugLog('서버 응답: ${response.body}');
        _setStatus("하이브리드 측정 시작 실패");
        return false;
      }
    } on TimeoutException catch (e) {
      _addDebugLog('❌ 하이브리드 측정 시작 타임아웃: $e');
      _setStatus("하이브리드 측정 시작 요청 타임아웃");
      return false;
    } on SocketException catch (e) {
      _addDebugLog('❌ 하이브리드 측정 시작 네트워크 오류: $e');
      _setStatus("네트워크 연결 오류");
      return false;
    } catch (e) {
      _addDebugLog('❌ 하이브리드 측정 시작 오류: $e');
      _setStatus("하이브리드 측정 시작 중 오류 발생");
      return false;
    }
  }

  /// 하이브리드 측정용 프레임 업로드 (조용히, 음성 안내 없음)
  Future<void> uploadFrameForMeasurement(String imagePath) async {
    try {
      // 측정 중이 아니면 업로드하지 않음
      if (_measurementStartTime == null) return;

      final file = File(imagePath);
      if (!file.existsSync()) {
        _addDebugLog("❌ 프레임 파일이 존재하지 않음: $imagePath");
        return;
      }

      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$baseUrl/api/users/measurement/frame'),
      );

      // 파일 첨부
      request.files.add(
        await http.MultipartFile.fromPath(
          'frame',
          imagePath,
          contentType: MediaType('image', 'jpeg'),
        ),
      );

      // 사용자 ID 추가
      request.fields['user_id'] = 'current_user';
      request.fields['measurement_type'] = 'hybrid_imu_camera';
      request.fields['timestamp'] = DateTime.now().toIso8601String();

      // 조용히 업로드 (음성 안내 없음)
      final response = await _httpClient.send(request).timeout(
        const Duration(seconds: 10),
      );

      if (response.statusCode == 200) {
        // 성공해도 조용히 처리 (디버그 로그만)
        _addDebugLog("📸 하이브리드 측정용 프레임 업로드 성공 (조용히)");
      } else {
        _addDebugLog("❌ 하이브리드 측정용 프레임 업로드 실패: ${response.statusCode}");
      }
    } catch (e) {
      _addDebugLog("❌ 하이브리드 측정용 프레임 업로드 오류: $e");
      // 오류가 발생해도 측정은 계속 진행 (IMU 데이터는 유지)
    }
  }

  /// 로그 초기화
  void clearLogs() {
    _debugLogs.clear();
    _lastRecognizedText = "";
    _addDebugLog("로그 초기화됨");
  }

  /// 강제 중단
  void forceStop() {
    if (_currentState == VoiceState.listening) {
      _audioRecorder.stop();
    }
    _setState(VoiceState.idle);
    _addDebugLog("강제 중단됨");
    _setStatus("중단됨");
  }

  /// Google Cloud TTS를 통한 음성 출력 - 최적화된 버전
  Future<void> speak(
    String text, {
    String gender = "female",
    double speed = 1.0,
  }) async {
    // 빈 텍스트는 즉시 반환
    if (text.trim().isEmpty) return;
    
    // 이미 음성 출력 중이면 즉시 중단 (await 제거로 속도 향상)
    if (_isSpeaking) {
      try {
        _audioPlayer.stop();
      } catch (e) {
        // 무시 (로그 제거로 속도 향상)
      }
      _isSpeaking = false;
    }

    try {
      _isSpeaking = true;
      
      // HTTP 요청 타임아웃을 3초로 단축 (기존 8초 → 3초)
      final response = await _httpClient
          .post(
            Uri.parse('$baseUrl/api/users/voice'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'user_id': 'c63427ae-ac05-4292-a52f-c967f36b3861',
              'text': text,
              'gender': gender,
              'speed': speed,
            }),
          )
          .timeout(const Duration(seconds: 3));

      if (response.statusCode == 200) {
        // 데이터 크기 체크 (빠른 검증)
        if (response.bodyBytes.length < 100) {
          _isSpeaking = false;
          return;
        }

        // 메모리 기반 재생으로 변경 (파일 I/O 제거)
        await _ttsSubscription?.cancel();

        // audioFile을 상위 스코프로 이동
        final directory = await getApplicationDocumentsDirectory();
        final timestamp = DateTime.now().millisecondsSinceEpoch;
        final audioFile = File('${directory.path}/tts_$timestamp.mp3');

        try {
          final player = _audioPlayer;
          
          // 플레이어 상태 초기화 (병렬 처리)
          await Future.wait([
            player.stop(),
            player.setVolume(1.0),
          ]);
          
          // 파일 쓰기와 오디오 소스 설정을 병렬 처리
          await audioFile.writeAsBytes(response.bodyBytes);
          await player.setAudioSource(AudioSource.file(audioFile.path));
          
          // 즉시 재생 시작
          await player.play();

          // 재생 완료 시 간소화된 정리 (지연 최소화)
          _ttsSubscription = player.processingStateStream
              .where((state) => state == ProcessingState.completed)
              .take(1)
              .listen((_) {
                _isSpeaking = false;
                // 파일 정리를 백그라운드에서 즉시 실행
                try {
                  audioFile.deleteSync();
                } catch (_) {
                  // 파일 삭제 실패 무시
                }
              });
              
        } catch (playerError) {
          _isSpeaking = false;
          
          // 간소화된 재시도 로직 (한 번만)
          try {
            final newPlayer = AudioPlayer();
            await Future.wait([
              newPlayer.setVolume(1.0),
              newPlayer.setAudioSource(AudioSource.file(audioFile.path)),
            ]);
            await newPlayer.play();
            
            _isSpeaking = true;
            
            // 새 플레이어 정리
            newPlayer.processingStateStream
                .where((state) => state == ProcessingState.completed)
                .take(1)
                .listen((_) {
                  _isSpeaking = false;
                  newPlayer.dispose();
                  try {
                    audioFile.deleteSync();
                  } catch (_) {}
                });
                
            return; // 재시도 성공
            
          } catch (_) {
            // 재시도 실패 - 파일만 정리
            try {
              audioFile.deleteSync();
            } catch (_) {}
          }
        }
      } else {
        _isSpeaking = false;
      }
    } catch (e) {
      _isSpeaking = false;
    }
  }

  @override
  void dispose() {
    // IMU 센서 구독 해제
    _accelerometerSubscription?.cancel();
    _gyroscopeSubscription?.cancel();
    _sensorTimer?.cancel();
    
    _httpClient.close(); // HTTP 클라이언트 해제
    _ttsSubscription?.cancel(); // TTS 스트림 리스너 해제
    _audioRecorder.dispose();
    // AudioPlayer 관리자의 dispose 호출 (필요시)
    // _playerManager.dispose(); // 전역 사용시에는 dispose하지 않음
    super.dispose();
  }
}

/// AudioPlayer 싱글톤 관리 클래스
class _AudioPlayerManager {
  static _AudioPlayerManager? _instance;
  AudioPlayer? _player;
  bool _isInitializing = false;
  
  _AudioPlayerManager._internal();
  
  factory _AudioPlayerManager() {
    _instance ??= _AudioPlayerManager._internal();
    return _instance!;
  }
  
  AudioPlayer get player {
    if (_player == null && !_isInitializing) {
      _initializePlayer();
    }
    // 초기화 실패한 경우 마지막 시도
    if (_player == null) {
      debugPrint('⚠️ AudioPlayer 마지막 시도 - 기본 플레이어 생성');
      try {
        _player = AudioPlayer();
        debugPrint('✅ 마지막 시도로 AudioPlayer 생성 성공');
      } catch (e) {
        debugPrint('❌ 마지막 AudioPlayer 생성 시도 실패: $e');
        // AudioPlayer 생성에 완전히 실패한 경우 예외 발생
        throw Exception('AudioPlayer 초기화 완전 실패: $e');
      }
    }
    return _player!;
  }
  
  void _initializePlayer() {
    if (_isInitializing || _player != null) return;
    
    _isInitializing = true;
    try {
      // AudioPlayer를 고유 ID와 함께 생성
      _player = AudioPlayer();
      debugPrint('✅ AudioPlayer 초기화 성공');
    } catch (e) {
      debugPrint('❌ AudioPlayer 초기화 오류: $e');
      // 오류가 발생해도 계속 시도
      try {
        _player = AudioPlayer();
        debugPrint('✅ AudioPlayer 재시도 생성 성공');
      } catch (e2) {
        debugPrint('❌ AudioPlayer 완전 실패: $e2');
        _player = null;
      }
    } finally {
      _isInitializing = false;
    }
  }
  
  void dispose() {
    _player?.dispose();
    _player = null;
  }
}
