import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
// import 'package:flutter_secure_storage/flutter_secure_storage.dart'; // 보안 저장소로 바꿀 때 사용
import 'package:http/http.dart' as http;

import 'screens/name_screen.dart';
import 'screens/mode_screen.dart';

const String kUuidKey = 'app_uuid';

/// (옵션) 백엔드 상태 확인을 사용할지 여부
/// CommandExecutor.get_current_status()를 노출한 API가 있다고 가정
const bool kUseBackendStatusCheck = true;

/// (예시) 백엔드 상태 조회 엔드포인트
/// GET /api/app/status?uuid={uuid}  → { setup_complete: bool, current_mode: "navigation"|"camera"|... }
const String kStatusEndpointBase = 'http://localhost:8000/api/app/status';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarBrightness: Brightness.light,
    statusBarIconBrightness: Brightness.dark,
  ));

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  Future<_LaunchDecision> _decideLaunch() async {
    // ===== 1) 로컬에서 uuid 확인 =====
    final prefs = await SharedPreferences.getInstance();
    final uuid = prefs.getString(kUuidKey);
    // // 보안 저장소로 바꾸고 싶으면:
    // const storage = FlutterSecureStorage();
    // final uuid = await storage.read(key: kUuidKey);

    if (uuid == null || uuid.isEmpty) {
      return _LaunchDecision.noUuid();
    }

    // ===== 2) (옵션) 백엔드로 현재 상태 확인 =====
    if (kUseBackendStatusCheck) {
      try {
        final uri = Uri.parse('$kStatusEndpointBase?uuid=$uuid');
        final resp = await http.get(uri, headers: {'Accept': 'application/json'});
        if (resp.statusCode == 200) {
          final json = jsonDecode(resp.body) as Map<String, dynamic>;
          final setupComplete = json['setup_complete'] == true;

          // CommandExecutor 기준: setup_complete가 true면 SETUP이 끝난 상태
          if (setupComplete) {
            // (원하면 current_mode를 보고 카메라/네비 초기 화면 분기도 가능)
            return _LaunchDecision.mode();
          } else {
            return _LaunchDecision.name(); // 셋업 이어서 진행
          }
        }
        // 상태코드가 애매하면 로컬 기준으로 통과
        return _LaunchDecision.mode();
      } catch (_) {
        // 네트워크 이슈 시 UX를 위해 로컬 기준으로 통과
        return _LaunchDecision.mode();
      }
    }

    // ===== 3) 백엔드 체크 끈 경우: uuid만 있으면 바로 ModeScreen =====
    return _LaunchDecision.mode();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'A:EYE',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true),
      home: FutureBuilder<_LaunchDecision>(
        future: _decideLaunch(),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const _Splash();
          }
          final decision = snap.data ?? _LaunchDecision.name();
          switch (decision.target) {
            case _StartTarget.name:
              return const NameScreen();
            case _StartTarget.mode:
              return const ModeScreen();
          }
        },
      ),
      routes: {
        '/name': (_) => const NameScreen(),
        '/mode': (_) => const ModeScreen(),
      },
    );
  }
}

/// 단순 스플래시 위젯
class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: CircularProgressIndicator()),
    );
  }
}

/// 시작 분기용 내부 타입
enum _StartTarget { name, mode }

class _LaunchDecision {
  final _StartTarget target;
  const _LaunchDecision(this.target);

  factory _LaunchDecision.name() => const _LaunchDecision(_StartTarget.name);
  factory _LaunchDecision.mode() => const _LaunchDecision(_StartTarget.mode);

  // uuid 자체가 없으면 셋업 필요
  static _LaunchDecision noUuid() => _LaunchDecision.name();
}
