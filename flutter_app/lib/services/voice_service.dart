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
String get baseUrl => dotenv.env['BACKEND_BASE_URL'] ?? 'https://aeye-backend-app-jp.azurewebsites.net';

  // === 상태 관리 ===
  VoiceState _currentState = VoiceState.idle;
  String _lastRecognizedText = "";
  String _statusMessage = "초기화 중...";
  final List<String> _debugLogs = [];
  bool _isDisposed = false; // 생명주기 상태 추적

  // === 녹음 관련 ===
  String? _currentRecordingPath;

  // === 자동 인식 사이클 제어 ===
  bool _isCycleRunning = false;

  // === TTS 구독 관리 ===
  StreamSubscription? _ttsSubscription;
  bool _isSpeaking = false; // 현재 음성 출력 중인지 확인



  // === 음성 속도 설정 ===
  double? _currentVoiceSpeed; // 사용자가 설정한 음성 속도
  static const double _defaultSpeed = 0.9; // 기본 속도 (사용자 설정 전)
  
  // === 음성 성별 설정 ===
  String _currentVoiceGender = 'female'; // 사용자가 설정한 음성 성별

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
  
  /// 음성 성별 설정 (사용자가 VoiceScreen에서 설정)
  void setVoiceGender(String gender) {
    _currentVoiceGender = gender;
    debugPrint('🎭 음성 성별 설정됨: $gender');
  }
  
  String _normalizeGender(String g) {
    final v = g.toLowerCase().trim();
    if (v.startsWith('m') || v.contains('남')) return 'male';
    return 'female';
  }

  // === TTS 큐 관리 ===
  final List<String> _ttsQueue = [];
  bool _isProcessingTtsQueue = false;
  
  // === 파일 정리 관리 ===
  final Set<String> _tempFiles = {};
  Timer? _cleanupTimer;

  /// 서비스 초기화 및 환경 체크
  Future<void> _initialize() async {
    _addDebugLog("=== VoiceService 초기화 시작 ===");

    // 마이크 권한 확인
    await _checkMicrophonePermission();
    
    // 사용자 설정 로드
    await _loadUserSettings();
    
    // 주기적 파일 정리 시작
    _startPeriodicCleanup();

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
    // 서비스가 dispose된 경우 중단
    if (_isDisposed) return;
    
    // 사이클 실행 플래그가 꺼지면 모든 동작 중단
    if (!_isCycleRunning) return;

    // 음성 출력 중이면 잠시 대기 후 재시도 (자기 음성 인식 방지)
    if (_isSpeaking) {
      Future.delayed(const Duration(milliseconds: 500), () {
        if (!_isDisposed && _isCycleRunning && !_isSpeaking) {
          _runSingleRecognition();
        }
      });
      return;
    }

    // 기존 녹음 시작 함수 호출(타임아웃 20초 걸어놧음)
    await startListening();
  }

  /// 자동 인식 사이클 내부 단일 인식 실행

  /// 음성 녹음 시작
  Future<void> startListening() async {
    // 서비스가 dispose된 경우 중단
    if (_isDisposed) return;
    
    if (_currentState != VoiceState.idle) return;

    // 음성 안내(TTS) 중에는 STT 시작 금지 (에코/루프 방지)
    if (_isSpeaking) {
      _addDebugLog("현재 음성 출력 중 - 인식 대기");
      return;
    }

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
    // 서비스가 dispose된 경우 중단
    if (_isDisposed) return;
    
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

      if (!_isDisposed && _isCycleRunning) {
        // 자동 인식 사이클이 활성화 상태일 때, 0.5초 후 다음 인식 시작 (더 빠른 응답)
        Future.delayed(const Duration(milliseconds: 500), () {
          if (!_isDisposed && _isCycleRunning) {
            _runSingleRecognition();
          }
        });
      }
    }
  }

  // 생성자 - NavigatorKey는 더 이상 사용하지 않음 (StepScreen에서 직접 카메라 관리)
  VoiceService({GlobalKey<NavigatorState>? navigatorKey}) {
    _initialize();
  }

  
  

  Future<void> _executeCommand(
    String command,
    Map<String, dynamic> entities,
  ) async {
    _addDebugLog("🎯 인식된 명령: $command, 엔티티: $entities");
    _setStatus("명령 실행: $command");

    switch (command) {
      case 'STOP_LISTENING':
        stopAutoRecognitionCycle();
        await speak("음성 인식을 중단합니다.", priority: true);
        break;
      default:
        _setStatus("알 수 없는 명령: $command");
        _addDebugLog('알 수 없는 명령: $command');
        break;
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

  /// 디버그 로그 추가 (안전한 버전)
  void _addDebugLog(String message) {
    if (_isDisposed) return;
    final timestamp = DateTime.now().toIso8601String().substring(11, 23);
    _debugLogs.add("[$timestamp] $message");
    // 콘솔에도 출력 (개발용)
    debugPrint("[$timestamp] $message");
    _safeNotifyListeners();
  }

  /// 상태 메시지 설정 (안전한 버전)
  void _setStatus(String message) {
    if (_isDisposed) return;
    _statusMessage = message;
    _safeNotifyListeners();
  }

  /// 상태 변경 (안전한 버전)
  void _setState(VoiceState newState) {
    if (_isDisposed) return;
    if (_currentState != newState) {
      _currentState = newState;
      _safeNotifyListeners();
    }
  }
  
  /// 안전한 리스너 알림
  void _safeNotifyListeners() {
    if (!_isDisposed) {
      try {
        notifyListeners();
      } catch (e) {
        debugPrint('⚠️ notifyListeners 호출 실패 (위젯 dispose됨): $e');
      }
    }
  }


  /// 로그 초기화 (안전한 버전)
  void clearLogs() {
    if (_isDisposed) return;
    _debugLogs.clear();
    _lastRecognizedText = "";
    _addDebugLog("로그 초기화됨");
  }

  /// 강제 중단 (안전한 버전)
  void forceStop() {
    if (_isDisposed) return;
    
    if (_currentState == VoiceState.listening) {
      try {
        _audioRecorder.stop();
      } catch (e) {
        debugPrint('⚠️ 녹음 중단 중 오류: $e');
      }
    }
    _setState(VoiceState.idle);
    _addDebugLog("강제 중단됨");
    _setStatus("중단됨");
  }

  /// 개선된 TTS 음성 출력 - 안정성과 성능 향상
  Future<void> speak(
    String text, {
    String? gender,
    double? speed,
    bool priority = false,
  }) async {
    // 빈 텍스트는 즉시 반환
    if (text.trim().isEmpty) return;
    
    // 우선순위 메시지가 아니면 큐에 추가
    if (!priority && _isProcessingTtsQueue) {
      _ttsQueue.add(text);
      return;
    }
    
    // 안전한 오디오 중단
    await _stopCurrentTts();
    
    try {
      _isSpeaking = true;
      _isProcessingTtsQueue = true;
      
      // 현재 설정된 성별과 속도 사용 (정규화/범위 보정)
      final currentGender = _normalizeGender(gender ?? _currentVoiceGender);
      final currentSpeed = (speed ?? getCurrentSpeed()).clamp(0.25, 4.0).toDouble();
      
      // 사용자 UUID 확보
      String? uuid;
      try {
        uuid = await ApiService().getCurrentUserUuid();
      } catch (_) {
        uuid = null;
      }
      if (uuid == null || uuid.trim().isEmpty) {
        // 사용자 미등록 시 1회 초기화 시도 후 재조회
        try {
          await ApiService().initializeUser();
          uuid = await ApiService().getCurrentUserUuid();
        } catch (_) {}
      }
      if (uuid == null || uuid.trim().isEmpty) {
        _isSpeaking = false;
        _isProcessingTtsQueue = false;
        debugPrint('❌ TTS 요청 불가: 사용자 UUID를 찾을 수 없습니다');
        return;
      }

      // TTS API 호출
      final response = await _httpClient
          .post(
            Uri.parse('$baseUrl/api/users/voice'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'user_id': uuid,
              'text': text,
              'gender': currentGender,
              'speed': currentSpeed,
            }),
          )
          .timeout(const Duration(seconds: 8));

      if (response.statusCode == 200) {
        // 응답 데이터 유효성 검사
        if (response.bodyBytes.length < 100) {
          _isSpeaking = false;
          _isProcessingTtsQueue = false;
          return;
        }

        // 안전한 파일 생성
        final audioFile = await _createSafeTempFile();
        
        try {
          // 오디오 데이터 저장
          await audioFile.writeAsBytes(response.bodyBytes);
          _tempFiles.add(audioFile.path);
          
          // 안전한 오디오 재생
          await _playAudioSafely(audioFile);
          
        } catch (playError) {
          debugPrint('❌ TTS 재생 오류: $playError');
          _isSpeaking = false;
          await _cleanupFile(audioFile.path);
        }
      } else {
        _isSpeaking = false;
        debugPrint('❌ TTS HTTP ${response.statusCode}: ${response.body}');
      }
    } catch (e) {
      _isSpeaking = false;
      debugPrint('❌ TTS 요청 실패: $e');
    } finally {
      _isProcessingTtsQueue = false;
      
      // 큐에 대기 중인 TTS가 있으면 다음 실행
      if (!_isDisposed && _ttsQueue.isNotEmpty) {
        final nextText = _ttsQueue.removeAt(0);
        Future.delayed(const Duration(milliseconds: 200), () {
          if (!_isDisposed) {
            speak(nextText, gender: gender, speed: speed);
          }
        });
      }
    }
  }

  /// 현재 TTS 안전하게 중단
  Future<void> _stopCurrentTts() async {
    if (_isSpeaking) {
      try {
        await _ttsSubscription?.cancel();
        _ttsSubscription = null;
        
        await _audioPlayer.stop();
        await Future.delayed(const Duration(milliseconds: 100)); // 완전한 정리 대기
        
        _isSpeaking = false;
      } catch (e) {
        debugPrint('⚠️ TTS 중단 중 오류 (무시됨): $e');
        _isSpeaking = false;
      }
    }
  }

  /// 안전한 임시 파일 생성
  Future<File> _createSafeTempFile() async {
    final directory = await getApplicationDocumentsDirectory();
    final timestamp = DateTime.now().microsecondsSinceEpoch; // 마이크로초로 변경
    final randomSuffix = math.Random().nextInt(1000);
    return File('${directory.path}/tts_${timestamp}_$randomSuffix.mp3');
  }

  /// 안전한 오디오 재생
  Future<void> _playAudioSafely(File audioFile) async {
    final player = _audioPlayer;
    
    // 플레이어 초기화
    await player.setVolume(1.0);
    await player.setAudioSource(AudioSource.file(audioFile.path));
    
    // 재생 시작
    await player.play();
    
    // 완료 리스너 설정 (생명주기 체크 추가)
    _ttsSubscription = player.processingStateStream
        .where((state) => state == ProcessingState.completed)
        .take(1)
        .listen((_) async {
          if (!_isDisposed) {
            _isSpeaking = false;
            await _cleanupFile(audioFile.path);
            
            // 다음 큐 처리를 위한 짧은 대기
            await Future.delayed(const Duration(milliseconds: 100));
          }
        });
  }

  /// 파일 정리
  Future<void> _cleanupFile(String filePath) async {
    _tempFiles.remove(filePath);
    try {
      final file = File(filePath);
      if (await file.exists()) {
        await file.delete();
      }
    } catch (e) {
      debugPrint('⚠️ TTS 파일 정리 실패: $e');
    }
  }

  /// 주기적 파일 정리 (메모리 누수 방지)
  void _startPeriodicCleanup() {
    _cleanupTimer?.cancel();
    _cleanupTimer = Timer.periodic(const Duration(minutes: 5), (_) async {
      final directory = await getApplicationDocumentsDirectory();
      final files = directory.listSync()
          .where((entity) => entity is File && entity.path.contains('tts_'))
          .cast<File>();
      
      for (final file in files) {
        try {
          final stats = await file.stat();
          final age = DateTime.now().difference(stats.modified);
          
          // 10분 이상 된 TTS 파일 삭제
          if (age.inMinutes > 10) {
            await file.delete();
            debugPrint('🗑️ 오래된 TTS 파일 정리: ${file.path}');
          }
        } catch (e) {
          debugPrint('⚠️ TTS 파일 정리 중 오류: $e');
        }
      }
    });
  }

  @override
  void dispose() {
    // dispose 플래그 설정 (가장 먼저)
    _isDisposed = true;
    
    // 자동 인식 사이클 즉시 중단
    _isCycleRunning = false;
    
    // TTS 큐와 현재 재생 정리
    _ttsQueue.clear();
    _stopCurrentTts(); // await 제거 (dispose는 동기적으로)
    
    // 정리 타이머 중지
    _cleanupTimer?.cancel();
    
    // 비동기 정리 작업들을 백그라운드에서 실행
    _cleanupResourcesAsync();
    
    // 기존 동기 리소스 정리
    try {
      _httpClient.close();
      _ttsSubscription?.cancel();
      _audioRecorder.dispose();
    } catch (e) {
      debugPrint('⚠️ dispose 리소스 정리 중 오류: $e');
    }
    
    super.dispose();
  }
  
  /// 비동기 리소스 정리 (백그라운드 실행)
  Future<void> _cleanupResourcesAsync() async {
    try {
      // 남은 임시 파일들 정리
      for (final filePath in _tempFiles) {
        try {
          final file = File(filePath);
          if (await file.exists()) {
            await file.delete();
          }
        } catch (e) {
          debugPrint('⚠️ dispose 파일 정리 실패: $e');
        }
      }
      _tempFiles.clear();
    } catch (e) {
      debugPrint('⚠️ 비동기 리소스 정리 실패: $e');
    }
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
