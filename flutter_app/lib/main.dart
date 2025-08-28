import 'package:flutter/material.dart';
import 'screens/name_screen.dart';  // 이름 화면 import

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'A:EYE',
      theme: ThemeData(useMaterial3: true),
      home: const NameScreen(),   // 앱 시작화면을 NameScreen으로 지정
    );
  }
}
