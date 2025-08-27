import 'package:flutter/material.dart';

class CameraModeScreen extends StatefulWidget {
  const CameraModeScreen({super.key});

  @override
  State<CameraModeScreen> createState() => _CameraModeScreenState();
}

class _CameraModeScreenState extends State<CameraModeScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            // 실시간 카메라 스트리밍 뷰 (실제 카메라 위젯으로 교체 필요)
            const Center(
              child: Icon(
                Icons.camera_alt,
                color: Colors.grey,
                size: 100.0,
              ),
            ),

            // 상단 '카메라 모드' 텍스트
            const Positioned(
              top: 20,
              left: 20,
              child: Text(
                '카메라 모드',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),

            // 하단 버튼 바
            Positioned(
              bottom: 20,
              left: 20,
              right: 20,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 15.0, horizontal: 10.0),
                decoration: BoxDecoration(
                  color: Colors.black.withOpacity(0.7),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _buildBottomButton(
                      icon: Icons.text_fields,
                      label: '텍스트읽기',
                      onPressed: () { /* TODO: 텍스트읽기 기능 구현 */ },
                    ),
                    _buildBottomButton(
                      icon: Icons.navigation,
                      label: '길찾기',
                      onPressed: () { /* TODO: 길찾기 기능 구현 */ },
                    ),
                    _buildBottomButton(
                      icon: Icons.phone,
                      label: '보호자호출',
                      onPressed: () { /* TODO: 보호자호출 기능 구현 */ },
                    ),
                    _buildBottomButton(
                      icon: Icons.settings,
                      label: '설정',
                      onPressed: () { /* TODO: 설정 기능 구현 */ },
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBottomButton({required IconData icon, required String label, required VoidCallback onPressed}) {
    return GestureDetector(
      onTap: onPressed,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white, size: 30),
          const SizedBox(height: 8),
          Text(
            label,
            style: const TextStyle(color: Colors.white, fontSize: 12),
          ),
        ],
      ),
    );
  }
}