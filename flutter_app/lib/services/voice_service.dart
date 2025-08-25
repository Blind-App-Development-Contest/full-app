import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

/// 음성 인식 상태

enum VoiceState { idle, listening, processing }

class VoiceService with ChangeNotifier {
  final Record _audioRecorder = Record();

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

  // === Measurement Callbacks ===
  Function(Map<String, dynamic>)? onMeasurementComplete;
  Function(Map<String, dynamic>)? onMeasurementStart;

  // === Getters ===
  VoiceState get currentState => _currentState;
  String get lastRecognizedText => _lastRecognizedText;
  String get statusMessage => _statusMessage;
  List<String> get debugLogs => _debugLogs;

  /// 서비스 초기화 및 환경 체크
  Future<void> _initialize() async {
    _addDebugLog("=== VoiceService 초기화 시작 ===");

    // 마이크 권한 확인
    await _checkMicrophonePermission();

    _setStatus("초기화 완료 - 음성 인식 준비됨");
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
    if (_isCycleRunning) return; // 이미 실행중이면 무시

    _addDebugLog("자동 인식 사이클 시작 요청");

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
        _addDebugLog("STT 실패 또는 빈 텍스트 수신");
        _setStatus("음성 인식 실패");
        _setState(VoiceState.idle);
        return;
      }
      _lastRecognizedText = transcribedText;
      _addDebugLog("STT 성공: $transcribedText");

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

  // === 네비게이션 제어 ===
  // main.dart에서 생성된 GlobalKey를 받아 저장합니다.
  final GlobalKey<NavigatorState> _navigatorKey;

  // 생성자를 수정하여 GlobalKey를 받도록 합니다.
  VoiceService({required GlobalKey<NavigatorState> navigatorKey})
    : _navigatorKey = navigatorKey {
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
    _addDebugLog("인식된 명령: $command, 엔티티: $entities");
    _setStatus("명령 실행: $command");

    switch (command) {
      case 'MEASURE_STEP':
      case 'BEGIN_WALKING':
      case 'FOOTSTEP_MEASUREMENT_START':
      case 'FOOTSTEP_MEASUREMENT_BEGIN':
        _setStatus("보폭 측정 시작 명령 인식됨");
        _startMeasurementAndNavigate();
        break;
      case 'FOOTSTEP_MEASUREMENT_COMPLETE':
      case 'STOP_MEASUREMENT':
      case 'FINISH_MEASURING':
      case 'END_WALKING':
      case 'MEASUREMENT_COMPLETE':
        _setStatus("보폭 측정 완료 명령 인식됨");
        await stopMeasurementWorkflow();
        break;
      case 'STOP_LISTENING':
      case 'FOOTSTEP_MEASUREMENT_CANCEL':
        _setStatus("중단 명령 인식됨");
        stopAutoRecognitionCycle();
        break;
      default:
        _setStatus("알 수 없는 명령: $command");
        _addDebugLog('알 수 없는 명령: $command');
        break;
    }
  }

  /// 측정 세션 시작 및 카메라 화면으로 이동
  Future<void> _startMeasurementAndNavigate() async {
    // 서버에 측정 시작 요청
    final success = await _startMeasurementSession();

    // 서버 요청이 성공했을 때만 카메라 화면으로 이동합니다.
    if (success) {
      // GlobalKey를 사용하여 현재 context 없이도 화면 전환이 가능합니다.
      _navigatorKey.currentState?.pushNamed('/measurement-camera');
      _addDebugLog("카메라 화면으로 이동합니다.");
    } else {
      _addDebugLog("서버 요청 실패로 카메라 화면으로 이동하지 않습니다.");
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
            const Duration(seconds: 10),
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
    const int maxRetries = 2;
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

  /// STT API 호출 및 상세 디버깅 (타임아웃 30초)
  Future<Map<String, dynamic>> _convertSpeechToText(String filePath) async {
    final url = '$baseUrl/api/users/speech/transcribe';

    // 네트워크 상태 및 설정 로깅
    _addDebugLog('네트워크 상태 확인 중...');
    _addDebugLog('서버 주소: $baseUrl');
    _addDebugLog('요청 타임아웃: 60초');
    _addDebugLog('재시도 횟수: 3회');
    _addDebugLog("STT 서버 호출 시작: $url");

    try {
      // HTTP 클라이언트 생성
      final client = http.Client();

      // HTTP 요청 생성
      final request = http.MultipartRequest('POST', Uri.parse(url));

      // 파일 첨부
      request.files.add(await http.MultipartFile.fromPath('file', filePath));
      _addDebugLog("오디오 파일 첨부 완료 (경로: $filePath)");

      // 요청 전송 및 응답 받기 (60초 타임아웃)
      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 60),
        onTimeout: () {
          client.close();
          throw TimeoutException('STT request timed out after 60 seconds');
        },
      );

      final response = await http.Response.fromStream(streamedResponse);
      client.close();

      _addDebugLog("서버 응답 수신: ${response.statusCode}");
      _addDebugLog("응답 시간: ${DateTime.now().toIso8601String()}");

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog("✅ STT 성공 - 텍스트 길이: ${result['text']?.length ?? 0}");
        _addDebugLog("인식된 텍스트: ${result['text']}");
        return result;
      } else {
        _addDebugLog("❌ STT 서버 오류: ${response.statusCode}");
        _addDebugLog("서버 응답: ${response.body}");
        throw HttpException('STT server error: ${response.statusCode}');
      }
    } on TimeoutException catch (e) {
      _addDebugLog("❌ STT 타임아웃: $e");
      rethrow;
    } on SocketException catch (e) {
      _addDebugLog("❌ STT 네트워크 연결 오류: $e");
      rethrow;
    } catch (e) {
      _addDebugLog("❌ STT 연결 예외: $e");
      rethrow;
    }
  }

  /// NLU 백엔드 서버를 호출하는 함수 (타임아웃 15초)
  /// 백엔드에서 다음 측정 관련 패턴들을 인식해야 함:
  /// - '측정 시작', '보폭 측정' → START_MEASUREMENT
  /// - '측정 완료', '측정 끝' → STOP_MEASUREMENT
  /// - '걷기 시작', '보폭 재기' → MEASURE_STEP
  /// - '걷기 끝', '측정 마침' → FINISH_MEASURING
  Future<Map<String, dynamic>> _getIntentFromText(String commandText) async {
    final url = '$baseUrl/api/users/speech/recognition';
    _addDebugLog("NLU 서버 호출: $url");
    _addDebugLog("분석할 텍스트: $commandText");

    try {
      final response = await http
          .post(
            Uri.parse(url),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'command_text': commandText}),
          )
          .timeout(
            const Duration(seconds: 15),
            onTimeout: () {
              throw TimeoutException('NLU request timed out after 15 seconds');
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

      final response = await http
          .post(
            Uri.parse('$baseUrl/api/users/measurement/session/start'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'user_id': 'current_user'}),
          )
          .timeout(
            const Duration(seconds: 10),
            onTimeout: () {
              throw TimeoutException(
                'Measurement start request timed out after 10 seconds',
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

  /// 측정 프레임 업로드 (올바른 파일 업로드 방식)
  Future<Map<String, dynamic>> uploadMeasurementFrame(
    File imageFile,
    String userId,
  ) async {
    try {
      _addDebugLog('📤 프레임 업로드 시작: ${imageFile.path}');

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

      _addDebugLog('프레임 파일 크기: ${await imageFile.length()} bytes');
      _addDebugLog('사용자 ID: $userId');

      // 요청 전송 (타임아웃 15초)
      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 15),
        onTimeout: () {
          throw TimeoutException('프레임 업로드 타임아웃 (15초)');
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

  @override
  void dispose() {
    _audioRecorder.dispose();
    super.dispose();
  }
}
