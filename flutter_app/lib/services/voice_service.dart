import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

/// 음성 인식 상태

enum VoiceState { idle, listening, processing }

/// OpenAI 음성 인식 디버깅 정보
class RecognitionDebugInfo {
  final String timestamp;
  final String filePath;
  final int fileSizeBytes;
  final Duration recordingDuration;
  final int apiResponseCode;
  final Duration apiResponseTime;
  final String rawApiResponse;
  final bool success;
  final String errorDetails;

  RecognitionDebugInfo({
    required this.timestamp,
    required this.filePath,
    required this.fileSizeBytes,
    required this.recordingDuration,
    required this.apiResponseCode,
    required this.apiResponseTime,
    required this.rawApiResponse,
    required this.success,
    required this.errorDetails,
  });
}

class VoiceService with ChangeNotifier {
  final Record _audioRecorder = Record();

  // === 상태 관리 ===
  VoiceState _currentState = VoiceState.idle;
  String _lastRecognizedText = "";
  String _statusMessage = "초기화 중...";
  List<String> _debugLogs = [];
  RecognitionDebugInfo? _lastDebugInfo;

  // === 녹음 관련 ===
  DateTime? _recordingStartTime;
  String? _currentRecordingPath;

  // === 자동 인식 사이클 제어 ===
  bool _isCycleRunning = false;

  // === Getters ===
  VoiceState get currentState => _currentState;
  String get lastRecognizedText => _lastRecognizedText;
  String get statusMessage => _statusMessage;
  List<String> get debugLogs => _debugLogs;
  RecognitionDebugInfo? get lastDebugInfo => _lastDebugInfo;

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
      _recordingStartTime = DateTime.now();

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
      // 1. STT 서버 호출하여 텍스트 얻기
      _setStatus("음성을 텍스트로 변환 중...");
      final sttResult = await _convertSpeechToText(path);
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
      _executeCommand(intent, nluResult['entities']);
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

  void _executeCommand(String command, Map<String, dynamic> entities) {
    _addDebugLog("인식된 명령: $command, 엔티티: $entities");
    _setStatus("명령 실행: $command");

    switch (command) {
      case 'MEASURE_STEP':
      case 'BEGIN_WALKING':
        _setStatus("보폭 측정 시작 명령 인식됨");
        _startMeasurementAndNavigate();
        break;
      case 'STOP_MEASUREMENT':
      case 'FINISH_MEASURING':
      case 'END_WALKING':
        _setStatus("보폭 측정 완료 명령 인식됨");
        _stopMeasurementAndNavigate();
        break;
      case 'STOP_LISTENING':
        _setStatus("중단 명령 인식됨");
        stopListening();
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

  /// 측정 세션 중지 및 이전 화면으로 복귀
  Future<void> _stopMeasurementAndNavigate() async {
    // 서버에 측정 중지 요청
    final success = await _stopMeasurementSession();

    // 서버 요청이 성공했을 때만 이전 화면으로 돌아갑니다.
    if (success) {
      // 현재 화면(카메라 화면)을 닫고 이전 화면으로 돌아갑니다.
      _navigatorKey.currentState?.pop();
      _addDebugLog("이전 화면으로 복귀합니다.");
    }
  }

  /// OpenAI Whisper API 호출 및 상세 디버깅
  Future<Map<String, dynamic>> _convertSpeechToText(String filePath) async {
    final url = 'http://192.168.45.217:8000/api/users/speech/transcribe';
    _addDebugLog("백엔드 서버 호출 시작: $url");

    try {
      // HTTP 요청 생성
      var request = http.MultipartRequest('POST', Uri.parse(url));
      // 파일 첨부
      request.files.add(await http.MultipartFile.fromPath('file', filePath));
      _addDebugLog("오디오 파일 첨부 완료");

      var response = await http.Response.fromStream(await request.send());

      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        _addDebugLog("❌ STT 서버 오류: ${response.statusCode} ${response.body}");
        return {'text': ''};
      }
    } catch (e) {
      _addDebugLog("❌ 백엔드 서버 예외: $e");
      return {'text': ''};
    }
  }

  /// NLU 백엔드 서버를 호출하는 함수
  /// 백엔드에서 다음 측정 관련 패턴들을 인식해야 함:
  /// - '측정 시작', '보폭 측정' → START_MEASUREMENT
  /// - '측정 완료', '측정 끝' → STOP_MEASUREMENT
  /// - '걷기 시작', '보폭 재기' → MEASURE_STEP
  /// - '걷기 끝', '측정 마침' → FINISH_MEASURING
  Future<Map<String, dynamic>> _getIntentFromText(String commandText) async {
    final url = 'http://192.168.45.217:8000/api/users/speech/recognition';
    _addDebugLog("NLU 서버 호출: $url");

    try {
      final response = await http.post(
        Uri.parse(url),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'command_text': commandText}),
      );

      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        _addDebugLog("❌ NLU 서버 오류: ${response.statusCode} ${response.body}");
        return {'intent': 'error'};
      }
    } catch (e) {
      _addDebugLog("❌ NLU 서버 연결 예외: $e");
      return {'intent': 'error'};
    }
  }

  /// 디버그 로그 추가
  void _addDebugLog(String message) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 23);
    _debugLogs.add("[$timestamp] $message");
    print(message); // 콘솔에도 출력
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

  /// 보폭 측정 세션 시작
  Future<bool> _startMeasurementSession() async {
    try {
      _addDebugLog("=== 측정 세션 시작 요청 ===");

      final response = await http.post(
        Uri.parse(
          'http://192.168.45.217:8000/api/users/measurement/session/start',
        ),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'user_id': 'current_user'}),
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
        _setStatus("측정 시작 실패");
        return false;
      }
    } catch (e) {
      _addDebugLog('❌ 측정 시작 오류: $e');
      _setStatus("측정 시작 중 오류 발생");
      return false;
    }
  }

  /// 보폭 측정 세션 완료
  Future<bool> _stopMeasurementSession() async {
    try {
      _addDebugLog("=== 측정 세션 완료 요청 ===");

      final response = await http.post(
        Uri.parse(
          'http://192.168.45.217:8000/api/users/measurement/session/stop',
        ),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'user_id': 'current_user'}),
      );

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        _addDebugLog('✅ 측정이 완료되었습니다');
        _addDebugLog('세션 상태: ${result['status']}');
        _addDebugLog('카메라 모드: ${result['camera_mode']}');

        // 측정 결과가 있으면 표시
        if (result['final_result'] != null) {
          final finalResult = result['final_result'];
          _addDebugLog('총 걸음수: ${finalResult['total_steps']}');
          _addDebugLog('프레임 수: ${finalResult['frame_count']}');
        }

        _setStatus("보폭 측정이 완료되었습니다");
        return true;
      } else {
        _addDebugLog('❌ 측정 완료 실패: ${response.statusCode}');
        _setStatus("측정 완료 실패");
        return false;
      }
    } catch (e) {
      _addDebugLog('❌ 측정 완료 오류: $e');
      _setStatus("측정 완료 중 오류 발생");
      return false;
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
