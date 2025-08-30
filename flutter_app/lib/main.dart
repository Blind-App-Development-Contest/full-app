import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'screens/name_screen.dart';
import 'screens/camera_measurement_screen.dart';
import 'services/voice_service.dart';
import 'services/api_service.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    await dotenv.load(fileName: ".env");
  } catch (e) {
    debugPrint("Warning: .env 파일을 찾을 수 없습니다: $e");
  }

  // ApiService 초기화 (사용자 UUID 생성/로드)
  try {
    await ApiService().initializeUser();
    debugPrint("✅ ApiService 초기화 완료");
  } catch (e) {
    debugPrint("❌ ApiService 초기화 실패: $e");
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [ChangeNotifierProvider(create: (context) => VoiceService())],
      child: MaterialApp(
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        title: 'A:EYE',
        theme: ThemeData(useMaterial3: true),
        home: const NameScreen(),
        routes: {
          '/measurement-camera':
              (context) => const CameraMeasurementScreen(isFromSettings: false),
        },
      ),
    );
  }
}
