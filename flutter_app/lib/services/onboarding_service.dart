import 'package:flutter/material.dart';
import 'api_service.dart';

/// 온보딩 과정에서 수집되는 사용자 정보를 관리하는 서비스
class OnboardingService with ChangeNotifier {
  static final OnboardingService _instance = OnboardingService._internal();
  factory OnboardingService() => _instance;
  OnboardingService._internal();

  // 온보딩 수집 데이터
  String _userName = '';
  String _voiceGender = 'F'; // F or M
  int _voiceSpeed = 10; // 1-20 (10이 기본)
  int step_length_cm = 0; // 백엔드와 동일한 변수명
  String _caregiverName = '';
  String _caregiverPhone = '';

  bool _isCompleted = false;

  // Getters
  String get userName => _userName;
  String get voiceGender => _voiceGender;
  int get voiceSpeed => _voiceSpeed;
  int get stepLengthCm => step_length_cm;
  String get caregiverName => _caregiverName;
  String get caregiverPhone => _caregiverPhone;
  bool get isCompleted => _isCompleted;

  // Setters
  void setUserName(String name) {
    _userName = name;
    notifyListeners();
  }

  void setVoiceSettings(String gender, int speed) {
    _voiceGender = gender;
    _voiceSpeed = speed;
    notifyListeners();
  }

  void setStepLength(int stepLengthCm) {
    step_length_cm = stepLengthCm;
    notifyListeners();
  }

  void setCaregiverInfo(String name, String phone) {
    _caregiverName = name;
    _caregiverPhone = phone;
    notifyListeners();
  }

  /// 온보딩 완료 처리 - 모든 데이터를 서버에 전송
  Future<bool> completeOnboarding() async {
    try {
      debugPrint('📋 온보딩 데이터 전송 시작');
      debugPrint('👤 사용자: $_userName');
      debugPrint('🎙️ 음성: $_voiceGender, 속도: $_voiceSpeed');
      debugPrint('📏 보폭: ${step_length_cm}cm');
      debugPrint('👨‍👩‍👧‍👦 보호자: $_caregiverName ($_caregiverPhone)');

      final result = await ApiService().completeOnboarding({
        'userName': _userName,
        'voiceGender': _voiceGender,
        'voiceSpeed': _voiceSpeed,
        'stepLengthCm': step_length_cm,
        'caregiverName': _caregiverName,
        'caregiverPhone': _caregiverPhone,
      });

      if (result) {
        _isCompleted = true;
        notifyListeners();
        debugPrint('✅ 온보딩 완료 성공');
        return true;
      } else {
        debugPrint('❌ 온보딩 완료 실패: $result');
        return false;
      }
    } catch (e) {
      debugPrint('❌ 온보딩 완료 오류: $e');
      return false;
    }
  }

  /// 온보딩 데이터 초기화 (테스트용)
  void reset() {
    _userName = '';
    _voiceGender = 'F';
    _voiceSpeed = 10;
    step_length_cm = 0;
    _caregiverName = '';
    _caregiverPhone = '';
    _isCompleted = false;
    notifyListeners();
  }

  /// 온보딩 데이터 유효성 검증
  bool get isDataValid {
    return _userName.isNotEmpty &&
           step_length_cm > 0 &&
           _caregiverName.isNotEmpty &&
           _caregiverPhone.isNotEmpty;
  }
}