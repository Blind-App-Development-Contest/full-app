import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:camera/camera.dart';

import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'screens/name_screen.dart';
import 'screens/mode_screen.dart';
import 'screens/camera_measurement_screen.dart'; // 필요 없으면 제거
import 'services/api_service.dart';
import 'services/voice_service.dart';
import 'services/onboarding_service.dart';
import 'constants/config.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

const String kUuidKey = 'app_uuid';

/// (옵션) 백엔드 상태 확인 사용 여부
const bool kUseBackendStatusCheck = true;

/// 기본 상태 조회 엔드포인트 (dotenv 가 있으면 그걸 우선)
// const String kStatusEndpointBaseDefault = 'http://localhost:8000/api/users/measurement/';
const String kStatusEndpointBaseDefault = 'https://aeye-gvu9.onrender.com/api/users/measurement/';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 시스템 UI (상태바 아이콘/밝기)
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarBrightness: Brightness.light,
    statusBarIconBrightness: Brightness.dark,
  ));

  // .env 로드 (없어도 동작)
  try {
    await dotenv.load(fileName: ".env");
  } catch (e) {
    debugPrint("Warning: .env 파일을 찾을 수 없습니다: $e");
  }

  // NaverMap SDK 초기화
  try {
    // 환경변수에서 클라이언트 ID를 가져오되, 없으면 플랫폼별 설정을 사용
    final clientId = dotenv.env['NAVER_MAP_CLIENT_ID'];
    
    if (clientId != null && clientId.isNotEmpty && clientId != 'YOUR_NAVER_MAP_CLIENT_ID_HERE') {
      // 유효한 클라이언트 ID가 있는 경우
      await NaverMapSdk.instance.initialize(
        clientId: clientId,
        onAuthFailed: (error) {
          debugPrint("❌ NaverMap 인증 실패: $error");
          debugPrint("💡 해결방법:");
          debugPrint("   1. 네이버 클라우드 플랫폼에서 클라이언트 ID 발급");
          debugPrint("   2. .env 파일에 NAVER_MAP_CLIENT_ID 설정");
          debugPrint("   3. iOS: Info.plist의 NMFNcpKeyId 값 설정");
          debugPrint("   4. Android: AndroidManifest.xml의 com.naver.maps.map.CLIENT_ID 값 설정");
        },
      );
      debugPrint("✅ NaverMap SDK 초기화 완료 (클라이언트 ID: ${clientId.substring(0, 8)}...)");
    } else {
      // 클라이언트 ID가 없는 경우 플랫폼별 설정 사용
      debugPrint("⚠️ .env에 NAVER_MAP_CLIENT_ID가 설정되지 않음");
      debugPrint("📱 플랫폼별 설정 파일에서 클라이언트 ID를 읽어옵니다:");
      debugPrint("   - iOS: Info.plist의 NMFNcpKeyId");
      debugPrint("   - Android: AndroidManifest.xml의 com.naver.maps.map.CLIENT_ID");
      
      await NaverMapSdk.instance.initialize(
        clientId: '', // 플랫폼별 설정에서 자동으로 읽어옴
        onAuthFailed: (error) {
          debugPrint("❌ NaverMap 인증 실패: $error");
          debugPrint("💡 해결방법:");
          debugPrint("   1. 네이버 클라우드 플랫폼(https://console.ncloud.com/)에서 클라이언트 ID 발급");
          debugPrint("   2. iOS: Info.plist의 NMFNcpKeyId에 클라이언트 ID 입력");
          debugPrint("   3. Android: AndroidManifest.xml의 com.naver.maps.map.CLIENT_ID에 클라이언트 ID 입력");
          debugPrint("   4. 또는 .env 파일 생성 후 NAVER_MAP_CLIENT_ID 설정");
        },
      );
      debugPrint("✅ NaverMap SDK 초기화 시도 완료 (플랫폼별 설정 사용)");
    }
  } catch (e) {
    debugPrint("❌ NaverMap SDK 초기화 실패: $e");
    debugPrint("💡 문제 해결을 위해 다음을 확인하세요:");
    debugPrint("   1. 네이버 클라우드 플랫폼에서 클라이언트 ID 발급 여부");
    debugPrint("   2. 플랫폼별 설정 파일에 클라이언트 ID 정확히 입력 여부");
    debugPrint("   3. 인터넷 연결 상태");
  }

  // 앱을 먼저 시작하고 백그라운드에서 초기화 (iPhone 최적화)
  runApp(const MyApp());
  
  // 백그라운드에서 초기화 작업 수행 (UI 차단하지 않음)
  _initializeInBackground();
}

/// ApiService 초기화
Future<void> _initializeApiService() async {
  try {
    await ApiService().initializeUser();
    debugPrint("✅ ApiService 초기화 완료");
  } catch (e) {
    debugPrint("❌ ApiService 초기화 실패: $e");
  }
}

/// 백그라운드 초기화 (UI 차단하지 않음)
Future<void> _initializeInBackground() async {
  // 병렬로 초기화 작업 수행
  await Future.wait([
    // 사용자 UUID 생성/로드
    _initializeApiService(),
    // 카메라 권한 미리 확인 (카메라 화면 진입 속도 향상)
    _preCheckCameraPermission(),
  ]);
}

/// 카메라 권한 미리 확인
Future<void> _preCheckCameraPermission() async {
  try {
    final cameras = await availableCameras();
    debugPrint("📷 백그라운드 카메라 권한 확인 완료 - 카메라 ${cameras.length}개 발견");
  } catch (e) {
    debugPrint("⚠️ 백그라운드 카메라 권한 확인 실패: $e");
  }
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => VoiceService(), lazy: true),
        ChangeNotifierProvider(create: (_) => OnboardingService(), lazy: true),
      ],
      child: MaterialApp(
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        title: 'A:EYE',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
          useMaterial3: true,
        ),
        home: const _StartupRouter(),
      ),
    );
  }
}

class _StartupRouter extends StatefulWidget {
  const _StartupRouter();
  @override
  State<_StartupRouter> createState() => _StartupRouterState();
}

class _StartupRouterState extends State<_StartupRouter> {
  Widget? _start;

  @override
  void initState() {
    super.initState();
    _decideStartScreen();
  }

  Future<void> _decideStartScreen() async {
    final prefs = await SharedPreferences.getInstance();
    final name = prefs.getString('user_name')?.trim();
    final uuid = prefs.getString(kUuidKey) ?? '';

    // .env 우선, 없으면 기본값
    final statusBase =
        dotenv.env['STATUS_ENDPOINT_BASE'] ?? AppConfig.measurementEndpoint;

    // 기본 기준: 이름 저장돼 있으면 ModeScreen, 아니면 NameScreen
    Widget fallback = const ModeScreen();
    if (name == null || name.isEmpty) {
      fallback = const NameScreen();
    }

    // 백엔드 상태 체크 옵션
    if (!kUseBackendStatusCheck || uuid.isEmpty) {
      setState(() => _start = fallback);
      return;
    }

    try {
      final uri = Uri.parse('$statusBase?uuid=$uuid');
      final resp = await http.get(uri).timeout(const Duration(seconds: 5));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final setupComplete = data['setup_complete'] == true;
        setState(() => _start = setupComplete ? const ModeScreen() : const NameScreen());
      } else {
        debugPrint('Status check failed: ${resp.statusCode}');
        setState(() => _start = fallback);
      }
    } catch (e) {
      debugPrint('Status check error: $e');
      setState(() => _start = fallback);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_start == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return _start!;
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

class _AlternativeStartup extends StatefulWidget {
  const _AlternativeStartup();
  
  @override
  State<_AlternativeStartup> createState() => _AlternativeStartupState();
}

class _AlternativeStartupState extends State<_AlternativeStartup> {
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
        final uri = Uri.parse('${AppConfig.measurementEndpoint}?uuid=$uuid');
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
    return MultiProvider(
      providers: [ChangeNotifierProvider(create: (context) => VoiceService())],
      child: MaterialApp(
        navigatorKey: navigatorKey,
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
          '/measurement-camera':
              (context) => const CameraMeasurementScreen(isFromSettings: false),
        },
      ),
    );
  }
}

