import 'package:flutter_dotenv/flutter_dotenv.dart';

/// 앱 설정 상수들
class AppConfig {
  /// 백엔드 서버 기본 URL
  static String get backendBaseUrl => 
      // dotenv.env['BACKEND_BASE_URL'] ?? 'http://localhost:8000';
dotenv.env['BACKEND_BASE_URL'] ?? 'https://aeye-gvu9.onrender.com';
  
  /// 측정 관련 엔드포인트 URL
  static String get measurementEndpoint => 
      '$backendBaseUrl/api/users/measurement/';
  
  /// 사용자 등록 엔드포인트 URL
  static String get userRegisterEndpoint => 
      '$backendBaseUrl/api/users/register';
      
  /// 측정 세션 시작 엔드포인트 URL
  static String get measurementSessionStartEndpoint => 
      '$backendBaseUrl/api/users/measurement/session/start';
      
  /// 측정 세션 중지 엔드포인트 URL
  static String get measurementSessionStopEndpoint => 
      '$backendBaseUrl/api/users/measurement/session/stop';
      
  /// 측정 프레임 처리 엔드포인트 URL
  static String get measurementFrameEndpoint => 
      '$backendBaseUrl/api/users/measurement/frame';
}
