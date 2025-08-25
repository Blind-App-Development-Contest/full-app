// lib/directions_api.dart
import 'dart:convert';
import 'package:http/http.dart' as http;

/// 1개 라우트만 쓰는 간단 모델 (필요하면 routes 전체로 확장 가능)
class DirectionsResponse {
  final bool hasRoute;
  final String provider;
  final String distanceText;
  final String durationText;
  final List<List<double>> pathLngLat; // [[lng,lat], ...]

  DirectionsResponse({
    required this.hasRoute,
    required this.provider,
    required this.distanceText,
    required this.durationText,
    required this.pathLngLat,
  });

  static T? _pick<T>(Map m, String snake, String camel) {
    final v = m[snake] ?? m[camel];
    if (v is T) return v;
    return null;
  }

  factory DirectionsResponse.fromJson(Map<String, dynamic> json) {
    final provider = (json['provider'] ?? '') as String? ?? '';
    final routes = (json['routes'] as List?) ?? const [];
    if (routes.isEmpty) {
      return DirectionsResponse(
        hasRoute: false,
        provider: provider,
        distanceText: '',
        durationText: '',
        pathLngLat: const [],
      );
    }
    final r0 = routes.first as Map? ?? const {};
    final distanceText =
        _pick<String>(r0 as Map, 'distance_text', 'distanceText') ?? '';
    final durationText =
        _pick<String>(r0, 'duration_text', 'durationText') ?? '';
    final rawPath = _pick<List>(r0, 'path_lnglat', 'pathLngLat') ?? const [];

    final path = <List<double>>[];
    for (final p in rawPath) {
      if (p is List && p.length == 2) {
        final lng = double.tryParse('${p[0]}');
        final lat = double.tryParse('${p[1]}');
        if (lng != null && lat != null) {
          path.add([lng, lat]);
        }
      }
    }

    return DirectionsResponse(
      hasRoute: path.isNotEmpty,
      provider: provider,
      distanceText: distanceText,
      durationText: durationText,
      pathLngLat: path,
    );
  }
}

class DirectionsApi {
  final String baseUrl;
  DirectionsApi(this.baseUrl);

  Uri _u(String path) {
    final b = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    final p = path.startsWith('/') ? path : '/$path';
    return Uri.parse('$b$p');
  }

  Future<bool> ping() async {
    // 여러 엔드포인트를 순차로 시도 (있으면 true)
    for (final path in const ['/health', '/ping', '/']) {
      try {
        final r = await http.get(_u(path)).timeout(const Duration(seconds: 5));
        if (r.statusCode < 500) return true; // 2xx/3xx/4xx면 서버는 켜져 있음
      } catch (_) {/* 계속 다음 시도 */}
    }
    return false;
    // 필요하다면 maps.py에 GET /ping 하나 추가해도 좋아요.
  }

  Future<DirectionsResponse> getRoute({
    required String origin,
    required String destination,
    String mode = 'walking', // 'walking'|'driving'
    List<String>? waypoints,
  }) async {
    final body = jsonEncode({
      'origin': origin,
      'destination': destination,
      'mode': mode,
      if (waypoints != null && waypoints.isNotEmpty) 'waypoints': waypoints,
    });

    final r = await http
        .post(
          _u('/maps/directions'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(const Duration(seconds: 20));

    if (r.statusCode >= 400) {
      throw Exception('Directions error ${r.statusCode}: ${r.body}');
    }
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return DirectionsResponse.fromJson(data);
  }
}
