import 'package:flutter_test/flutter_test.dart';
import 'package:blind/main.dart';

void main() {
  testWidgets('App starts with NameScreen', (WidgetTester tester) async {
    await tester.pumpWidget(const MyApp());
    
    expect(find.text('A:EYE'), findsWidgets);
  });
}
