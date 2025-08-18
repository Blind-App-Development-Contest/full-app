import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'services/voice_service.dart';
import 'screens/voice_test.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  try {
    await dotenv.load(fileName: ".env");
  } catch (e) {
    print("Warning: .env 파일을 찾을 수 없습니다: $e");
  }
  
  runApp(VoiceTestApp());
}

class VoiceTestApp extends StatelessWidget {
  const VoiceTestApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (context) => VoiceService(),
      child: MaterialApp(
        title: '음테',
        theme: ThemeData(
          primarySwatch: Colors.blue,
          visualDensity: VisualDensity.adaptivePlatformDensity,
        ),
        home: const VoiceTestScreen(),
      ));
  }
}