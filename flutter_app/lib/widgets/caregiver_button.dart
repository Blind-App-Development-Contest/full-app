import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class CaregiverButton extends StatefulWidget {
  const CaregiverButton({
    super.key,
    required this.backendBaseUrl,
    this.panel,
    this.divider,
    this.caption,
    this.onCompleted,
  });

  /// 예: AppConfig.backendBaseUrl
  final String backendBaseUrl;

  /// 스타일(선택): Mode 카드와 톤 맞추기
  final Color? panel;
  final Color? divider;
  final Color? caption;

  /// (ok, message) 콜백
  final void Function(bool ok, String? message)? onCompleted;

  @override
  State<CaregiverButton> createState() => _CaregiverButtonState();
}

class _CaregiverButtonState extends State<CaregiverButton> {
  final http.Client _client = http.Client();
  bool _loading = false;

  String get _resolvedBaseUrl {
    if (kIsWeb) return widget.backendBaseUrl;
    // Android 에뮬레이터에서 localhost → 10.0.2.2 보정
    if (Platform.isAndroid &&
        (widget.backendBaseUrl.contains('localhost') ||
            widget.backendBaseUrl.contains('127.0.0.1'))) {
      return widget.backendBaseUrl.replaceFirst(RegExp(r'localhost|127\.0\.0\.1'), '10.0.2.2');
    }
    return widget.backendBaseUrl;
  }

  /// 앱 초기화 시 저장해둔 UUID를 user_id로 사용
  Future<String> _loadUserId() async {
    final prefs = await SharedPreferences.getInstance();
    final uuid = prefs.getString('app_uuid') ?? prefs.getString('uuid');
    if (uuid == null || uuid.isEmpty) {
      throw StateError('user_id(UUID)가 없습니다. 앱 초기화에서 uuid를 먼저 생성/저장하세요.');
    }
    return uuid;
  }

  Future<void> _callCaregiver() async {
    setState(() => _loading = true);

    bool ok = false;
    String? message;

    try {
      final userId = await _loadUserId();
      final uri = Uri.parse('$_resolvedBaseUrl/api/users/caregiver/alert');

      final headers = {'Content-Type': 'application/json'};
      final body = jsonEncode({
        'user_id': userId,           // ✅ uuid를 user_id 필드로 전송
        'reason': 'manual_alert',    // 선택 필드(백엔드에서 무시 가능)
      });

      final resp = await _client
          .post(uri, headers: headers, body: body)
          .timeout(const Duration(seconds: 10));

      if (resp.statusCode == 200) {
        ok = true;
        message = '✅ 보호자에게 호출이 전달되었습니다.';
        if (resp.body.isNotEmpty) {
          try {
            final data = jsonDecode(resp.body);
            if (data is Map && data['message'] is String) {
              message = data['message'] as String;
            }
          } catch (_) {}
        }
      } else if (resp.statusCode == 422) {
        message = '⚠️ 요청 형식 오류(422): ${resp.body}';
      } else {
        message = '⚠️ 호출 실패: ${resp.statusCode}${resp.body.isNotEmpty ? ' / ${resp.body}' : ''}';
      }
    } on TimeoutException {
      message = '⏰ 서버 응답 지연(타임아웃)';
    } on StateError catch (e) {
      message = '❌ 설정 오류: ${e.message}';
    } catch (e) {
      message = '❌ 오류 발생: $e';
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        widget.onCompleted?.call(ok, message);
      }
    }
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final panel = widget.panel ?? const Color(0xFF0D1320);
    final divider = widget.divider ?? const Color(0xFF22304A);
    final caption = widget.caption ?? const Color(0xFF9AA3B2);

    return InkWell(
      borderRadius: BorderRadius.circular(18),
      onTap: _loading ? null : _callCaregiver,
      splashColor: Colors.white.withValues(alpha: 0.1),
      highlightColor: Colors.white.withValues(alpha: 0.05),
      child: Container(
        height: 110,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: panel,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: divider.withValues(alpha: 0.25)),
        ),
        child: Row(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: divider.withValues(alpha: 0.4)),
              ),
              child: _loading
                  ? const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
                  : const Icon(Icons.sos_outlined, color: Colors.white, size: 28),
            ),
            const SizedBox(width: 16),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '보호자 호출',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  SizedBox(height: 4),
                  Flexible(
                    child: Text(
                      '긴급 상황 시 보호자에게 즉시 알림을 보냅니다',
                      style: TextStyle(
                        color: Color(0xFF9AA3B2),
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            const Icon(Icons.chevron_right_rounded, color: Colors.white),
          ],
        ),
      ),
    );
  }
}
