import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;

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

  VoiceService() {
    _initialize();
  }

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
    if(!_isCycleRunning) return;

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

  /// 인식된 명령 확인 (실행은 하지 않음)
  void _executeCommand(String intent, Map<String, dynamic> entities) {
    _addDebugLog("=== 명령 인식 완료 ===");
    _addDebugLog("인식된 의도: $intent");
    _addDebugLog("추출된 엔티티: $entities");
    
    switch (intent) {
      case 'CAMERA':
        _setStatus("카메라 명령 인식됨");
        break;
      case 'NAVIGATION':
        _setStatus("길찾기 명령 인식됨");
        break;
      case 'EMERGENCY_CALL':
        _setStatus("보호자 호출 명령 인식됨");
        break;
      case 'SETTINGS':
        _setStatus("설정 명령 인식됨");
        break;
      case 'HELP':
        _setStatus("도움말 명령 인식됨");
        break;
      case 'DESCRIBE_SCENE':
        _setStatus("주변 설명 명령 인식됨");
        break;
      case 'STOP_LISTENING':
        _setStatus("중단 명령 인식됨");
        stopAutoRecognitionCycle();
        return;
      default:
        _setStatus("❓ 알 수 없는 명령: $intent");
        break;
    }
    
    _addDebugLog("=== 명령 처리 완료 ===");
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