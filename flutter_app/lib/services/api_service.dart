import 'dart:convert';
import 'package:http/http.dart' as http;

/// Flutter ↔ FastAPI 연동 전용 서비스
///
/// ✅ 에뮬레이터 접속 주소 참고
/// - Android 에뮬레이터: http://10.0.2.2:8000
/// - iOS 시뮬레이터:     http://127.0.0.1:8000
/// - 실기기:             PC IP 사용 (예: http://192.168.0.10:8000)
///
/// 배포 시 --dart-define로 API_BASE_URL 주입 가능:
/// flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
class ApiService {
  ApiService._();

  static final String baseUrl = const String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static const _jsonHeaders = {
    'Content-Type': 'application/json; charset=utf-8',
    'Accept': 'application/json',
  };

  static const Duration _timeout = Duration(seconds: 8);

  // ============== 공통 유틸 ==============
  static Uri _u(String path) => Uri.parse('$baseUrl$path');

  static T _decode<T>(http.Response res) {
    if (res.statusCode >= 200 && res.statusCode < 300) {
      if (res.body.isEmpty) return {} as T;
      final parsed = jsonDecode(utf8.decode(res.bodyBytes));
      return parsed as T;
    }
    throw HttpException(
      'HTTP ${res.statusCode} ${res.reasonPhrase ?? ''}',
      url: res.request?.url.toString(),
      body: res.body,
    );
  }

  // 서버 상태 확인 (선택)
  static Future<bool> ping() async {
    try {
      final res = await http.get(_u('/health')).timeout(_timeout);
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

// ============== 엔드포인트 ==============