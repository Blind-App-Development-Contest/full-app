// lib/directions_api.dart
import 'dart:convert';
import 'package:flutter/foundation.dart';
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
    final b =
        baseUrl.endsWith('/')
            ? baseUrl.substring(0, baseUrl.length - 1)
            : baseUrl;
    final p = path.startsWith('/') ? path : '/$path';
    return Uri.parse('$b$p');
  }

  Future<Map<String, dynamic>> pingDiagnostic() async {
    final results = <String, dynamic>{
      'baseUrl': baseUrl,
      'tests': <Map<String, dynamic>>[],
      'isConnected': false,
      'error': null,
    };

    // 여러 엔드포인트를 순차로 시도하며 상세 정보 수집
    for (final path in const ['/maps/directions', '/health', '/ping', '/']) {
      final testResult = <String, dynamic>{
        'endpoint': path,
        'url': _u(path).toString(),
        'success': false,
        'statusCode': null,
        'error': null,
        'responseTime': null,
      };

      try {
        final stopwatch = Stopwatch()..start();
        final r = await http.get(_u(path)).timeout(const Duration(seconds: 8));
        stopwatch.stop();
        
        testResult['success'] = r.statusCode < 500;
        testResult['statusCode'] = r.statusCode;
        testResult['responseTime'] = '${stopwatch.elapsedMilliseconds}ms';
        
        if (r.statusCode < 500) {
          results['isConnected'] = true;
        }
      } catch (e) {
        testResult['error'] = e.toString();
        if (e.toString().contains('Connection refused') || 
            e.toString().contains('Network is unreachable')) {
          testResult['diagnosis'] = 'Server is down or unreachable';
        } else if (e.toString().contains('TimeoutException')) {
          testResult['diagnosis'] = 'Server is slow or overloaded';
        } else if (e.toString().contains('SocketException')) {
          testResult['diagnosis'] = 'Network connectivity issue';
        }
      }
      
      results['tests'].add(testResult);
    }

    return results;
  }

  Future<bool> ping() async {
    final diagnostic = await pingDiagnostic();
    return diagnostic['isConnected'] as bool;
  }

  Future<DirectionsResponse> getRoute({
    required String origin,
    required String destination,
    List<String>? waypoints,
  }) async {
    final body = jsonEncode({
      'origin': origin,
      'destination': destination,
      'mode': 'walking', // 도보만 지원
      if (waypoints != null && waypoints.isNotEmpty) 'waypoints': waypoints,
    });

    // 최대 3번 재시도
    Exception? lastError;
    for (int attempt = 1; attempt <= 3; attempt++) {
      try {
        debugPrint('Route request attempt $attempt/3 to: ${_u('/maps/directions')}');
        
        final r = await http
            .post(
              _u('/maps/directions'),
              headers: {'Content-Type': 'application/json'},
              body: body,
            )
            .timeout(const Duration(seconds: 45));

        debugPrint('Route response: ${r.statusCode} (attempt $attempt)');

        if (r.statusCode >= 400) {
          final errorMsg = 'Directions error ${r.statusCode}: ${r.body}';
          debugPrint(errorMsg);
          
          // 4xx 에러는 재시도하지 않음 (클라이언트 오류)
          if (r.statusCode < 500) {
            throw Exception(errorMsg);
          }
          
          // 5xx 에러는 재시도 가능
          lastError = Exception(errorMsg);
          if (attempt < 3) {
            await Future.delayed(Duration(seconds: attempt * 2));
            continue;
          }
          throw lastError!;
        }

        final data = jsonDecode(r.body) as Map<String, dynamic>;
        return DirectionsResponse.fromJson(data);
        
      } catch (e) {
        debugPrint('Route request failed (attempt $attempt): $e');
        lastError = e is Exception ? e : Exception(e.toString());
        
        // 연결 거부나 타임아웃이면 재시도
        final errorStr = e.toString();
        if ((errorStr.contains('Connection refused') || 
             errorStr.contains('TimeoutException') ||
             errorStr.contains('SocketException')) && 
            attempt < 3) {
          debugPrint('Retrying in ${attempt * 2} seconds...');
          await Future.delayed(Duration(seconds: attempt * 2));
          continue;
        }
        
        // 마지막 시도였으면 에러 던지기
        if (attempt == 3) {
          String diagnosis = 'Network error';
          if (errorStr.contains('Connection refused')) {
            diagnosis = 'Server is down or unreachable (Connection refused)';
          } else if (errorStr.contains('TimeoutException')) {
            diagnosis = 'Request timeout - server may be overloaded';
          } else if (errorStr.contains('SocketException')) {
            diagnosis = 'Network connectivity issue';
          }
          
          throw Exception('$diagnosis\nOriginal error: ${lastError.toString()}');
        }
      }
    }
    
    throw lastError!;
  }
}
