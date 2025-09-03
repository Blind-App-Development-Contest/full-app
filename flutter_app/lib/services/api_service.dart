import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  final String baseUrl = 'http://192.168.45.74:8000';
  final http.Client _httpClient = http.Client();
  
  /// 사용자 UUID 키
  static const String _userUuidKey = 'app_uuid';

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
    try {
      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'app_uuid': uuid}),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200 || response.statusCode == 201) {
        debugPrint('✅ 사용자 등록/확인 성공');
      } else if (response.statusCode == 422) {
        debugPrint('⚠️ 사용자가 이미 존재함 (422) - 정상 상황');
        // 422는 이미 존재하는 사용자라는 의미이므로 정상
      } else {
        debugPrint('❌ 사용자 등록/확인 실패: ${response.statusCode}');
        debugPrint('서버 응답: ${response.body}');
      }
    } catch (e) {
      if (e.toString().contains('Connection refused') || e.toString().contains('SocketException')) {
        debugPrint('⚠️ 서버 연결 실패 - 오프라인 모드로 진행: $e');
      } else {
        debugPrint('❌ 사용자 등록/확인 오류: $e');
      }
      // 사용자 등록 실패는 앱 사용을 막지 않음 (오프라인 모드 지원)
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
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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
    try {
      final uuid = await getCurrentUserUuid();
      if (uuid == null) return null;

      final response = await _httpClient.get(
        Uri.parse('$baseUrl/api/users/settings/$uuid'),
        headers: {'Accept': 'application/json'},
      ).timeout(const Duration(seconds: 7));

      if (response.statusCode == 200) {
        final settings = jsonDecode(utf8.decode(response.bodyBytes));
        debugPrint('✅ 사용자 설정 로드 성공: $settings');
        return settings;
      } else if (response.statusCode == 404) {
        debugPrint('⚠️ 사용자 설정이 없음 - 기본 설정 생성 시도');
        // 사용자 설정이 없으면 기본 설정 생성
        final created = await _createDefaultUserSettings(uuid);
        if (created) {
          // 생성 후 다시 조회
          return await getUserSettings();
        }
        return null;
      } else {
        debugPrint('❌ 사용자 설정 로드 실패: ${response.statusCode}');
        return null;
      }
    } catch (e) {
      debugPrint('사용자 설정 로드 오류: $e');
      return null;
    }
  }

  /// 기본 사용자 설정 생성
  Future<bool> _createDefaultUserSettings(String uuid) async {
    try {
      debugPrint('🔧 기본 사용자 설정 생성 시작: $uuid');
      
      final response = await _httpClient.post(
        Uri.parse('$baseUrl/api/users/settings/initialize/$uuid'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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
      ).timeout(const Duration(seconds: 10));

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