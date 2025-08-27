import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'services/voice_service.dart';
import 'screens/voice_test.dart';
import 'screens/camera_measurement_screen.dart';
import 'screens/step_measurement_result_screen.dart';
import 'models/step_measurement_result.dart';

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
        title: '시각장애인용 보폭 측정 앱',
        theme: ThemeData(
          primarySwatch: Colors.blue,
          visualDensity: VisualDensity.adaptivePlatformDensity,
          brightness: Brightness.dark,
          scaffoldBackgroundColor: Colors.black,
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.black,
            foregroundColor: Colors.white,
          ),
        ),
        // 앱의 화면 경로를 정의합니다.
        initialRoute: '/',
        routes: {
          '/': (context) => const VoiceTestScreen(),
          '/measurement-camera': (context) => const CameraMeasurementScreen(),
          '/measurement-result': (context) {
            final args =
                ModalRoute.of(context)!.settings.arguments
                    as Map<String, dynamic>?;
            final measurementResult = args?['result'] as StepMeasurementResult;
            final onContinue = args?['onContinue'] as VoidCallback?;

            return StepMeasurementResultScreen(
              measurementResult: measurementResult,
              onContinue: onContinue,
            );
          },
        },
      ),
    );
  }
}
