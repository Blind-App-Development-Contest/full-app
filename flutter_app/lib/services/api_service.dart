import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

/// 백엔드 API 통신을 담당하는 서비스
class ApiService {
  static const String baseUrl = 'http://192.168.45.74:8000';
  static const String _userIdKey = 'user_uuid';
  static const String _userNameKey = 'user_name';

  // DB 연동 활성화/비활성화 플래그 (테스트용)
  static const bool enableDatabaseSync = false; // false로 설정하면 DB 연동 비활성화

  // 싱글톤 패턴
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  String? _userId;
  String? _userName;

  /// 사용자 ID 초기화 (앱 시작시 호출)
  Future<void> initializeUser() async {
    final prefs = await SharedPreferences.getInstance();
    
    // 기존 사용자 ID 확인
    _userId = prefs.getString(_userIdKey);
    _userName = prefs.getString(_userNameKey);
    
    if (_userId == null) {
      // 새로운 사용자 ID 생성
      _userId = const Uuid().v4();
      await prefs.setString(_userIdKey, _userId!);
      debugPrint('🆔 새로운 사용자 ID 생성: $_userId');
    } else {
      debugPrint('🆔 기존 사용자 ID 사용: $_userId');
    }
  }

  /// 현재 사용자 ID 반환
  String? get userId => _userId;
  String? get userName => _userName;

  /// 사용자 이름 업데이트
  Future<void> updateUserName(String name) async {
    final prefs = await SharedPreferences.getInstance();
    _userName = name;
    await prefs.setString(_userNameKey, name);
    
    // 백엔드에 사용자 등록/업데이트
    try {
      await registerUser(name);
    } catch (e) {
      debugPrint('❌ 사용자 등록 실패: $e');
    }
  }

  /// 사용자 등록 API 호출
  Future<Map<String, dynamic>> registerUser(String? userName) async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    try {
      final response = await http.post(
        Uri.parse('$baseUrl/users/register'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'app_uuid': _userId,
          'user_name': userName,
        }),
      );

      debugPrint('👤 사용자 등록 API 호출: ${response.statusCode}');
      debugPrint('👤 응답: ${response.body}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data;
      } else {
        throw Exception('사용자 등록 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 사용자 등록 오류: $e');
      rethrow;
    }
  }

  /// 보폭 저장 API 호출
  Future<Map<String, dynamic>> saveStepLength(int stepLengthCm) async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    // DB 연동 비활성화시 성공 응답 반환
    if (!enableDatabaseSync) {
      return {'test_mode': true, 'step_length_cm': stepLengthCm};
    }

    try {
      debugPrint('📏 보폭 저장 시작: ${stepLengthCm}cm (사용자: $_userId)');

      final response = await http.post(
        Uri.parse('$baseUrl/footstep/update'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'user_id': _userId,
          'step_length_cm': stepLengthCm,
        }),
      );

      debugPrint('📏 보폭 저장 API 호출: ${response.statusCode}');
      debugPrint('📏 응답: ${response.body}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 보폭 저장 성공: ${stepLengthCm}cm');
        return data;
      } else {
        throw Exception('보폭 저장 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 보폭 저장 오류: $e');
      rethrow;
    }
  }

  /// 사용자 보폭 조회 API 호출
  Future<Map<String, dynamic>?> getUserStepLength() async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    try {
      final response = await http.get(
        Uri.parse('$baseUrl/footstep/user/$_userId'),
        headers: {
          'Content-Type': 'application/json',
        },
      );

      debugPrint('📏 보폭 조회 API 호출: ${response.statusCode}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 보폭 조회 성공: ${data['step_length_cm']}cm');
        return data;
      } else if (response.statusCode == 404) {
        debugPrint('📏 사용자 보폭 정보 없음');
        return null;
      } else {
        throw Exception('보폭 조회 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 보폭 조회 오류: $e');
      return null;
    }
  }

  /// 측정 결과 저장 API 호출
  Future<Map<String, dynamic>> saveMeasurementResult({
    required int stepLengthCm,
    int? sessionDurationSeconds,
    int? frameCount,
    String? measurementType,
  }) async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    try {
      debugPrint('📊 측정 결과 저장 시작: ${stepLengthCm}cm');

      final response = await http.post(
        Uri.parse('$baseUrl/api/users/measurement/results/save'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'user_id': _userId,
          'step_length_cm': stepLengthCm,
          'session_duration_seconds': sessionDurationSeconds,
          'frame_count': frameCount,
          'measurement_type': measurementType ?? 'camera_measurement',
        }),
      );

      debugPrint('📊 측정 결과 저장 API 호출: ${response.statusCode}');
      debugPrint('📊 응답: ${response.body}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 측정 결과 저장 성공');
        return data;
      } else {
        throw Exception('측정 결과 저장 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 측정 결과 저장 오류: $e');
      rethrow;
    }
  }

  /// 음성 설정 저장 API 호출
  Future<Map<String, dynamic>> saveVoiceSettings({
    required String gender, // 'female' or 'male'
    required double speed,   // 0.5 ~ 2.0
  }) async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    // DB 연동 비활성화시 성공 응답 반환
    if (!enableDatabaseSync) {
      return {'test_mode': true, 'gender': gender, 'speed': speed};
    }

    try {
      debugPrint('🎙️ 음성 설정 저장 시도: $gender, ${speed}x (사용자: $_userId)');

      final response = await http.patch(
        Uri.parse('$baseUrl/api/users/$_userId/voice'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'gender': gender,
          'speed': speed,
        }),
      );

      debugPrint('🎙️ 음성 설정 저장 API 호출: ${response.statusCode}');
      debugPrint('🎙️ 응답: ${response.body}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 음성 설정 저장 성공: $gender, ${speed}x');
        return data;
      } else {
        throw Exception('음성 설정 저장 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 음성 설정 저장 오류: $e');
      rethrow;
    }
  }

  /// 음성 설정 조회 API 호출
  Future<Map<String, dynamic>?> getVoiceSettings() async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    try {
      final response = await http.get(
        Uri.parse('$baseUrl/api/users/$_userId/voice'),
        headers: {
          'Content-Type': 'application/json',
        },
      );

      debugPrint('🎙️ 음성 설정 조회 API 호출: ${response.statusCode}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 음성 설정 조회 성공: ${data['gender']}, ${data['speed']}x');
        return data;
      } else if (response.statusCode == 404) {
        debugPrint('🎙️ 사용자 음성 설정 없음');
        return null;
      } else {
        throw Exception('음성 설정 조회 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 음성 설정 조회 오류: $e');
      return null;
    }
  }

  /// 온보딩 완료 API 호출
  Future<Map<String, dynamic>> completeOnboarding({
    required String userName,
    required String voiceGender,
    required int voiceSpeed,
    required int stepLengthCm,
    required String caregiverName,
    required String caregiverPhone,
  }) async {
    if (_userId == null) {
      throw Exception('사용자 ID가 초기화되지 않았습니다');
    }

    // DB 연동 비활성화시 성공 응답 반환
    if (!enableDatabaseSync) {
      return {
        'test_mode': true,
        'status': 'onboarding_completed',
        'user_id': _userId,
        'user_name': userName,
        'step_length_cm': stepLengthCm,
        'voice_settings': {'gender': voiceGender, 'speed': voiceSpeed},
      };
    }

    try {
      debugPrint('📋 온보딩 완료 데이터 전송 시작: $userName (사용자: $_userId)');

      final response = await http.post(
        Uri.parse('$baseUrl/api/users/onboarding/complete'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'user_id': _userId,
          'user_name': userName,
          'voice_gender': voiceGender,
          'voice_speed': voiceSpeed,
          'step_length_cm': stepLengthCm,
          'caregiver_name': caregiverName,
          'caregiver_phone': caregiverPhone,
        }),
      );

      debugPrint('📋 온보딩 완료 API 호출: ${response.statusCode}');
      debugPrint('📋 응답: ${response.body}');

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        debugPrint('✅ 온보딩 완료 성공: $userName');
        return data;
      } else {
        throw Exception('온보딩 완료 실패: ${response.statusCode} ${response.body}');
      }
    } catch (e) {
      debugPrint('❌ 온보딩 완료 오류: $e');
      rethrow;
    }
  }

  /// 네트워크 연결 상태 확인
  Future<bool> checkConnection() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/health'),
        headers: {'Content-Type': 'application/json'},
      ).timeout(const Duration(seconds: 5));

      return response.statusCode == 200;
    } catch (e) {
      debugPrint('🌐 네트워크 연결 확인 실패: $e');
      return false;
    }
  }
}