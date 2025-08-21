import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'services/voice_service.dart';
import 'screens/voice_test.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    await dotenv.load(fileName: ".env");
  } catch (e) {
    print("Warning: .env 파일을 찾을 수 없습니다: $e");
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    // MultiProvider를 사용하여 여러 서비스를 앱 전체에 제공합니다.
    return MultiProvider(
      providers: [
        // VoiceService를 생성할 때 navigatorKey를 전달합니다.
        ChangeNotifierProvider(
          create: (context) => VoiceService(navigatorKey: navigatorKey),
        ),
        // CameraService도 앱 전체에서 사용할 수 있도록 제공합니다.
        // ChangeNotifierProvider(create: (context) => CameraService()),
      ],
      child: MaterialApp(
        // MaterialApp에 navigatorKey를 연결합니다.
        navigatorKey: navigatorKey,
        title: 'Voice Measurement App',
        theme: ThemeData(
          primarySwatch: Colors.blue,
          visualDensity: VisualDensity.adaptivePlatformDensity,
        ),
        // 앱의 화면 경로를 정의합니다.
        initialRoute: '/',
        routes: {
          '/': (context) => const VoiceTestScreen(),
          // '/measurement-camera' 경로를 MeasurementCameraScreen과 연결합니다.
          // '/measurement-camera': (context) => const MeasurementCameraScreen(),
        },
      ),
    );
  }
}
