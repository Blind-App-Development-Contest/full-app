import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  // String get baseUrl => dotenv.env['BACKEND_BASE_URL'] ?? 'http://localhost:8000';
String get baseUrl => dotenv.env['BACKEND_BASE_URL'] ?? 'https://aeye-gvu9.onrender.com';
  final http.Client _httpClient = http.Client();
  
  /// 사용자 UUID 키
  static const String _userUuidKey = 'app_uuid';
  
  /// 서버 연결 상태 캐시
  bool _serverConnected = false;
  DateTime? _lastConnectionCheck;
  
  /// 사용자 설정 로컬 캐시
  Map<String, dynamic>? _cachedUserSettings;
  DateTime? _lastSettingsUpdate;

  /// 안정적인 HTTP 요청 (재시도 로직 포함)
  Future<http.Response?> _safeHttpRequest(
    Future<http.Response> Function() requestFunction, {
    int maxRetries = 5, // 재시도 횟수 증가
    Duration retryDelay = const Duration(seconds: 3), // 재시도 간격 증가
  }) async {
    for (int attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        debugPrint('🌐 HTTP 요청 시도 $attempt/$maxRetries');
        final response = await requestFunction();
        
        // 성공 시 연결 상태 업데이트
        if (response.statusCode < 500) {
          _serverConnected = true;
          _lastConnectionCheck = DateTime.now();
          debugPrint('✅ HTTP 요청 성공 (시도 $attempt/$maxRetries): ${response.statusCode}');
        }
        
        return response;
      } catch (e) {
        final errorMsg = e.toString();
        debugPrint('❌ HTTP 요청 실패 (시도 $attempt/$maxRetries): $errorMsg');
        
        // 특정 오류는 재시도하지 않음
        if (errorMsg.contains('FormatException') || 
            errorMsg.contains('Invalid argument')) {
          debugPrint('🚫 재시도 불가능한 오류 - 즉시 중단');
          return null;
        }
        
        if (attempt == maxRetries) {
          _serverConnected = false;
          _lastConnectionCheck = DateTime.now();
          debugPrint('❌ 모든 재시도 실패 ($maxRetries회) - 오프라인 모드');
          return null;
        }
        
        // 점진적 재시도 간격 (exponential backoff)
        final currentDelay = Duration(seconds: retryDelay.inSeconds * attempt);
        debugPrint('⏳ ${currentDelay.inSeconds}초 후 재시도...');
        await Future.delayed(currentDelay);
      }
    }
    return null;
  }

  /// 서버 연결 상태 확인
  bool get isServerConnected {
    final now = DateTime.now();
    if (_lastConnectionCheck != null && 
        now.difference(_lastConnectionCheck!).inMinutes < 5) {
      return _serverConnected;
    }
    return false;
  }

  /// 사용자 초기화 (UUID 생성/로드)
  Future<void> initializeUser() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      String? existingUuid = prefs.getString(_userUuidKey);
      
      if (existingUuid == null) {
        // 새로운 UUID 생성
        const uuid = Uuid();
        existingUuid = uuid.v4();
        await prefs.setString(_userUuidKey, existingUuid);
        debugPrint('새로운 사용자 UUID 생성: $existingUuid');
      } else {
        debugPrint('기존 사용자 UUID 로드: $existingUuid');
      }
      
      // 서버에 사용자 등록/확인
      await _registerUser(existingUuid);
    } catch (e) {
      debugPrint('사용자 초기화 오류: $e');
      rethrow;
    }
  }

  /// 서버에 사용자 등록/확인
  Future<void> _registerUser(String uuid) async {
    final response = await _safeHttpRequest(
      () => _httpClient.post(
        Uri.parse('$baseUrl/api/users/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'app_uuid': uuid}),
      ).timeout(const Duration(seconds: 30)),
    );

    if (response != null) {
      if (response.statusCode == 200 || response.statusCode == 201) {
        debugPrint('✅ 사용자 등록/확인 성공');
      } else if (response.statusCode == 422) {
        debugPrint('⚠️ 사용자가 이미 존재함 (422) - 정상 상황');
      } else {
        debugPrint('❌ 사용자 등록/확인 실패: ${response.statusCode}');
        debugPrint('서버 응답: ${response.body}');
      }
    } else {
      debugPrint('⚠️ 서버 연결 실패 - 오프라인 모드로 진행');
    }
  }

  /// 현재 사용자 UUID 가져오기
  Future<String?> getCurrentUserUuid() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_userUuidKey);
  }

  /// 서버 상태 확인
  Future<Map<String, dynamic>> checkServerStatus() async {
    try {
      final response = await _httpClient.get(
        Uri.parse('$baseUrl/api/users/measurement/'),
        headers: {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } else {
        return {'status': 'error', 'code': response.statusCode};
      }
    } catch (e) {
      debugPrint('서버 상태 확인 오류: $e');
      return {'status': 'error', 'message': e.toString()};
    }
  }

  /// 측정 결과 저장
  Future<bool> saveMeasurementResult(Map<String, dynamic> result) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) return false;

      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/measurement/save'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': uuid,
          'measurement_data': result,
        }),
      ).timeout(const Duration(seconds: 30));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint('측정 결과 저장 오류: $e');
      return false;
    }
  }

  /// 보폭 길이 저장 (백엔드와 동일한 변수명 사용)
  Future<bool> saveStepLength(double step_length_cm) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) return false;

      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/footstep/update'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': uuid,
          'step_length_cm': step_length_cm.toInt(),
        }),
      ).timeout(const Duration(seconds: 30));

      return response.statusCode == 200;
    } catch (e) {
      if (e.toString().contains('Connection refused') || e.toString().contains('SocketException')) {
        debugPrint('⚠️ 서버 연결 실패 - 보폭은 로컬에만 저장: $e');
        // 서버가 다운되어도 보폭 측정은 계속 진행 가능하도록 true 반환
        return true;
      }
      debugPrint('❌ 보폭 길이 저장 오류: $e');
      return false;
    }
  }

  /// 음성 설정 저장
  Future<bool> saveVoiceSettings(Map<String, dynamic> settings) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) return false;

      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/voice'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': uuid,
          'text': '음성 설정이 저장되었습니다.',
          'gender': settings['gender'] ?? 'F',
          'speed': settings['speed'] ?? 1.0,
        }),
      ).timeout(const Duration(seconds: 30));

      return response.statusCode == 200;
    } catch (e) {
      if (e.toString().contains('Connection refused') || e.toString().contains('SocketException')) {
        debugPrint('⚠️ 서버 연결 실패 - 오프라인 모드로 진행: $e');
        // 서버가 다운되어도 온보딩은 계속 진행 가능하도록 true 반환
        return true;
      }
      debugPrint('❌ 음성 설정 저장 오류: $e');
      return false;
    }
  }

  /// 온보딩 완료 처리
  Future<bool> completeOnboarding(Map<String, dynamic> onboardingData) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) return false;

      // 서버가 기대하는 평평한 JSON 구조를 만듭니다.
      final payload = {
        'app_uuid': uuid,
        ...onboardingData,
      };

      // step_length_cm가 double일 경우 int로 변환합니다.
      if (payload.containsKey('step_length_cm') && payload['step_length_cm'] is double) {
        payload['step_length_cm'] = (payload['step_length_cm'] as double).toInt();
      }

      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/onboarding/complete'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(payload), // 수정된 payload를 전송
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        debugPrint('✅ 온보딩 완료 데이터 전송 성공');
        // 이어서 설정 초기화 API 호출
        final initResponse = await _httpClient.post(
          Uri.parse('$baseUrl/api/users/settings/initialize/$uuid'),
          headers: {'Content-Type': 'application/json'},
        ).timeout(const Duration(seconds: 5));

        if (initResponse.statusCode == 200) {
          debugPrint('✅ 사용자 설정 초기화(연결) 성공');
          return true;
        } else {
          debugPrint('❌ 사용자 설정 초기화(연결) 실패: ${initResponse.statusCode}');
          debugPrint('서버 응답: ${initResponse.body}');
          return false;
        }
      } else {
        debugPrint('❌ 온보딩 완료 처리 실패: ${response.statusCode}');
        debugPrint('서버 응답: ${response.body}');
        return false;
      }
    } catch (e) {
      debugPrint('온보딩 완료 처리 오류: $e');
      return false;
    }
  }

  /// 사용자 설정 불러오기
  Future<Map<String, dynamic>?> getUserSettings() async {
    final uuid = await getCurrentUserUuid();
    if (uuid == null) {
      debugPrint('❌ 사용자 UUID가 없어 설정을 로드할 수 없습니다');
      return null;
    }

    final response = await _safeHttpRequest(
      () => _httpClient.get(
        Uri.parse('$baseUrl/api/users/settings/$uuid'),
        headers: {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 30)),
    );

    if (response != null) {
      if (response.statusCode == 200) {
        final settings = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 사용자 설정 로드 성공: $settings');
        return settings;
      } else if (response.statusCode == 404) {
        debugPrint('⚠️ 사용자 설정이 없음 - 기본 설정 생성 시도');
        // 사용자 설정이 없으면 기본 설정 생성
        final created = await _createDefaultUserSettings(uuid);
        if (created) {
          // 생성 후 다시 조회 (재귀 호출 방지를 위해 한 번만)
          debugPrint('🔄 기본 설정 생성 후 재조회 시도');
          return await _safeGetUserSettingsRetry(uuid);
        }
        return null;
      } else {
        debugPrint('❌ 사용자 설정 로드 실패: ${response.statusCode}');
        return null;
      }
    } else {
      debugPrint('❌ 서버 연결 완전 실패 - 설정을 가져올 수 없음');
      // 기본 설정을 반환하지 않고 null을 반환하여 호출자가 적절히 처리하도록 함
      return null;
    }
  }

  /// 재귀 호출 방지를 위한 재시도 메소드
  Future<Map<String, dynamic>?> _safeGetUserSettingsRetry(String uuid) async {
    final response = await _safeHttpRequest(
      () => _httpClient.get(
        Uri.parse('$baseUrl/api/users/settings/$uuid'),
        headers: {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 30)),
      maxRetries: 1, // 재시도는 1번만
    );

    if (response?.statusCode == 200) {
      final settings = jsonDecode(utf8.decode(response!.bodyBytes));
      debugPrint('✅ 재시도 후 사용자 설정 로드 성공: $settings');
      return settings;
    }
    return null;
  }

  /// 로컬 기본 설정 반환
  Map<String, dynamic> _getDefaultSettings() {
    return {
      'step_length': 70.0,
      'voice_speed': 0.9,
      'voice_gender': 'female',
      'caregiver_name': null,
      'caregiver_phone': null,
    };
  }

  /// 기본 사용자 설정 생성
  Future<bool> _createDefaultUserSettings(String uuid) async {
    try {
      debugPrint('🔧 기본 사용자 설정 생성 시작: $uuid');
      
      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/settings/initialize/$uuid'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode == 200 || response.statusCode == 201) {
        debugPrint('✅ 기본 사용자 설정 생성 성공');
        return true;
      } else {
        debugPrint('❌ 기본 사용자 설정 생성 실패: ${response.statusCode}');
        debugPrint('서버 응답: ${response.body}');
        return false;
      }
    } catch (e) {
      debugPrint('❌ 기본 사용자 설정 생성 오류: $e');
      return false;
    }
  }

  // ===================
  // 보호자 관리 API
  // ===================

  /// 보호자 정보 등록
  Future<Map<String, dynamic>?> createCaregiver({
    required String caregivers_name,
    required String phoneNumber,
  }) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) throw Exception('사용자 UUID를 찾을 수 없습니다');
      
      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/caregiver'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': uuid,
          'caregivers_name': caregivers_name,
          'phone_number': phoneNumber,
        }),
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode == 200 || response.statusCode == 201) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 보호자 정보 등록 성공: $caregivers_name ($phoneNumber)');
        return result;
      } else {
        debugPrint('❌ 보호자 등록 실패: ${response.statusCode} ${response.body}');
        throw Exception('보호자 등록 실패: ${response.statusCode}');
      }
    } catch (e) {
      if (e.toString().contains('Connection refused') || e.toString().contains('SocketException')) {
        debugPrint('⚠️ 서버 연결 실패 - 보호자 정보는 로컬에만 저장: $e');
        // 서버 연결 실패 시에도 온보딩이 계속될 수 있도록 기본 응답 반환
        return {
          'caregiver_id': -1,
          'user_id': await getCurrentUserUuid() ?? 'offline',
          'caregivers_name': caregivers_name,
          'phone_number': phoneNumber,
          'status': 'offline_mode'
        };
      }
      debugPrint('❌ 보호자 정보 등록 실패: $e');
      rethrow;
    }
  }

  /// 보호자 정보 수정
  Future<Map<String, dynamic>?> updateCaregiver({
    String? name,
    String? phoneNumber,
  }) async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) throw Exception('사용자 UUID를 찾을 수 없습니다');
      
      final Map<String, dynamic> updateData = {};
      if (name != null) updateData['caregivers_name'] = name;
      if (phoneNumber != null) updateData['phone_number'] = phoneNumber;

      if (updateData.isEmpty) {
        throw Exception('수정할 데이터가 없습니다');
      }

      final response = await _httpClient.patch(
        Uri.parse('$baseUrl/api/users/caregiver/$uuid'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(updateData),
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 보호자 정보 수정 성공');
        return result;
      } else {
        debugPrint('❌ 보호자 수정 실패: ${response.statusCode} ${response.body}');
        throw Exception('보호자 수정 실패: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('❌ 보호자 정보 수정 실패: $e');
      rethrow;
    }
  }

  /// 긴급 상황 보호자 알림 발송
  Future<Map<String, dynamic>?> sendCaregiverAlert() async {
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) throw Exception('사용자 UUID를 찾을 수 없습니다');
      
      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/caregiver/alert'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': uuid,
        }),
      ).timeout(const Duration(seconds: 30));

      if (response.statusCode == 200) {
        final result = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 보호자 긴급 알림 발송 성공');
        return result;
      } else {
        debugPrint('❌ 보호자 알림 발송 실패: ${response.statusCode} ${response.body}');
        throw Exception('보호자 알림 발송 실패: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('❌ 보호자 긴급 알림 발송 실패: $e');
      rethrow;
    }
  }

  /// HTTP 클라이언트 정리
  void dispose() {
    _httpClient.close();
  }
}