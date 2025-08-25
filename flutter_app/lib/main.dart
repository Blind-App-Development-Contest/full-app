// lib/main.dart
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';
import 'map_screen.dart';

const backendBaseUrl = String.fromEnvironment(
  'BACKEND_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 네이버 지도 플러그인은 웹 미지원 → 웹에선 init 스킵
  if (!kIsWeb) {
    await FlutterNaverMap().init(
      clientId: 'YOUR_NAVER_CLIENT_ID', // 실제 값으로 교체
      onAuthFailed: (e) => debugPrint('NaverMap auth failed: $e'),
    );
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    debugPrint('BACKEND_BASE_URL = $backendBaseUrl');
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: MapScreen(backendBaseUrl: backendBaseUrl),
    );
  }
}
