// lib/map_screen.dart
import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_naver_map/flutter_naver_map.dart';
import 'package:geolocator/geolocator.dart';

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

  @override
  void initState() {
    super.initState();
    _api = DirectionsApi(widget.backendBaseUrl);
  }

  // ---- 유틸 ----
  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<bool> _ensureLocationPermission() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        setState(() => _status = '위치 서비스 꺼짐');
        _toast('위치 서비스가 꺼져 있어요.');
        return false;
      }
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
        setState(() => _status = '위치 권한 거부됨');
        _toast('설정에서 위치 권한을 허용해주세요.');
        return false;
      }
      return true;
    } catch (e) {
      setState(() => _status = '위치 권한 점검 실패');
      _toast('위치 권한 확인 중 오류');
      return false;
    }
  }

  Future<NLatLng?> _getCurrentLatLng() async {
    final ok = await _ensureLocationPermission();
    if (!ok) return null;
    try {
      final pos = await Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high);
      return NLatLng(pos.latitude, pos.longitude);
    } catch (e) {
      _toast('현재 위치를 가져오지 못했어요.');
      return null;
    }
  }

  // ---- 서버 핑 ----
  Future<void> _ping() async {
    setState(() => _status = '서버 확인 중...');
    final ok = await _api.ping();
    if (!mounted) return;
    setState(() => _status = ok ? '서버 연결 OK' : '서버 연결 실패');
    _toast('PING: ${ok ? 'OK' : 'FAIL'} • ${widget.backendBaseUrl}');
  }

  // ---- 현재 위치로 시점 이동 ----
  Future<void> _centerToMyLocation() async {
    final here = await _getCurrentLatLng();
    if (here == null) return;
    final map = _map ?? await _controller.future;

    if (_hereMarker != null) {
      try { map.deleteOverlay(_hereMarker!.info); } catch (_) {}
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
    cu.setAnimation(animation: NCameraAnimation.easing, duration: const Duration(milliseconds: 450));
    await map.updateCamera(cu);

    setState(() => _status = '현재 위치로 이동');
  }

  // ---- 경로 그리기 (maps.py 호환) ----
  Future<void> _drawRoute({
    required String origin,       // "lat,lng" 혹은 주소
    required String destination,  // "lat,lng" 혹은 주소
    String mode = 'walking',
    List<String>? waypoints,
  }) async {
    try {
      setState(() => _status = '경로 요청 중...');
      final resp = await _api.getRoute(
        origin: origin,
        destination: destination,
        mode: mode,
        waypoints: waypoints,
      );

      if (!resp.hasRoute) {
        setState(() => _status = '경로 없음');
        _toast('경로가 없습니다.');
        return;
      }

      // [[lng,lat], ...] -> NLatLng(lat,lng)
      final coords = resp.pathLngLat.map((p) => NLatLng(p[1], p[0])).toList(growable: false);
      final map = _map ?? await _controller.future;

      // 기존 오버레이 제거
      final toDelete = <NOverlayInfo>[];
      if (_routePolyline != null) toDelete.add(_routePolyline!.info);
      if (_startMarker != null) toDelete.add(_startMarker!.info);
      if (_endMarker != null) toDelete.add(_endMarker!.info);
      for (final info in toDelete) {
        try { map.deleteOverlay(info); } catch (_) {}
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
        final cu = NCameraUpdate.fitBounds(bounds, padding: const EdgeInsets.all(40));
        cu.setAnimation(animation: NCameraAnimation.easing, duration: const Duration(milliseconds: 600));
        await map.updateCamera(cu);
      } catch (_) {}

      setState(() => _status = '경로 표시 완료');
      _toast('경로 표시 (${resp.provider}) • ${resp.distanceText} / ${resp.durationText}');
    } catch (e) {
      setState(() => _status = '에러');
      _toast('경로 요청 실패: $e');
    }
  }

  // ---- 버튼 핸들러 ----
  Future<void> _routeFromMyLocation() async {
    final here = await _getCurrentLatLng();
    if (here == null) return;
    final origin = '${here.latitude},${here.longitude}';
    const dest = '37.5796,126.9770'; // 경복궁(데모)
    await _drawRoute(origin: origin, destination: dest, mode: 'walking');
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      title: const Text('Naver Map • 길찾기'),
      actions: [
        IconButton(onPressed: _ping, icon: const Icon(Icons.wifi)),
        IconButton(onPressed: _centerToMyLocation, icon: const Icon(Icons.my_location)),
        IconButton(
          onPressed: _routeFromMyLocation,
          icon: const Icon(Icons.directions_walk),
          tooltip: '내 위치 → 경복궁',
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    // Web 가드 (플러그인 미지원)
    if (kIsWeb) {
      return Scaffold(
        appBar: _buildAppBar(),
        body: const Center(child: Text('네이버 지도는 Flutter Web 미지원입니다. iOS/Android에서 실행하세요.')),
      );
    }

    // NaverMap 초기화 전 가드
    if (!FlutterNaverMap.isInitialized) {
      return Scaffold(
        appBar: _buildAppBar(),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      appBar: _buildAppBar(),
      body: Stack(
        children: [
          NaverMap(
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
              _map = c;
              if (!_controller.isCompleted) _controller.complete(c);
            },
          ),
          Positioned(
            left: 16, right: 16, bottom: 16,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Backend: ${widget.backendBaseUrl}', style: const TextStyle(fontSize: 13)),
                    const SizedBox(height: 6),
                    Text('Status: $_status', style: const TextStyle(fontSize: 13, color: Colors.blueGrey)),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: _centerToMyLocation,
                          icon: const Icon(Icons.my_location),
                          label: const Text('내 위치로 이동'),
                        ),
                        const SizedBox(width: 12),
                        ElevatedButton.icon(
                          onPressed: _routeFromMyLocation,
                          icon: const Icon(Icons.directions_walk),
                          label: const Text('내 위치 → 경복궁'),
                        ),
                        const SizedBox(width: 12),
                        ElevatedButton.icon(
                          onPressed: () => _drawRoute(
                            origin: '37.5665,126.9780',      // 시청
                            destination: '37.5796,126.9770', // 경복궁
                            mode: 'walking',
                          ),
                          icon: const Icon(Icons.alt_route),
                          label: const Text('데모 경로'),
                        ),
                      ],
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
