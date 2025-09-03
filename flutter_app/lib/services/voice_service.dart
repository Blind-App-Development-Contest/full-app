import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;
import 'package:just_audio/just_audio.dart';
import 'package:http_parser/http_parser.dart';

/// 음성 인식 상태

enum VoiceState { idle, listening, processing }

class VoiceService with ChangeNotifier {
  final Record _audioRecorder = Record();
  // AudioPlayer 싱글톤 관리 클래스
  static final _AudioPlayerManager _playerManager = _AudioPlayerManager();
  AudioPlayer get _audioPlayer => _playerManager.player;

  // --- http.Client를 멤버 변수로 선언하여 재사용 ---
  final http.Client _httpClient = http.Client();

  // === 서버 설정 ===
  static const String baseUrl = 'http://192.168.45.74:8000';

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

  // === Measurement Callbacks ===
  Function(Map<String, dynamic>)? onMeasurementComplete;
  Function(Map<String, dynamic>)? onMeasurementStart;

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
      await _audioRecorder.start(path: _currentRecordingPath!);

      _setState(VoiceState.listening);
      _setStatus("녹음 중... (최대 20초)");
      _addDebugLog("녹음 시작됨");

      // 5초 타임아웃으로 단축
      Future.delayed(const Duration(seconds: 5), () {
        if (_currentState == VoiceState.listening) {
          _addDebugLog("5초 타임아웃으로 자동 중단");
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
        // 자동 인식 사이클이 활성화 상태일 때, 1초 후 다음 인식 시작
        Future.delayed(const Duration(seconds: 1), () {
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
        // TTS와 측정 시작을 병렬로 처리하여 시간 단축
        final ttsTask = speak("보폭 측정을 시작하겠습니다. 카메라 화면으로 이동합니다.", speed: 1.2);
        final measurementTask = _startMeasurementAndNavigate();
        await Future.wait([ttsTask, measurementTask]);
        break;
      case 'FOOTSTEP_MEASUREMENT_COMPLETE':
      case 'STOP_MEASUREMENT':
      case 'FINISH_MEASURING':
      case 'END_WALKING':
      case 'MEASUREMENT_COMPLETE':
        _setStatus("측정을 완료하겠습니다");
        // TTS와 측정 완료를 병렬로 처리하여 시간 단축
        final ttsTask = speak("보폭 측정을 완료하겠습니다.", speed: 1.2);
        final stopTask = stopMeasurementWorkflow();
        await Future.wait([ttsTask, stopTask]);
        break;
      case 'STOP_LISTENING':
      case 'FOOTSTEP_MEASUREMENT_CANCEL':
        _setStatus("측정을 중단하겠습니다");
        // 중단은 즉시 실행하고 TTS는 병렬로
        stopAutoRecognitionCycle();
        speak("측정을 중단하겠습니다.", speed: 1.2); // await 제거하여 즉시 처리
        break;
      default:
        _setStatus("알 수 없는 명령: $command");
        _addDebugLog('알 수 없는 명령: $command');
        break;
    }
  }

  /// 측정 세션 시작 (화면 이동 없이 서버만 호출)
  Future<void> _startMeasurementAndNavigate() async {
    // 서버에 측정 시작 요청
    final success = await _startMeasurementSession();

    if (success) {
      _addDebugLog("측정 세션 시작됨 - 현재 화면에서 카메라 활성화");
      // 측정 시작 콜백 호출
      if (onMeasurementStart != null) {
        onMeasurementStart!({'status': 'started'});
        _addDebugLog('측정 시작 콜백 호출됨');
      }
    } else {
      _addDebugLog("측정 세션 시작 실패");
    }
  }

  /// 새로운 측정 중지 워크플로우 (향상된 기능)
  Future<void> stopMeasurementWorkflow() async {
    try {
      _addDebugLog('🛑 보폭 측정 종료 중...');
      _setStatus('측정을 종료하고 있습니다...');

      // 측정 중지 API 호출
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/users/measurement/session/stop'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(
            const Duration(seconds: 5),
            onTimeout: () {
              throw TimeoutException('측정 종료 요청 타임아웃');
            },
          );

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog('✅ 측정 완료: 상태=${result['status']}');

        // 측정 결과 표시
        if (result['final_result'] != null) {
          final finalResult = result['final_result'];
          final steps = finalResult['total_steps'] ?? 0;
          final frames = finalResult['frame_count'] ?? 0;
          _setStatus('측정 완료! 총 걸음수: $steps, 프레임: $frames');
          _addDebugLog('측정 결과 - 총 걸음수: $steps, 프레임 수: $frames');
        } else {
          _setStatus('측정이 완료되었습니다.');
        }

        // 측정 완료 콜백 호출
        if (onMeasurementComplete != null) {
          onMeasurementComplete!(result);
          _addDebugLog('측정 완료 콜백 호출됨');
        }

        // 카메라 모드 복원 확인
        if (result['camera_mode_switched'] == true) {
          _addDebugLog('카메라 모드가 실시간 모드로 복원되었습니다.');
        }
      } else {
        _addDebugLog('❌ 측정 종료 실패: ${response.statusCode}');
        _addDebugLog('서버 응답: ${response.body}');
        _setStatus('측정 종료에 실패했습니다.');
      }
    } on TimeoutException catch (e) {
      _addDebugLog('❌ 측정 종료 타임아웃: $e');
      _setStatus('측정 종료 요청 타임아웃');
    } on SocketException catch (e) {
      _addDebugLog('❌ 측정 종료 네트워크 오류: $e');
      _setStatus('네트워크 연결 오류');
    } catch (e) {
      _addDebugLog('❌ 측정 종료 오류: $e');
      _setStatus('측정 종료 중 오류 발생');
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
            const Duration(seconds: 20),
            onTimeout: () {
              _addDebugLog("❌ STT 요청 20초 타임아웃 발생");
              throw TimeoutException('STT request timed out after 20 seconds');
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
            const Duration(seconds: 8),
            onTimeout: () {
              throw TimeoutException('NLU request timed out after 8 seconds');
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

  /// 보폭 측정 세션 시작 (타임아웃 10초)
  Future<bool> _startMeasurementSession() async {
    try {
      _addDebugLog("=== 측정 세션 시작 요청 ===");

      final response = await _httpClient
          .post(
            Uri.parse('$baseUrl/api/users/measurement/session/start'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(
            const Duration(seconds: 5),
            onTimeout: () {
              throw TimeoutException(
                'Measurement start request timed out after 5 seconds',
              );
            },
          );

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog('✅ 측정이 시작되었습니다');
        _addDebugLog('세션 상태: ${result['status']}');
        _addDebugLog('카메라 모드: ${result['camera_mode']}');
        _setStatus("보폭 측정 세션이 시작되었습니다");
        return true;
      } else {
        _addDebugLog('❌ 측정 시작 실패: ${response.statusCode}');
        _addDebugLog('서버 응답: ${response.body}');
        _setStatus("측정 시작 실패");
        return false;
      }
    } on TimeoutException catch (e) {
      _addDebugLog('❌ 측정 시작 타임아웃: $e');
      _setStatus("측정 시작 요청 타임아웃");
      return false;
    } on SocketException catch (e) {
      _addDebugLog('❌ 측정 시작 네트워크 오류: $e');
      _setStatus("네트워크 연결 오류");
      return false;
    } catch (e) {
      _addDebugLog('❌ 측정 시작 오류: $e');
      _setStatus("측정 시작 중 오류 발생");
      return false;
    }
  }

  /// 측정 프레임 업로드 (메타데이터 포함 - 칼만 필터 지원)
  Future<Map<String, dynamic>> uploadMeasurementFrameWithMetadata(
    File imageFile,
    String userId, {
    int frameCount = 0,
    double estimatedDistance = 0.0,
    int estimatedStepCount = 0,
    DateTime? sessionStartTime,
  }) async {
    try {
      _addDebugLog('📤 프레임 업로드 시작: ${imageFile.path}');
      _addDebugLog('서버 주소: $baseUrl/api/users/measurement/frame');

      // 파일 존재 여부 확인
      if (!imageFile.existsSync()) {
        _addDebugLog('❌ 이미지 파일이 존재하지 않음: ${imageFile.path}');
        throw Exception('이미지 파일을 찾을 수 없습니다');
      }

      // MultipartRequest 사용 (파일 업로드 방식)
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$baseUrl/api/users/measurement/frame'), // 올바른 엔드포인트
      );

      // 파일 첨부 (backend가 기대하는 'file' 필드명 사용)
      request.files.add(
        await http.MultipartFile.fromPath(
          'file',
          imageFile.path,
          filename: 'measurement_frame.jpg',
        ),
      );

      // Form 데이터 추가 (backend가 기대하는 방식)
      request.fields['user_id'] = userId;

      // 발 인식을 위한 추가 메타데이터
      request.fields['measurement_type'] = 'sequence';
      request.fields['enable_kalman'] = 'true';
      request.fields['image_enhancement'] = 'true'; // 이미지 품질 향상 요청
      request.fields['foot_detection_mode'] = 'aggressive'; // 적극적 발 인식 모드

      // 측정 세션 정보 (서버가 시퀀스 추적할 수 있도록)
      request.fields['session_id'] = userId;
      request.fields['frame_timestamp'] =
          DateTime.now().millisecondsSinceEpoch.toString();
      request.fields['frame_count'] = frameCount.toString();
      // 의미있는 값으로 계산하여 전송
      final meaningfulDistance =
          frameCount > 0 ? frameCount * 0.75 : 1.5; // 프레임당 75cm 추정
      final meaningfulStepCount =
          frameCount > 0 ? (frameCount * 0.5).round() : 2; // 프레임당 0.5걸음 추정

      // 서버가 기대하는 필드명 (로그 기준)
      request.fields['distance_meters'] = meaningfulDistance.toString();
      request.fields['step_count'] = meaningfulStepCount.toString();

      // 추가로 기존 이름도 전송 (호환성)
      request.fields['estimated_distance'] = estimatedDistance.toString();
      request.fields['estimated_step_count'] = estimatedStepCount.toString();

      // 세션 경과 시간
      if (sessionStartTime != null) {
        final elapsed = DateTime.now().difference(sessionStartTime).inSeconds;
        request.fields['session_elapsed_seconds'] = elapsed.toString();
      }

      _addDebugLog('프레임 파일 크기: ${await imageFile.length()} bytes');
      _addDebugLog('사용자 ID: $userId');
      _addDebugLog(
        '프레임 번호: $frameCount, 의미있는 거리: ${meaningfulDistance}m, 의미있는 걸음: $meaningfulStepCount',
      );
      _addDebugLog('기존 추정값: 거리=${estimatedDistance}m, 걸음=$estimatedStepCount');

      // 요청 전송 (타임아웃 60초로 증가 - 발 인식 처리 시간 고려)
      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 60),
        onTimeout: () {
          _addDebugLog('❌ 프레임 업로드 60초 타임아웃 발생');
          throw TimeoutException('프레임 업로드 타임아웃 (60초)');
        },
      );

      // 응답 처리
      final response = await http.Response.fromStream(streamedResponse);

      _addDebugLog('프레임 업로드 응답: ${response.statusCode}');

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog('✅ 프레임 업로드 성공');

        // FastDepth 프로세서 응답 처리
        if (result['success'] == true && result['measurement'] != null) {
          final measurement = result['measurement'];
          _addDebugLog(
            '측정 결과: ${measurement['step_length_cm']}cm (신뢰도: ${measurement['confidence']})',
          );
        } else if (result['success'] == false) {
          _addDebugLog('⚠️ 측정 실패: ${result['message']}');
        }

        return result;
      } else {
        _addDebugLog('❌ 프레임 업로드 실패: ${response.statusCode}');
        _addDebugLog('서버 응답: ${response.body}');
        throw HttpException('프레임 업로드 서버 오류: ${response.statusCode}');
      }
    } on TimeoutException catch (e) {
      _addDebugLog('❌ 프레임 업로드 타임아웃: $e');
      rethrow;
    } on SocketException catch (e) {
      _addDebugLog('❌ 프레임 업로드 네트워크 오류: $e');
      rethrow;
    } catch (e) {
      _addDebugLog('❌ 프레임 업로드 오류: $e');
      rethrow;
    }
  }

  /// 기존 호환성을 위한 래퍼 메서드
  Future<Map<String, dynamic>> uploadMeasurementFrame(
    File imageFile,
    String userId,
  ) async {
    return uploadMeasurementFrameWithMetadata(imageFile, userId);
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

  /// Google Cloud TTS를 통한 음성 출력
  Future<void> speak(
    String text, {
    String gender = "female",
    double speed = 1.0,
  }) async {
    try {
      _addDebugLog("🔊 음성 출력: $text");

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
          .timeout(const Duration(seconds: 8));

      if (response.statusCode == 200) {
        _addDebugLog("✅ TTS 응답 성공 (200 OK)");
        _addDebugLog("🔊 수신된 오디오 데이터 크기: ${response.bodyBytes.length} bytes");

        // 데이터 크기가 0이거나 너무 작으면 재생 시도 전에 차단
        if (response.bodyBytes.length < 100) {
          _addDebugLog("❌ 수신된 오디오 데이터가 너무 작아 재생할 수 없습니다.");
          return;
        }

        // 임시 파일로 저장 후 재생
        final directory = await getApplicationDocumentsDirectory();
        final timestamp = DateTime.now().millisecondsSinceEpoch;
        final audioFile = File('${directory.path}/tts_$timestamp.mp3');

        await audioFile.writeAsBytes(response.bodyBytes);
        _addDebugLog("🔊 TTS 파일 저장: ${audioFile.path}");

        await _ttsSubscription?.cancel();

        // 오디오 플레이어 안전한 사용
        try {
          final player = _audioPlayer; // getter를 통해 안전하게 접근
          await player.stop();
          await player.setAudioSource(AudioSource.file(audioFile.path));
          await player.play();

          // 재생이 완료될 때까지 대기 후 파일 삭제
          _ttsSubscription = player.processingStateStream
              .where((state) => state == ProcessingState.completed)
              .take(1)
              .listen((_) {
                Future.delayed(const Duration(milliseconds: 500)).then((_) {
                  if (audioFile.existsSync()) {
                    audioFile.deleteSync();
                    _addDebugLog("🔊 임시 TTS 파일 삭제됨");
                  }
                });
              });
        } catch (playerError) {
          _addDebugLog("❌ AudioPlayer 사용 오류: $playerError");
          // AudioPlayer 오류 시에도 파일 삭제
          Future.delayed(const Duration(milliseconds: 500)).then((_) {
            if (audioFile.existsSync()) {
              audioFile.deleteSync();
            }
          });
          rethrow;
        }
      } else {
        _addDebugLog("❌ TTS 실패: ${response.statusCode}");
      }
    } catch (e) {
      _addDebugLog("❌ TTS 오류: $e");
    }
  }

  @override
  void dispose() {
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
    // 초기화 실패한 경우에도 안전하게 처리
    if (_player == null) {
      debugPrint('❌ AudioPlayer가 초기화되지 않았습니다. 임시 플레이어를 생성하지 않고 오류를 발생시킵니다.');
      throw Exception('AudioPlayer 초기화 실패: Platform player already exists 오류로 인해 플레이어를 생성할 수 없습니다.');
    }
    return _player!;
  }
  
  void _initializePlayer() {
    if (_isInitializing) return;
    
    _isInitializing = true;
    try {
      _player = AudioPlayer();
      debugPrint('✅ AudioPlayer 초기화 성공');
    } catch (e) {
      debugPrint('❌ AudioPlayer 초기화 오류: $e');
      if (e.toString().contains('Platform player already exists')) {
        debugPrint('ℹ️ 기존 AudioPlayer를 재사용합니다');
        // 기존 플레이어가 있다면 그대로 사용 (null 유지)
        _player = null;
      } else {
        // 다른 오류의 경우 재시도
        try {
          _player = AudioPlayer();
        } catch (e2) {
          debugPrint('❌ AudioPlayer 재시도 실패: $e2');
        }
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
