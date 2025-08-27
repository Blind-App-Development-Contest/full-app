// lib/main.dart
import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'map_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // .env 파일 로드
  try {
    await dotenv.load(fileName: ".env");
    debugPrint('✅ .env file loaded successfully');
  } catch (e) {
    debugPrint('⚠️ Failed to load .env file: $e');
  }

  // 네이버 지도 초기화 (실패해도 앱 실행 계속)
  if (!kIsWeb) {
    await _initializeNaverMap();
  }

  runApp(const MyApp());
}

Future<void> _initializeNaverMap() async {
  const maxRetries = 3;

  for (int retry = 0; retry < maxRetries; retry++) {
    try {
      debugPrint('Initializing NaverMap... (attempt ${retry + 1}/$maxRetries)');

      // 재시도 시에는 더 긴 대기
      if (retry > 0) {
        await Future.delayed(Duration(milliseconds: 500 * (retry + 1)));
      }

      await FlutterNaverMap()
          .init(
            clientId: '5z23wo0mnc',
            onAuthFailed: (e) {
              debugPrint('NaverMap auth failed: $e');
            },
          )
          .timeout(
            const Duration(seconds: 8), // 타임아웃 단축
            onTimeout: () {
              debugPrint('NaverMap init timeout (attempt ${retry + 1})');
              throw TimeoutException(
                'NaverMap init timeout',
                const Duration(seconds: 8),
              );
            },
          );

      debugPrint('✅ NaverMap initialized successfully on attempt ${retry + 1}');
      return; // 성공시 즉시 종료
    } catch (e) {
      debugPrint('⚠️ NaverMap init failed (attempt ${retry + 1}): $e');

      if (retry == maxRetries - 1) {
        debugPrint(
          '❌ All NaverMap init attempts failed. Continuing without NaverMap...',
        );
      }
    }
  }
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    // .env에서 백엔드 URL 가져오기 (기본값: 새 IP)
    final backendBaseUrl =
        dotenv.env['BACKEND_BASE_URL'] ?? 'http://192.168.45.217:8000';
    debugPrint('BACKEND_BASE_URL = $backendBaseUrl');

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: MapScreen(backendBaseUrl: backendBaseUrl),
    );
  }
}
