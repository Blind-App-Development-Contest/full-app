// lib/map_screen.dart
import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';
import 'package:geolocator/geolocator.dart'; // geolocator import 추가
import 'directions_api.dart';

class MapScreen extends StatefulWidget {
  final String backendBaseUrl;
  const MapScreen({super.key, required this.backendBaseUrl});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  late final DirectionsApi _api;
  final Completer<NaverMapController> _controller = Completer();

  NaverMapController? _map;
  NPolylineOverlay? _routePolyline;
  NMarker? _startMarker;
  NMarker? _endMarker;
  NMarker? _hereMarker; // 현재 위치 표시용

  String _status = '대기';
  final _destinationController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _api = DirectionsApi(widget.backendBaseUrl);
  }

  @override
  void dispose() {
    _destinationController.dispose();
    super.dispose();
  }

  // ---- 유틸 ----
  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  // GPS 관련 코드 (네이버 맵 테스트용)
  Future<bool> _ensureLocationPermission() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        setState(() => _status = '위치 서비스 꺼짐');
        _toast('위치 서비스가 꺼져 있어요.');
        return false;
      }
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied) {
        setState(() => _status = '위치 권한 거부됨');
        _toast('설정에서 위치 권한을 허용해주세요.');
        return false;
      }

      if (permission == LocationPermission.deniedForever) {
        setState(() => _status = '위치 권한 영구 거부됨');
        _toast('설정에서 위치 권한을 허용해주세요.');
        return false;
      }

      return true;
    } catch (e) {
      debugPrint('Permission check failed: $e');
      setState(() => _status = '위치 권한 점검 실패');
      _toast('위치 권한 확인 중 오류');
      return false;
    }
  }

  // 실제 GPS 위치 반환
  Future<NLatLng?> _getCurrentLatLng() async {
    try {
      final hasPermission = await _ensureLocationPermission();
      if (!hasPermission) return null;

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 1,
        ),
      );

      return NLatLng(position.latitude, position.longitude);
    } catch (e) {
      debugPrint('Failed to get current location: $e');
      _toast('현재 위치를 가져올 수 없습니다.');
      return null;
    }
  }

  // ---- 서버 진단 ----
  Future<void> _ping() async {
    setState(() => _status = '서버 진단 중...');

    try {
      final diagnostic = await _api.pingDiagnostic();
      final isConnected = diagnostic['isConnected'] as bool;
      final tests = diagnostic['tests'] as List<Map<String, dynamic>>;

      if (!mounted) return;

      setState(() => _status = isConnected ? '서버 연결 OK' : '서버 연결 실패');

      // 진단 결과 표시
      if (isConnected) {
        final successfulTest = tests.firstWhere(
          (test) => test['success'] == true,
        );
        _toast(
          '서버 연결 성공\n엔드포인트: ${successfulTest['endpoint']}\n응답시간: ${successfulTest['responseTime']}',
        );
      } else {
        // 실패한 경우 상세 정보 표시
        String errorMsg = '서버 연결 실패\n서버 주소: ${widget.backendBaseUrl}\n\n';

        for (final test in tests) {
          if (test['diagnosis'] != null) {
            errorMsg += '진단: ${test['diagnosis']}\n';
            break;
          }
          if (test['error'] != null) {
            final error = test['error'] as String;
            if (error.contains('Connection refused')) {
              errorMsg += '진단: 서버가 다운되었거나 방화벽이 차단 중\n';
            } else if (error.contains('TimeoutException')) {
              errorMsg += '진단: 서버 응답 시간 초과\n';
            } else if (error.contains('SocketException')) {
              errorMsg += '진단: 네트워크 연결 문제\n';
            }
            break;
          }
        }

        errorMsg += '\n해결 방법:\n1. 서버 상태 확인\n2. IP 주소 및 포트 확인\n3. 네트워크 연결 확인';
        _toast(errorMsg);
      }
    } catch (e) {
      debugPrint('Ping diagnostic error: $e');
      if (!mounted) return;
      setState(() => _status = '진단 실패');
      _toast('서버 진단 중 오류 발생: $e');
    }
  }

  // ---- 현재 위치로 시점 이동 ----
  Future<void> _centerToMyLocation() async {
    final here = await _getCurrentLatLng();
    if (here == null) return;
    final map = _map ?? await _controller.future;

    if (_hereMarker != null) {
      try {
        map.deleteOverlay(_hereMarker!.info);
      } catch (_) {}
      _hereMarker = null;
    }
    _hereMarker = NMarker(
      id: 'here_marker',
      position: here,
      caption: const NOverlayCaption(text: '현재 위치'),
      captionAligns: const [NAlign.top],
      iconTintColor: Colors.blueAccent,
    );
    map.addOverlay(_hereMarker!);

    final cu = NCameraUpdate.scrollAndZoomTo(target: here, zoom: 16);
    cu.setAnimation(
      animation: NCameraAnimation.easing,
      duration: const Duration(milliseconds: 450),
    );
    await map.updateCamera(cu);

    setState(() => _status = '현재 위치로 이동');
  }

  // ---- 경로 그리기 (도보 전용) ----
  Future<void> _drawRoute({
    required String origin, // "lat,lng" 혹은 주소
    required String destination, // "lat,lng" 혹은 주소
    List<String>? waypoints,
  }) async {
    try {
      setState(() => _status = '도보 경로 요청 중...');
      final resp = await _api.getRoute(
        origin: origin,
        destination: destination,
        waypoints: waypoints,
      );

      if (!resp.hasRoute) {
        setState(() => _status = '경로 없음');
        _toast('경로가 없습니다.');
        return;
      }

      // [[lng,lat], ...] -> NLatLng(lat,lng)
      final coords = resp.pathLngLat
          .map((p) => NLatLng(p[1], p[0]))
          .toList(growable: false);
      final map = _map ?? await _controller.future;

      // 기존 오버레이 제거
      final toDelete = <NOverlayInfo>[];
      if (_routePolyline != null) toDelete.add(_routePolyline!.info);
      if (_startMarker != null) toDelete.add(_startMarker!.info);
      if (_endMarker != null) toDelete.add(_endMarker!.info);
      for (final info in toDelete) {
        try {
          map.deleteOverlay(info);
        } catch (_) {}
      }
      _routePolyline = null;
      _startMarker = null;
      _endMarker = null;

      // 시작/도착 마커
      _startMarker = NMarker(
        id: 'start_marker',
        position: coords.first,
        caption: const NOverlayCaption(text: '출발'),
        captionAligns: const [NAlign.top],
        iconTintColor: Colors.green,
      );
      _endMarker = NMarker(
        id: 'end_marker',
        position: coords.last,
        caption: const NOverlayCaption(text: '도착'),
        captionAligns: const [NAlign.top],
        iconTintColor: Colors.red,
      );
      map.addOverlay(_startMarker!);
      map.addOverlay(_endMarker!);

      // 경로 폴리라인
      _routePolyline = NPolylineOverlay(
        id: 'route_polyline',
        coords: coords,
        width: 8.0,
        color: Colors.blue,
      );
      map.addOverlay(_routePolyline!);

      // 화면에 경로 전체가 보이도록 시점 맞춤
      try {
        final bounds = NLatLngBounds.from(coords);
        final cu = NCameraUpdate.fitBounds(
          bounds,
          padding: const EdgeInsets.all(40),
        );
        cu.setAnimation(
          animation: NCameraAnimation.easing,
          duration: const Duration(milliseconds: 600),
        );
        await map.updateCamera(cu);
      } catch (_) {}

      setState(() => _status = '경로 표시 완료');
      _toast(
        '경로 표시 (${resp.provider}) • ${resp.distanceText} / ${resp.durationText}',
      );
    } catch (e) {
      setState(() => _status = '에러');
      _toast('경로 요청 실패: $e');
    }
  }

  // ---- 버튼 핸들러 ----
  Future<void> _routeFromMyLocation() async {
    final destination = _destinationController.text.trim();
    if (destination.isEmpty) {
      _toast('목적지를 입력해주세요.');
      return;
    }

    try {
      setState(() => _status = 'GPS 위치 확인 중...');

      final here = await _getCurrentLatLng();
      if (here == null) {
        _toast('현재 위치를 확인할 수 없습니다.');
        setState(() => _status = '위치 확인 실패');
        return;
      }

      // 출발지 현재 GPS 위치로 고정
      final origin = '${here.latitude},${here.longitude}';

      debugPrint('GPS Location (Origin): $origin');
      debugPrint('Destination: $destination');

      setState(() => _status = '도보 경로 계산 중... (최대 45초)');
      _toast('도보 경로를 계산하고 있습니다. 잠시만 기다려주세요.');

      await _drawRoute(origin: origin, destination: destination);
    } catch (e) {
      debugPrint('Route from my location error: $e');
      setState(() => _status = '경로 계산 실패');
      _toast('경로 계산 중 오류가 발생했습니다: ${e.toString()}');
    }
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      title: const Text('Naver Map • 길찾기'),
      actions: [
        IconButton(onPressed: _ping, icon: const Icon(Icons.wifi)),
        IconButton(
          onPressed: _centerToMyLocation,
          icon: const Icon(Icons.my_location), // 아이콘 변경
        ),
        IconButton(
          onPressed: _routeFromMyLocation,
          icon: const Icon(Icons.directions_walk),
          tooltip: '입력한 목적지로 길찾기', // 툴팁 변경
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    debugPrint('📱 MapScreen build - Status: $_status');

    // Web 가드 (플러그인 미지원)
    if (kIsWeb) {
      return Scaffold(
        appBar: _buildAppBar(),
        body: const Center(
          child: Text('네이버 지도는 Flutter Web 미지원입니다. iOS/Android에서 실행하세요.'),
        ),
      );
    }

    return Scaffold(
      appBar: _buildAppBar(),
      body: Stack(
        children: [
          NaverMap(
            // Expanded 제거
            options: const NaverMapViewOptions(
              initialCameraPosition: NCameraPosition(
                target: NLatLng(37.5665, 126.9780), // 서울시청
                zoom: 14,
              ),
              indoorEnable: false,
              logoClickEnable: false,
              locationButtonEnable: false, // 기본 버튼은 비활성화 (우리가 직접 제어)
            ),
            onMapReady: (c) async {
              debugPrint('🗺️ onMapReady called');
              _map = c;
              if (!_controller.isCompleted) _controller.complete(c);

              setState(() => _status = '맵 로드 완료');
              debugPrint(' NaverMap widget ready');
            },
          ),
          Positioned(
            left: 16,
            right: 16,
            bottom: 16,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Backend: ${widget.backendBaseUrl}',
                      style: const TextStyle(fontSize: 13),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Status: $_status',
                      style: const TextStyle(
                        fontSize: 13,
                        color: Colors.blueGrey,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: _centerToMyLocation,
                          icon: const Icon(Icons.my_location),
                          label: const Text('GPS 위치로 이동'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _destinationController,
                      decoration: const InputDecoration(
                        hintText: '목적지를 입력하세요 (예: 경복궁, 명동역)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.place),
                        contentPadding: EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 8,
                        ),
                      ),
                      onSubmitted: (_) => _routeFromMyLocation(),
                    ),
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: _routeFromMyLocation,
                        icon: const Icon(Icons.directions_walk),
                        label: const Text('도보 경로 찾기'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
