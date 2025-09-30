// lib/map_screen.dart
import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../directions_api.dart';
import '../services/voice_service.dart';
import '../utils/voice_utils.dart';
import 'package:html/parser.dart' show parse;
import '../constants/app_colors.dart';
import 'package:flutter/services.dart';

/// 음성 안내 우선순위 정의
enum VoiceGuidancePriority {
  emergency(3), // 긴급 (안전 관련)
  navigation(2), // 경로 안내
  interaction(1), // 사용자 상호작용
  status(0); // 상태 안내

  const VoiceGuidancePriority(this.level);
  final int level;
}

/// 음성 안내 큐 아이템
class _VoiceGuidanceItem {
  final String text;
  final VoiceGuidancePriority priority;
  final DateTime timestamp;
  final bool canBeInterrupted;

  _VoiceGuidanceItem({
    required this.text,
    required this.priority,
    this.canBeInterrupted = true,
  }) : timestamp = DateTime.now();

  /// 우선순위 비교 (높은 우선순위가 먼저)
  int compareTo(_VoiceGuidanceItem other) {
    final priorityCompare = other.priority.level.compareTo(priority.level);
    if (priorityCompare != 0) return priorityCompare;
    // 같은 우선순위면 시간 순서
    return timestamp.compareTo(other.timestamp);
  }
}

class MapScreen extends StatefulWidget {
  final String backendBaseUrl;
  const MapScreen({super.key, required this.backendBaseUrl});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  late final DirectionsApi _api;
  final Completer<NaverMapController> _controller = Completer();

  NaverMapController? _map;
  NPolylineOverlay? _routePolyline;
  NMarker? _startMarker;
  NMarker? _endMarker;
  NMarker? _hereMarker; // 현재 위치 표시용

  String _status = '대기';
  final _destinationController = TextEditingController();
  List<Map<String, dynamic>> _instructions = []; // 길안내 단계들
  bool _showInstructions = false; // 패널 표시 여부
  List<Map<String, dynamic>> _placeSuggestions = []; // 장소 추천 목록
  bool _showSuggestions = false; // 추천 목록 표시 여부
  int _selectedSuggestionIndex = -1; // 선택된 추천 항목 인덱스
  bool _waitingForReadConfirmation = false; // 음성 안내 확인 대기 상태
  bool _isListening = false; // 음성인식 상태
  bool _mapAuthFailed = false; // 맵 인증 실패 상태

  // VoiceService 연동
  VoiceService? _voiceService;

  // 음성 길안내 관련 상태 변수
  StreamSubscription<Position>? _positionStream;
  int _currentInstructionIndex = 0;
  bool _isNavigating = false;

  Timer? _statusAnnouncementTimer; // 주기적 상태 안내 타이머

  // === 음성 안내 큐 시스템 ===
  final List<_VoiceGuidanceItem> _voiceQueue = [];
  bool _isProcessingQueue = false;
  Timer? _queueProcessTimer;

  @override
  void initState() {
    super.initState();
    _api = DirectionsApi(widget.backendBaseUrl);
    _initializeVoiceService();
    _checkMapAuthStatus();
  }

  void _checkMapAuthStatus() {
    // 맵 로드 후 인증 상태 확인
    Future.delayed(const Duration(seconds: 3), () {
      if (mounted && _status == '대기' && _map == null) {
        debugPrint('⚠️ 맵 로딩 시간 초과 - 인증 실패로 추정');
        setState(() {
          _mapAuthFailed = true;
          _status = '맵 인증 실패';
        });
      }
    });
  }

  @override
  void dispose() {
    _stopVoiceGuidance(); // 음성 안내 중지
    _statusAnnouncementTimer?.cancel(); // 상태 안내 타이머 취소
    _clearVoiceQueue(); // 음성 안내 큐 정리
    // VoiceService 자동 인식 중지
    try {
      _voiceService?.stopAutoRecognitionCycle();
      debugPrint('✅ MapScreen: 자동 인식 사이클 중지 완료');
    } catch (e) {
      debugPrint('❌ MapScreen: 자동 인식 중지 실패: $e');
    }

    // 음성 인식 상태 초기화
    if (_isListening) {
      try {
        _voiceService?.stopListeningAndProcess();
        _voiceService?.removeListener(_handleVoiceRecognitionResult);
        debugPrint('✅ MapScreen: 진행 중인 음성 인식 중지 완료');
      } catch (e) {
        debugPrint('❌ MapScreen: 음성 인식 중지 실패: $e');
      }
    }

    _destinationController.dispose();
    super.dispose();
  }

  void _initializeVoiceService() {
    try {
      _voiceService = context.read<VoiceService>();
      debugPrint("✅ MapScreen VoiceService 초기화 성공");

      // 지도 화면 진입 시 시각장애인용 안내
      _announceMapScreenEntry();
    } catch (e) {
      debugPrint("❌ MapScreen VoiceService 초기화 실패: $e");
    }
  }

  /// 지도 화면 진입 시 시각장애인용 상세 안내
  Future<void> _announceMapScreenEntry() async {
    if (_voiceService == null) return;

    try {
      await Future.delayed(const Duration(milliseconds: 500));

      await _speakText(
        "길찾기 모드입니다. "
        "목적지를 입력하면 음성으로 경로를 안내해드립니다.",
      );

      await Future.delayed(const Duration(milliseconds: 800));

      await _speakText(
        "화면 하단의 입력창에 목적지를 말하거나 입력하세요. "
        "음성인식 버튼을 사용할 수 있습니다.",
      );
    } catch (e) {
      debugPrint('❌ 지도 화면 진입 안내 실패: $e');
    }
  }

  /// 경로 안내 시작 시 시각장애인용 상세 안내
  Future<void> _announceRouteStart() async {
    if (_voiceService == null || _instructions.isEmpty) return;

    try {
      // 1단계: 경로 안내 시작 알림
      await _speakText("경로 안내 시작!", priority: VoiceGuidancePriority.navigation);

      await Future.delayed(const Duration(milliseconds: 800));

      // 2단계: 전체 경로 정보 안내
      final totalSteps = _instructions.length;
      await _speakText(
        "총 $totalSteps단계의 경로로 안내해드리겠습니다.",
        priority: VoiceGuidancePriority.navigation,
      );

      await Future.delayed(const Duration(milliseconds: 600));

      // 3단계: 첫 번째 안내 시작
      final firstInstruction =
          _instructions.first['instruction_html'] as String;
      await _speakText(
        "첫 번째 안내입니다. $firstInstruction",
        priority: VoiceGuidancePriority.navigation,
      );

      // 4단계: 주기적 상태 안내 시작
      _startPeriodicStatusAnnouncement();
    } catch (e) {
      debugPrint('❌ 경로 안내 시작 음성 안내 실패: $e');
    }
  }

  /// 주기적 상태 안내 시작 (시각장애인용)
  void _startPeriodicStatusAnnouncement() {
    _statusAnnouncementTimer?.cancel();

    // 30초마다 현재 상태 안내
    _statusAnnouncementTimer = Timer.periodic(const Duration(seconds: 30), (
      timer,
    ) {
      if (_isNavigating && _currentInstructionIndex < _instructions.length) {
        _announceCurrentStatus();
      } else {
        timer.cancel();
      }
    });
  }

  /// 현재 진행 상태 안내 (시각장애인용)
  Future<void> _announceCurrentStatus() async {
    if (_voiceService == null) return;

    try {
      final remainingSteps = _instructions.length - _currentInstructionIndex;
      final currentStep = _currentInstructionIndex + 1;

      await _speakText(
        "현재 ${_instructions.length}단계 중 $currentStep단계 진행 중입니다. "
        "남은 안내는 $remainingSteps단계입니다.",
      );
    } catch (e) {
      debugPrint('❌ 현재 상태 음성 안내 실패: $e');
    }
  }

  /// 다음 단계 안내 시 상세 음성 피드백 (시각장애인용)
  Future<void> _announceNextStep(String instruction) async {
    if (_voiceService == null) return;

    try {
      final currentStep = _currentInstructionIndex + 1;
      final totalSteps = _instructions.length;

      // 단계 정보와 함께 안내
      await _speakText(
        "$totalSteps단계 중 $currentStep단계입니다. $instruction",
        priority: VoiceGuidancePriority.navigation,
      );
    } catch (e) {
      debugPrint('❌ 다음 단계 음성 안내 실패: $e');
    }
  }

  /// 목적지 도착 시 상세 음성 안내 (시각장애인용)
  Future<void> _announceDestinationArrival() async {
    if (_voiceService == null) return;

    try {
      await _speakEmergency("목적지 도착!");

      await Future.delayed(const Duration(milliseconds: 800));

      await _speakText(
        "경로 안내를 종료합니다.",
        priority: VoiceGuidancePriority.navigation,
      );

      await Future.delayed(const Duration(milliseconds: 600));

      await _speakText(
        "새로운 경로를 검색하거나 다른 모드를 이용하세요.",
        priority: VoiceGuidancePriority.status,
      );
    } catch (e) {
      debugPrint('❌ 목적지 도착 음성 안내 실패: $e');
    }
  }

  // === 음성 안내 큐 시스템 메서드들 ===

  /// 음성 안내 큐에 추가
  void _addToVoiceQueue(
    String text,
    VoiceGuidancePriority priority, {
    bool canBeInterrupted = true,
  }) {
    final item = _VoiceGuidanceItem(
      text: text,
      priority: priority,
      canBeInterrupted: canBeInterrupted,
    );

    _voiceQueue.add(item);
    _voiceQueue.sort((a, b) => a.compareTo(b)); // 우선순위 순으로 정렬

    debugPrint(
      '📢 음성 안내 큐 추가: [${priority.name}] $text (큐 크기: ${_voiceQueue.length})',
    );

    _processVoiceQueue();
  }

  /// 음성 안내 큐 처리
  void _processVoiceQueue() async {
    if (_isProcessingQueue || _voiceQueue.isEmpty || _voiceService == null) {
      return;
    }

    _isProcessingQueue = true;

    try {
      // VoiceService가 음성 출력 중이면 대기
      if (_voiceService!.isSpeaking) {
        debugPrint('🔊 VoiceService 사용 중 - 큐 처리 대기');
        _queueProcessTimer?.cancel();
        _queueProcessTimer = Timer.periodic(const Duration(milliseconds: 500), (
          timer,
        ) {
          if (!_voiceService!.isSpeaking) {
            timer.cancel();
            _isProcessingQueue = false;
            _processVoiceQueue();
          }
        });
        return;
      }

      final item = _voiceQueue.removeAt(0);
      debugPrint('🔊 음성 안내 재생: [${item.priority.name}] ${item.text}');

      await _speakTextDirect(item.text);
    } catch (e) {
      debugPrint('❌ 음성 안내 큐 처리 실패: $e');
    } finally {
      _isProcessingQueue = false;

      // 큐에 남은 아이템이 있으면 계속 처리
      if (_voiceQueue.isNotEmpty) {
        Future.delayed(const Duration(milliseconds: 100), _processVoiceQueue);
      }
    }
  }

  /// 직접 음성 출력 (큐 시스템 우회)
  Future<void> _speakTextDirect(String text) async {
    try {
      // HTML 태그 제거
      final document = parse(text);
      final String parsedString =
          parse(document.body?.text).documentElement!.text;

      if (_voiceService != null) {
        await VoiceUtils.speakWithService(
          _voiceService,
          parsedString,
          speed: _voiceService!.getCurrentSpeed(),
        );
      } else {
        debugPrint('🔊 음성 안내 (VoiceService 없음): $parsedString');
      }
    } catch (e) {
      debugPrint('❌ 음성 출력 실패: $e');
    }
  }

  /// 큐 정리
  void _clearVoiceQueue() {
    _queueProcessTimer?.cancel();
    _voiceQueue.clear();
    _isProcessingQueue = false;
    debugPrint('🧹 음성 안내 큐 정리 완료');
  }

  /// 특정 우선순위 이하의 안내 중단 (긴급 상황 시 사용)
  void _interruptLowerPriority(VoiceGuidancePriority priority) {
    final removedCount = _voiceQueue.length;
    _voiceQueue.removeWhere(
      (item) => item.priority.level < priority.level && item.canBeInterrupted,
    );
    final currentCount = _voiceQueue.length;
    debugPrint(
      '⚡ 낮은 우선순위 안내 중단: ${priority.name} 이하 (${removedCount - currentCount}개 제거)',
    );
  }

  /// 긴급 음성 안내 (다른 모든 안내 중단)
  Future<void> _speakEmergency(String text) async {
    _interruptLowerPriority(VoiceGuidancePriority.emergency);
    await _speakText(text, priority: VoiceGuidancePriority.emergency);
  }

  // 음성 안내 메서드 (큐 시스템 사용)
  Future<void> _speakText(
    String text, {
    VoiceGuidancePriority priority = VoiceGuidancePriority.status,
  }) async {
    _addToVoiceQueue(text, priority);
  }

  // 현재 선택된 추천 항목 음성 안내
  void _speakCurrentSuggestion() {
    if (_selectedSuggestionIndex >= 0 &&
        _selectedSuggestionIndex < _placeSuggestions.length) {
      final suggestion = _placeSuggestions[_selectedSuggestionIndex];
      final name = suggestion['description'] ?? '';
      final address =
          suggestion['structured_formatting']?['secondary_text'] ?? '';

      String message = '추천 ${_selectedSuggestionIndex + 1}. $name';
      if (address.isNotEmpty) {
        message += ', $address';
      }
      _speakText(message, priority: VoiceGuidancePriority.interaction);
    }
  }

  void _hideInstructionsPanel() {
    setState(() {
      _showInstructions = false;
    });
  }

  Future<void> _searchPlaces(String query) async {
    debugPrint('장소 검색 시작: "$query"');

    // 최소 2글자 이상 입력시에만 검색
    if (query.trim().length < 2) {
      debugPrint('검색어가 너무 짧음 (${query.length}글자), 추천 목록 숨김');
      setState(() {
        _placeSuggestions = [];
        _showSuggestions = false;
      });
      return;
    }

    try {
      // 현재 위치 가져오기 (검색 정확도 향상을 위해)
      double? lat, lng;
      try {
        final currentLocation = await _getCurrentLatLng();
        if (currentLocation != null) {
          lat = currentLocation.latitude;
          lng = currentLocation.longitude;
          debugPrint('현재 위치 기반 검색: $lat, $lng');
        }
      } catch (e) {
        debugPrint('위치 정보를 가져올 수 없어 기본 검색 실행: $e');
      }

      // 백엔드의 places autocomplete API 호출 (위치 정보 포함)
      debugPrint('API 호출 중: "${query.trim()}"');
      final response = await _api.searchPlaces(
        query.trim(),
        lat: lat,
        lng: lng,
      );
      debugPrint('API 응답: ${response.length}개 장소 찾음');

      setState(() {
        _placeSuggestions = response;
        _showSuggestions = response.isNotEmpty;
        _selectedSuggestionIndex = response.isNotEmpty ? 0 : -1; // 첫 번째 항목 선택
        _waitingForReadConfirmation = response.isNotEmpty; // 음성 안내 확인 대기
      });

      if (response.isNotEmpty) {
        debugPrint('${response.length}개 추천 장소 표시');
        for (int i = 0; i < response.length; i++) {
          final place = response[i];
          debugPrint(
            '  ${i + 1}. ${place['description']} - ${place['structured_formatting']?['secondary_text'] ?? ''}',
          );
        }

        // 음성 안내: 추천 목록이 있음을 알리고 사용자 선택 대기
        _speakText(
          '${response.length}개의 추천 장소가 있습니다. 목록을 읽어드릴까요?',
          priority: VoiceGuidancePriority.interaction,
        );
      } else {
        debugPrint('추천할 장소 없음');
        _speakText('추천할 장소가 없습니다.', priority: VoiceGuidancePriority.status);
        setState(() {
          _waitingForReadConfirmation = false;
        });
      }
    } catch (e) {
      debugPrint('장소 검색 실패: $e');
      setState(() {
        _placeSuggestions = [];
        _showSuggestions = false;
      });
    }
  }

  void _selectPlace(Map<String, dynamic> place) {
    final name = place['description'] ?? place['name'] ?? '';
    _destinationController.text = name;
    // 자동완성 패널을 숨기지 않고 유지
    // setState(() {
    //   _showSuggestions = false;
    // });

    // 선택한 장소 음성 안내
    final address = place['structured_formatting']?['secondary_text'] ?? '';
    String message = '$name이 선택되었습니다';
    if (address.isNotEmpty) {
      message += '. 주소: $address';
    }
    _speakText(message, priority: VoiceGuidancePriority.interaction);
  }

  // 음성 안내 읽기 시작
  void _startReadingSuggestions() {
    setState(() {
      _waitingForReadConfirmation = false;
    });
    _speakText(
      '${_placeSuggestions.length}개의 추천 장소입니다.',
      priority: VoiceGuidancePriority.interaction,
    );

    // 첫 번째 항목 읽어주기
    Future.delayed(const Duration(milliseconds: 1000), () {
      _speakCurrentSuggestion();
    });
  }

  // 음성 안내 건너뛰기
  void _skipReadingSuggestions() {
    setState(() {
      _waitingForReadConfirmation = false;
    });
    _speakText('원하는 장소를 선택하세요.', priority: VoiceGuidancePriority.interaction);
  }

  // 다음 추천 항목으로 이동
  void _nextSuggestion() {
    if (_placeSuggestions.isNotEmpty) {
      setState(() {
        if (_selectedSuggestionIndex < _placeSuggestions.length - 1) {
          _selectedSuggestionIndex++;
        } else {
          _selectedSuggestionIndex = 0; // 순환
        }
      });
      _speakCurrentSuggestion();
    }
  }

  // 이전 추천 항목으로 이동
  void _previousSuggestion() {
    if (_placeSuggestions.isNotEmpty) {
      setState(() {
        if (_selectedSuggestionIndex > 0) {
          _selectedSuggestionIndex--;
        } else {
          _selectedSuggestionIndex = _placeSuggestions.length - 1; // 순환
        }
      });
      _speakCurrentSuggestion();
    }
  }

  // 현재 선택된 항목 선택
  void _selectCurrentSuggestion() {
    if (_selectedSuggestionIndex >= 0 &&
        _selectedSuggestionIndex < _placeSuggestions.length) {
      _selectPlace(_placeSuggestions[_selectedSuggestionIndex]);
    }
  }

  // 음성인식 버튼
  void _toggleVoiceRecognition() async {
    if (_voiceService == null) {
      debugPrint('❌ MapScreen: VoiceService not initialized');
      return;
    }

    try {
      if (_isListening) {
        // 음성인식 중지
        debugPrint('🎙️ MapScreen: 음성인식 중지 요청');
        await _voiceService!.stopListeningAndProcess();

        // 효과음으로 중지 알림 (딜레이 없음)
        SystemSound.play(SystemSoundType.alert);

        setState(() {
          _isListening = false;
        });
      } else {
        // 음성인식 시작
        debugPrint('🎙️ MapScreen: 음성인식 시작 요청');

        // 효과음으로 시작 알림 (딜레이 없음)
        SystemSound.play(SystemSoundType.click);

        setState(() {
          _isListening = true;
        });

        // VoiceService 리스너 설정 (인식 결과 처리)
        _setupVoiceRecognitionListener();

        // 즉시 음성인식 실행 (딜레이 제거)
        await _voiceService!.startListening();
      }
    } catch (e) {
      debugPrint('❌ MapScreen: 음성인식 토글 실패: $e');
      // 사용자에게는 단순하게 알림
      _speakText('다시 시도해주세요.', priority: VoiceGuidancePriority.status);

      setState(() {
        _isListening = false;
      });
    }
  }

  /// 음성인식 결과 처리 리스너 설정
  void _setupVoiceRecognitionListener() {
    if (_voiceService == null) return;

    // VoiceService의 상태 변화 리스너 등록
    _voiceService!.addListener(_handleVoiceRecognitionResult);
  }

  /// 음성인식 결과 처리
  void _handleVoiceRecognitionResult() {
    if (_voiceService == null || !_isListening) return;

    // VoiceService가 인식을 완료했는지 확인
    if (_voiceService!.currentState == VoiceState.idle) {
      // 인식 완료 후 상태 초기화
      setState(() {
        _isListening = false;
      });

      // 인식된 텍스트가 있다면 목적지로 설정
      final recognizedText = _getLastRecognizedText();
      if (recognizedText != null && recognizedText.isNotEmpty) {
        debugPrint('🎙️ MapScreen: 인식된 텍스트: $recognizedText');

        // 목적지 입력창에 설정
        _destinationController.text = recognizedText;

        // 음성 확인
        _speakText(
          '$recognizedText로 검색합니다.',
          priority: VoiceGuidancePriority.interaction,
        );

        // 자동 장소 검색
        _searchPlaces(recognizedText);
      } else {
        debugPrint('🎙️ MapScreen: 인식 결과 없음');
        _speakText('다시 말씀해주세요.', priority: VoiceGuidancePriority.status);
      }

      // 리스너 제거
      _voiceService!.removeListener(_handleVoiceRecognitionResult);
    }
  }

  /// 마지막 인식된 텍스트 가져오기 (VoiceService에서)
  String? _getLastRecognizedText() {
    if (_voiceService == null) return null;

    final text = _voiceService!.lastRecognizedText.trim();
    return text.isEmpty ? null : text;
  }

  // ---- 유틸 ----
  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  // GPS 관련 코드 (네이버 맵 테스트용)
  Future<bool> _ensureLocationPermission() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        setState(() => _status = '위치 서비스 꺼짐');
        _toast('위치 서비스가 꺼져 있어요.');
        return false;
      }
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied) {
        setState(() => _status = '위치 권한 거부됨');
        _toast('설정에서 위치 권한을 허용해주세요.');
        return false;
      }

      if (permission == LocationPermission.deniedForever) {
        setState(() => _status = '위치 권한 영구 거부됨');
        _toast('설정에서 위치 권한을 허용해주세요.');
        return false;
      }

      return true;
    } catch (e) {
      debugPrint('Permission check failed: $e');
      setState(() => _status = '위치 권한 점검 실패');
      _toast('위치 권한 확인 중 오류');
      return false;
    }
  }

  // 실제 GPS 위치 반환
  Future<NLatLng?> _getCurrentLatLng() async {
    try {
      final hasPermission = await _ensureLocationPermission();
      if (!hasPermission) return null;

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 1,
        ),
      );

      return NLatLng(position.latitude, position.longitude);
    } catch (e) {
      debugPrint('Failed to get current location: $e');
      _toast('현재 위치를 가져올 수 없습니다.');
      return null;
    }
  }

  // ---- 현재 위치로 시점 이동 ----
  Future<void> _centerToMyLocation() async {
    final here = await _getCurrentLatLng();
    if (here == null) return;
    final map = _map ?? await _controller.future;

    if (_hereMarker != null) {
      try {
        map.deleteOverlay(_hereMarker!.info);
      } catch (_) {}
      _hereMarker = null;
    }
    _hereMarker = NMarker(
      id: 'here_marker',
      position: here,
      caption: const NOverlayCaption(text: '현재 위치'),
      captionAligns: const [NAlign.top],
      iconTintColor: Colors.blueAccent,
    );
    map.addOverlay(_hereMarker!);

    final cu = NCameraUpdate.scrollAndZoomTo(target: here, zoom: 16);
    cu.setAnimation(
      animation: NCameraAnimation.easing,
      duration: const Duration(milliseconds: 450),
    );
    await map.updateCamera(cu);

    setState(() => _status = '현재 위치로 이동');
  }

  // ---- 경로 그리기 (도보 전용) ----
  Future<void> _drawRoute({
    required String origin, // "lat,lng" 혹은 주소
    required String destination, // "lat,lng" 혹은 주소
    List<String>? waypoints,
  }) async {
    // 음성 안내가 진행 중이면 중지
    _stopVoiceGuidance();
    try {
      setState(() => _status = '도보 경로 요청 중...');
      final resp = await _api.getRoute(
        origin: origin,
        destination: destination,
        waypoints: waypoints,
      );

      if (!resp.hasRoute) {
        setState(() => _status = '경로 없음');
        _toast('경로가 없습니다.');
        return;
      }

      // [[lng,lat], ...] -> NLatLng(lat,lng)
      final coords = resp.pathLngLat
          .map((p) => NLatLng(p[1], p[0]))
          .toList(growable: false);
      final map = _map ?? await _controller.future;

      // 기존 오버레이 제거
      final toDelete = <NOverlayInfo>[];
      if (_routePolyline != null) toDelete.add(_routePolyline!.info);
      if (_startMarker != null) toDelete.add(_startMarker!.info);
      if (_endMarker != null) toDelete.add(_endMarker!.info);
      for (final info in toDelete) {
        try {
          map.deleteOverlay(info);
        } catch (_) {}
      }
      _routePolyline = null;
      _startMarker = null;
      _endMarker = null;

      // 시작/도착 마커
      _startMarker = NMarker(
        id: 'start_marker',
        position: coords.first,
        caption: const NOverlayCaption(text: '출발'),
        captionAligns: const [NAlign.top],
        iconTintColor: Colors.green,
      );
      _endMarker = NMarker(
        id: 'end_marker',
        position: coords.last,
        caption: const NOverlayCaption(text: '도착'),
        captionAligns: const [NAlign.top],
        iconTintColor: Colors.red,
      );
      map.addOverlay(_startMarker!);
      map.addOverlay(_endMarker!);

      // 경로 폴리라인
      _routePolyline = NPolylineOverlay(
        id: 'route_polyline',
        coords: coords,
        width: 8.0,
        color: Colors.blue,
      );
      map.addOverlay(_routePolyline!);

      // 화면에 경로 전체가 보이도록 시점 맞춤
      try {
        final bounds = NLatLngBounds.from(coords);
        final cu = NCameraUpdate.fitBounds(
          bounds,
          padding: const EdgeInsets.all(40),
        );
        cu.setAnimation(
          animation: NCameraAnimation.easing,
          duration: const Duration(milliseconds: 600),
        );
        await map.updateCamera(cu);
      } catch (_) {}

      setState(() => _status = '경로 표시 완료');
      _toast(
        '경로 표시 (${resp.provider}) • ${resp.distanceText} / ${resp.durationText}',
      );

      // 경로 응답에서 길안내 단계들 추출
      _extractInstructions(resp);
      // 음성 길안내 시작
      _startVoiceGuidance();
    } catch (e) {
      setState(() => _status = '경로 요청 실패');
      String userMessage = '경로 요청 실패';

      final errorStr = e.toString();
      if (errorStr.contains('TimeoutException')) {
        userMessage = '서버 응답이 너무 느려 연결이 끊어졌습니다. 네트워크 연결을 확인하거나 잠시 후 다시 시도해주세요.';
      } else if (errorStr.contains('Connection refused')) {
        userMessage = '서버에 연결할 수 없습니다. 네트워크 연결을 확인해주세요.';
      } else if (errorStr.contains('SocketException')) {
        userMessage = '네트워크 연결에 문제가 있습니다. WiFi 또는 모바일 데이터 연결을 확인해주세요.';
      } else if (errorStr.contains('overloaded')) {
        userMessage = '서버가 과부하 상태입니다. 잠시 후 다시 시도해주세요.';
      }

      _toast(userMessage);
      debugPrint('Route error details: $e');
    }
  }

  void _extractInstructions(DirectionsResponse resp) {
    debugPrint('Extracting instructions: ${resp.steps.length} steps found');
    for (int i = 0; i < resp.steps.length; i++) {
      final step = resp.steps[i];
      debugPrint(
        'Step $i: ${step['instruction_html']} - ${step['distance_text']}',
      );
    }

    setState(() {
      _instructions = resp.steps;
      _showInstructions = _instructions.isNotEmpty;
    });

    if (_instructions.isEmpty) {
      debugPrint('No instructions found in response');
    } else {
      debugPrint('Instructions panel should be visible: $_showInstructions');
    }
  }

  // ---- 음성 길안내 관련 메서드 ----

  void _startVoiceGuidance() {
    if (_instructions.isEmpty) return;

    _stopVoiceGuidance(); // 기존 안내 중지

    setState(() {
      _isNavigating = true;
      _currentInstructionIndex = 0;
      _status = '음성 길안내 시작';
    });

    // 시각장애인용 상세 경로 안내 시작
    _announceRouteStart();

    _positionStream = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.bestForNavigation,
        distanceFilter: 10, // 10미터 이동 시 업데이트
      ),
    ).listen(_checkUserPosition);
  }

  void _stopVoiceGuidance() {
    _positionStream?.cancel();
    _positionStream = null;
    _statusAnnouncementTimer?.cancel(); // 주기적 안내 중지
    if (mounted) {
      setState(() {
        _isNavigating = false;
        _status = '음성 길안내 중지';
      });
    }
  }

  void _checkUserPosition(Position position) {
    if (!_isNavigating || _currentInstructionIndex >= _instructions.length) {
      return;
    }

    final nextInstruction = _instructions[_currentInstructionIndex];
    // API 응답에 'start_location'이 있다고 가정
    final locationData = nextInstruction['start_location'] as Map?;
    if (locationData == null) return;

    final lat = locationData['lat'] as double?;
    final lng = locationData['lng'] as double?;
    if (lat == null || lng == null) return;

    final distance = Geolocator.distanceBetween(
      position.latitude,
      position.longitude,
      lat,
      lng,
    );

    // 다음 안내 지점에 20미터 이내로 가까워지면 안내
    if (distance < 20) {
      _currentInstructionIndex++;
      if (_currentInstructionIndex < _instructions.length) {
        final instructionText =
            _instructions[_currentInstructionIndex]['instruction_html']
                as String?;
        if (instructionText != null) {
          // 시각장애인용 상세 다음 단계 안내
          _announceNextStep(instructionText);
        }
      } else {
        // 시각장애인용 상세 도착 안내
        _announceDestinationArrival();
        _stopVoiceGuidance();
      }
    }
  }

  // ---- 버튼 핸들러 ----
  Future<void> _routeFromMyLocation() async {
    final destination = _destinationController.text.trim();
    if (destination.isEmpty) {
      _toast('목적지를 입력해주세요.');
      return;
    }

    try {
      setState(() => _status = 'GPS 위치 확인 중...');

      final here = await _getCurrentLatLng();
      if (here == null) {
        _toast('현재 위치를 확인할 수 없습니다.');
        setState(() => _status = '위치 확인 실패');
        return;
      }

      // 출발지 현재 GPS 위치로 고정
      final origin = '${here.latitude},${here.longitude}';

      debugPrint('GPS Location (Origin): $origin');
      debugPrint('Destination: $destination');

      setState(() => _status = '도보 경로 계산 중... (최대 15초)');
      _toast('도보 경로를 계산하고 있습니다. 잠시만 기다려주세요.');

      // 추천 목록 숨기기
      setState(() {
        _showSuggestions = false;
        _placeSuggestions = [];
        _waitingForReadConfirmation = false;
      });

      await _drawRoute(origin: origin, destination: destination);
    } catch (e) {
      debugPrint('Route from my location error: $e');
      setState(() => _status = '경로 계산 실패');

      String userMessage = '경로 계산 중 오류가 발생했습니다';
      final errorStr = e.toString();

      if (errorStr.contains('TimeoutException')) {
        userMessage = '경로 계산 시간이 초과되었습니다. 네트워크 상태를 확인하고 다시 시도해주세요.';
      } else if (errorStr.contains('Connection refused') ||
          errorStr.contains('unreachable')) {
        userMessage = '지도 서버에 연결할 수 없습니다. 네트워크 연결을 확인해주세요.';
      } else if (errorStr.contains('SocketException')) {
        userMessage = '인터넷 연결에 문제가 있습니다. WiFi나 모바일 데이터를 확인해주세요.';
      }

      _toast(userMessage);
    }
  }

  Widget _buildMapWidget() {
    if (_mapAuthFailed) {
      return Container(
        color: Colors.grey[100],
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.map_outlined, size: 80, color: Colors.grey[400]),
                const SizedBox(height: 16),
                Text(
                  '네이버 지도 인증 실패',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: Colors.grey[700],
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '네이버 지도를 사용하려면 클라이언트 ID가 필요합니다.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.grey[600], fontSize: 16),
                ),
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.blue[50],
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.blue[200]!),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.info, color: Colors.blue[700], size: 20),
                          const SizedBox(width: 8),
                          Text(
                            '해결 방법',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.blue[700],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Text('1. 네이버 클라우드 플랫폼에서 클라이언트 ID 발급'),
                      const Text('   → https://console.ncloud.com/'),
                      const SizedBox(height: 8),
                      const Text('2. 플랫폼별 설정 파일에 클라이언트 ID 입력:'),
                      const Text('   • iOS: Info.plist의 NMFNcpKeyId'),
                      const Text('   • Android: AndroidManifest.xml'),
                      const SizedBox(height: 8),
                      const Text('3. 또는 .env 파일에 NAVER_MAP_CLIENT_ID 설정'),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: () {
                    _speakText(
                      '맵 재시도',
                      priority: VoiceGuidancePriority.interaction,
                    );
                    setState(() {
                      _mapAuthFailed = false;
                      _status = '맵 재시도 중...';
                    });
                  },
                  icon: const Icon(Icons.refresh),
                  label: const Text('다시 시도'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.blue,
                    foregroundColor: Colors.white,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return NaverMap(
      options: const NaverMapViewOptions(
        initialCameraPosition: NCameraPosition(
          target: NLatLng(37.5665, 126.9780), // 서울시청
          zoom: 14,
        ),
        indoorEnable: false,
        logoClickEnable: false,
        locationButtonEnable: false,
        // 타일 로딩 문제 해결 시도
        mapType: NMapType.basic,
        buildingHeight: 1.0,
        symbolScale: 1.0,
      ),
      onMapReady: (c) async {
        debugPrint('🗺️ onMapReady called');
        _map = c;
        if (!_controller.isCompleted) _controller.complete(c);

        setState(() => _status = '맵 로드 완료');
        debugPrint('✅ NaverMap widget ready');

        // 타일 로딩 상태 확인을 위한 짧은 대기
        await Future.delayed(const Duration(seconds: 2));

        // 맵이 준비되면 현재 위치로 자동 이동
        try {
          await Future.delayed(const Duration(milliseconds: 500));
          await _centerToMyLocation();
        } catch (e) {
          debugPrint('⚠️ 초기 위치 이동 실패: $e');
        }

        // 타일 로딩 실패 감지
        Future.delayed(const Duration(seconds: 5), () {
          if (mounted && _status.contains('맵 로드 완료')) {
            debugPrint('🔍 지도 타일 로딩 상태 확인');
            debugPrint('💡 그리드만 보인다면 클라이언트 ID 권한 문제일 수 있습니다.');
            debugPrint('📋 해결 방법: 네이버 클라우드 플랫폼에서 새 ID 발급');
          }
        });
      },
      onMapTapped: (point, latLng) {
        // 맵 탭 시 인증 오류 감지
        debugPrint('🗺️ 맵 탭됨: $latLng');
      },
    );
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      backgroundColor: AppColors.bg,
      leading: IconButton(
        icon: const Icon(Icons.arrow_back_ios_new, color: Colors.white),
        onPressed: () {
          _speakText('뒤로가기', priority: VoiceGuidancePriority.interaction);
          Navigator.of(context).pop();
        },
        tooltip: '뒤로가기',
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    debugPrint('📱 MapScreen build - Status: $_status');

    // Web 가드 (플러그인 미지원)
    if (kIsWeb) {
      return Scaffold(
        appBar: _buildAppBar(),
        body: const Center(
          child: Text('네이버 지도는 Flutter Web 미지원입니다. iOS/Android에서 실행하세요.'),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: _buildAppBar(),
      body: Stack(
        children: [
          _buildMapWidget(),
          Positioned(
            left: 16,
            right: 16,
            bottom: 16,
            child: Card(
              color: AppColors.panel,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 12),
                    Column(
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _destinationController,
                                decoration: const InputDecoration(
                                  hintText: '목적지를 입력하세요 (예: 경복궁, 명동역)',
                                  border: OutlineInputBorder(),
                                  prefixIcon: Icon(Icons.place),
                                  contentPadding: EdgeInsets.symmetric(
                                    horizontal: 12,
                                    vertical: 8,
                                  ),
                                ),
                                onChanged: _searchPlaces,
                                onSubmitted: (_) {
                                  _routeFromMyLocation();
                                },
                              ),
                            ),
                            const SizedBox(width: 8),
                            Container(
                              decoration: BoxDecoration(
                                color: _isListening ? Colors.red : Colors.blue,
                                shape: BoxShape.circle,
                              ),
                              child: IconButton(
                                onPressed: () {
                                  _speakText(
                                    _isListening ? '음성인식 중지' : '음성인식 시작',
                                  );
                                  _toggleVoiceRecognition();
                                },
                                icon: Icon(
                                  _isListening ? Icons.mic : Icons.mic_none,
                                  color: Colors.white,
                                ),
                                tooltip: _isListening ? '음성인식 중지' : '음성인식 시작',
                              ),
                            ),
                          ],
                        ),
                        if (_showSuggestions) _buildSuggestionsPanel(),
                      ],
                    ),
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: () {
                          _speakText(
                            '도보 경로 찾기',
                            priority: VoiceGuidancePriority.interaction,
                          );
                          _routeFromMyLocation();
                        },
                        icon: const Icon(Icons.directions_walk),
                        label: const Text('도보 경로 찾기'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_showInstructions) _buildInstructionsPanel(),
        ],
      ),
    );
  }

  Widget _buildInstructionsPanel() {
    return Align(
      alignment: Alignment.topCenter,
      child: Padding(
        padding: const EdgeInsets.only(top: 16.0),
        child: Container(
          width: 300,
          height: 400,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black26,
                blurRadius: 8,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: const BoxDecoration(
                  color: Colors.blue,
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(12),
                    topRight: Radius.circular(12),
                  ),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.directions_walk, color: Colors.white),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        '길안내',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    IconButton(
                      onPressed: () {
                        _speakText(
                          '닫기',
                          priority: VoiceGuidancePriority.interaction,
                        );
                        _hideInstructionsPanel();
                      },
                      icon: const Icon(Icons.close, color: Colors.white),
                    ),
                  ],
                ),
              ),
              Expanded(
                child:
                    _instructions.isEmpty
                        ? const Center(child: Text('길안내 정보가 없습니다.'))
                        : ListView.builder(
                          padding: const EdgeInsets.all(8),
                          itemCount: _instructions.length,
                          itemBuilder: (context, index) {
                            final instruction = _instructions[index];
                            final html = instruction['instruction_html'] ?? '';
                            final distanceText =
                                instruction['distance_text'] ?? '';
                            final durationText =
                                instruction['duration_text'] ?? '';

                            return Card(
                              margin: const EdgeInsets.symmetric(vertical: 4),
                              child: Padding(
                                padding: const EdgeInsets.all(12),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        CircleAvatar(
                                          radius: 12,
                                          backgroundColor: Colors.blue,
                                          child: Text(
                                            '${index + 1}',
                                            style: const TextStyle(
                                              color: Colors.white,
                                              fontSize: 12,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Expanded(
                                          child: Text(
                                            html.isNotEmpty
                                                ? html
                                                : '단계 ${index + 1}',
                                            style: const TextStyle(
                                              fontSize: 14,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                    if (distanceText.isNotEmpty ||
                                        durationText.isNotEmpty)
                                      Padding(
                                        padding: const EdgeInsets.only(
                                          top: 4,
                                          left: 32,
                                        ),
                                        child: Text(
                                          [distanceText, durationText]
                                              .where((s) => s.isNotEmpty)
                                              .join(' • '),
                                          style: TextStyle(
                                            fontSize: 12,
                                            color: Colors.grey[600],
                                          ),
                                        ),
                                      ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSuggestionsPanel() {
    return Container(
      margin: const EdgeInsets.only(top: 4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        boxShadow: [
          BoxShadow(
            color: Colors.black12,
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      constraints: const BoxConstraints(maxHeight: 300),
      child: Column(
        children: [
          // 음성 안내 확인 대기 상태 표시 및 버튼들
          if (_waitingForReadConfirmation)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              decoration: const BoxDecoration(
                color: Colors.orange,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(8),
                  topRight: Radius.circular(8),
                ),
              ),
              child: Column(
                children: [
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: () {
                            _speakText(
                              '읽기',
                              priority: VoiceGuidancePriority.interaction,
                            );
                            _startReadingSuggestions();
                          },
                          icon: const Icon(Icons.volume_up, size: 18),
                          label: const Text('읽기'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: () {
                            _speakText(
                              '건너뛰기',
                              priority: VoiceGuidancePriority.interaction,
                            );
                            _skipReadingSuggestions();
                          },
                          icon: const Icon(Icons.skip_next, size: 18),
                          label: const Text('건너뛰기'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.grey,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 8),
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),

          // 탐색 버튼들 (음성 안내 모드가 아닐 때 표시)
          if (!_waitingForReadConfirmation && _placeSuggestions.isNotEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.blue.shade50,
                borderRadius:
                    _waitingForReadConfirmation
                        ? null
                        : const BorderRadius.only(
                          topLeft: Radius.circular(8),
                          topRight: Radius.circular(8),
                        ),
              ),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () {
                      _speakText(
                        '이전 항목',
                        priority: VoiceGuidancePriority.interaction,
                      );
                      _previousSuggestion();
                    },
                    icon: const Icon(Icons.keyboard_arrow_up),
                    tooltip: '이전 항목',
                  ),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: () {
                        _speakText(
                          '선택',
                          priority: VoiceGuidancePriority.interaction,
                        );
                        _selectCurrentSuggestion();
                      },
                      icon: const Icon(Icons.check, size: 18),
                      label: const Text('선택'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.blue,
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () {
                      _speakText(
                        '다음 항목',
                        priority: VoiceGuidancePriority.interaction,
                      );
                      _nextSuggestion();
                    },
                    icon: const Icon(Icons.keyboard_arrow_down),
                    tooltip: '다음 항목',
                  ),
                ],
              ),
            ),

          // 추천 목록
          Flexible(
            child: ListView.builder(
              padding: EdgeInsets.zero,
              shrinkWrap: true,
              itemCount: _placeSuggestions.length,
              itemBuilder: (context, index) {
                final place = _placeSuggestions[index];
                final name = place['description'] ?? place['name'] ?? '';
                final address =
                    place['structured_formatting']?['secondary_text'] ?? '';

                final isSelected = index == _selectedSuggestionIndex;

                return Container(
                  decoration: BoxDecoration(
                    color:
                        isSelected
                            ? Colors.blue.withValues(alpha: 0.1)
                            : Colors.transparent,
                    border:
                        isSelected
                            ? Border.all(color: Colors.blue, width: 2)
                            : null,
                  ),
                  child: ListTile(
                    dense: true,
                    leading: Icon(
                      Icons.place,
                      color: isSelected ? Colors.blue : Colors.grey,
                      size: 20,
                    ),
                    title: Text(
                      name,
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight:
                            isSelected ? FontWeight.bold : FontWeight.normal,
                        color: isSelected ? Colors.blue : Colors.black,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle:
                        address.isNotEmpty
                            ? Text(
                              address,
                              style: TextStyle(
                                fontSize: 12,
                                color:
                                    isSelected
                                        ? Colors.blue[700]
                                        : Colors.grey[600],
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            )
                            : null,
                    onTap: () => _selectPlace(place),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
