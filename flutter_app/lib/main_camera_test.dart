import 'package:flutter/material.dart';
import 'screens/camera_mode_screen.dart'; // Use relative path

void main() {
  // View factory registration is now handled inside CameraModeScreen.
  // No need to register it here.
  runApp(const MaterialApp(
    home: CameraModeScreen(), // Use the correct constructor
  ));
}
