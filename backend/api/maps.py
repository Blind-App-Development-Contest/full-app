# api/maps.py
# NAVER + MAPBOX 혼합판 (개선: 네이버 키 지연 요구, Mapbox 경유지 23개 제한)
# - driving: NAVER (v15 우선, 404/미개통 시 legacy로 폴백, 응답 파싱 보강)
# - walking: MAPBOX Directions API, 네이버 지도 위에 그릴 좌표 [[lng,lat], ...] 반환
# - 공통: 좌표/지오코딩 유틸 및 path 정규화 유틸

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Any
import httpx
import os
import re

# 중앙화된 데이터베이스 연결 사용 (로그 저장용)
from core.database import get_async_db
from models.database_models import DashboardLog
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from config.settings import get_settings, Settings

router = APIRouter(prefix="/maps", tags=["maps"])

# ===== Schemas =====
class DirectionsReq(BaseModel):
    origin: str = Field(..., description='"lat,lng" | address')
    destination: str = Field(..., description='"lat,lng" | address')
    mode: str = Field("walking", description="driving|walking")
    waypoints: Optional[List[str]] = None  # MAPBOX: up to 25 total points (origin + ≤23 wpts + destination)

# ===== Helpers (NAVER) =====
def _require_naver_keys(settings: Settings | None = None) -> Tuple[str, str]:
    cid = None
    csec = None
    if settings:
        cid = getattr(settings, "NAVER_CLIENT_ID", None) or getattr(settings, "naver_client_id", None)
        csec = getattr(settings, "NAVER_CLIENT_SECRET", None) or getattr(settings, "naver_client_secret", None)
    cid = cid or os.getenv("NAVER_CLIENT_ID")
    csec = csec or os.getenv("NAVER_CLIENT_SECRET")
    if not cid or not csec:
        raise HTTPException(500, "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET not configured")
    return cid, csec

async def _ncloud_get(url: str, params: dict, cid: str, csec: str, *, strict: bool = True) -> dict:
    """
    strict=True  : non-200 -> HTTPException(502)
    strict=False : non-200 -> wrap response in dict for upper fallback opportunity
    """
    headers = {
        "X-NCP-APIGW-API-KEY-ID": cid,
        "X-NCP-APIGW-API-KEY": csec,
        "Referer": "http://20.22.176.12" # 서버 주소 명시 
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            r = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as e:
        print(f"[NCloud GET] Request error: {e!s}")
        if not strict:
            return {"_status": 503, "error": f"Request error: {e!s}"}
        raise HTTPException(502, f"Naver upstream request error: {e!s}")

    print(f"[NCloud GET] {url} params={params} -> {r.status_code} content_length={len(r.content)}")

    if r.status_code == 200:
        try:
            return r.json()
        except Exception as e:
            print(f"[NCloud GET] JSON parse error: {e!s}, content: {r.text[:200]}")
            if not strict:
                return {"_status": 200, "error": f"Non-JSON response", "raw": r.text[:500]}
            raise HTTPException(502, "Naver upstream returned non-JSON response")

    if strict:
        raise HTTPException(502, f"Naver upstream error {r.status_code}: {r.text[:300]}")
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    body["_status"] = str(r.status_code)
    return body

def _parse_latlng(s: str) -> Optional[Tuple[float, float]]:
    """Try parse 'lat,lng'. Returns (lat,lng) or None."""
    if not s:
        return None
    s = s.strip()
    if "," not in s:
        return None
    a, b = [x.strip() for x in s.split(",", 1)]
    try:
        lat, lng = float(a), float(b)
    except Exception:
        return None
    # swap if reversed (lng,lat)
    if abs(lat) > 90 and abs(lng) <= 90:
        lat, lng = lng, lat
    if abs(lat) > 90 or abs(lng) > 180:
        raise HTTPException(400, "Invalid lat/lng")
    return (lat, lng)

async def _geocode_nominatim(
    query: str,
    bias: Optional[Tuple[float, float]] = (37.5665, 126.9780),  # default: 서울시청
) -> Tuple[float, float]:
    """
    OpenStreetMap Nominatim Geocoding API fallback (free, no key required)
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        raise HTTPException(400, "Empty query for geocoding")
    
    params = {
        "q": q,
        "format": "json", 
        "limit": 1,
        "countrycodes": "kr",  # 한국으로 제한
        "addressdetails": 1,
    }
    if bias:
        lat, lng = bias
        params["viewbox"] = f"{lng-1},{lat+1},{lng+1},{lat-1}"  # bias 주변 1도 범위
        params["bounded"] = 1
    
    headers = {
        "User-Agent": "BlindApp/1.0 (walking directions app)"  # Nominatim 요구사항
    }
    
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get("https://nominatim.openstreetmap.org/search", 
                                params=params, headers=headers)
        
        print(f"[Nominatim Geocoding] query={q} -> {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                result = data[0]
                lat = float(result["lat"])
                lng = float(result["lon"])
                print(f"[Nominatim Geocoding] Found: {lat},{lng} for '{q}' ({result.get('display_name', 'N/A')})")
                return (lat, lng)
            else:
                print(f"[Nominatim Geocoding] No results for '{q}'")
        else:
            print(f"[Nominatim Geocoding] HTTP error: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[Nominatim Geocoding] Request error: {e}")
    
    raise HTTPException(404, f"Nominatim geocoding failed for: {q}")

async def _geocode_naver(
    query: str,
    cid: str,
    csec: str,
    bias: Optional[Tuple[float, float]] = (37.5665, 126.9780),  # default: 서울시청
) -> Tuple[float, float]:
    """
    NAVER Geocoding + Place 혼합판 (with Google fallback)
    - 주소 형태(도로명, 번지 등)는 Geocode API 사용
    - 지명(역, 타워, 공원 등)은 Place API 사용 (bias 좌표 반경 50km)
    - Naver 실패 시 Google Geocoding으로 폴백
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        raise HTTPException(400, "Empty query for geocoding")

    # 주소 형태인지 판별 (도로명/번지 등 키워드 포함 시)
    if any(x in q for x in ["로", "길", "번지", "동", "읍", "면", "리", "아파트"]):
        geocode_params = {"query": q}
        if bias:
            lat, lng = bias
            geocode_params["coordinate"] = f"{lng},{lat}"

        data = await _ncloud_get(
            "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode",
            geocode_params, cid, csec, strict=False
        )
        if isinstance(data, dict) and "_status" not in data:
            addrs = data.get("addresses") or []
            if addrs:
                lng = float(addrs[0]["x"])
                lat = float(addrs[0]["y"])
                return (lat, lng)

    # 지명 검색 (Place API + bias 적용)
    place_params = {
        "query": q,
        "display": 1,
    }
    if bias:
        lat, lng = bias
        # Place API에서는 coordinate + radius 조합이 효과적
        place_params["coordinate"] = f"{lng},{lat}"
        place_params["radius"] = 50000  # 50km

    pdata = await _ncloud_get(
        "https://naveropenapi.apigw.ntruss.com/map-place/v1/search",
        place_params, cid, csec, strict=False
    )
    if isinstance(pdata, dict) and "_status" not in pdata:
        places = pdata.get("places") or pdata.get("place") or []
        if places:
            lng = float(places[0].get("x"))
            lat = float(places[0].get("y"))
            return (lat, lng)

    # Naver 실패 시 Nominatim Geocoding 폴백
    print(f"[Geocoding] Naver failed, trying Nominatim fallback for: {q}")
    try:
        return await _geocode_nominatim(q, bias=bias)
    except Exception as e:
        print(f"[Geocoding] Nominatim fallback also failed: {e}")

    # 모든 방법 실패 시 예외
    raise HTTPException(404, f"Geocoding failed for: {q} (naver=failed, nominatim=failed)")

async def _to_latlng(
    s: str,
    cid: str,
    csec: str,
    bias: Optional[Tuple[float, float]] = None
) -> Tuple[float, float]:
    ll = _parse_latlng(s)
    if ll:
        return ll
    return await _geocode_naver(s, cid, csec, bias=bias)

def _fmt_meters(m: float) -> str:
    m = float(m)
    return f"{m/1000:.1f} km" if m >= 1000 else f"{int(m)} m"

def _fmt_seconds(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m} mins"

# ----- path 정규화 유틸 (NAVER 응답용) -----
def _normalize_path(raw) -> list:
    """
    Normalize various path formats to [[lng,lat], ...]
      - [[lng,lat], ...]
      - {"list":[[lng,lat], ...]}
      - [{"x":lng,"y":lat}], [{"lng":lng,"lat":lat}], [{"longitude":lng,"latitude":lat}]
    """
    out = []
    if not raw:
        return out
    if isinstance(raw, dict) and "list" in raw:
        return _normalize_path(raw.get("list"))
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        for p in raw:
            if isinstance(p, list) and len(p) == 2:
                try:
                    out.append([float(p[0]), float(p[1])])
                except Exception:
                    continue
        return out
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for p in raw:
            for kx, ky in (("x","y"), ("lng","lat"), ("longitude","latitude")):
                if kx in p and ky in p:
                    try:
                        out.append([float(p[kx]), float(p[ky])])
                        break
                    except Exception:
                        pass
        return out
    return out

def _merge_sections_links(best: dict) -> list:
    merged = []
    for sec in best.get("section", []) or []:
        for link in sec.get("links", []) or []:
            pr = link.get("path")
            if pr:
                norm = _normalize_path(pr)
                if norm:
                    merged.extend(norm)
    return merged

# ----- NAVER 응답 파서 -----
def _extract_best_path(data: dict, mode: str) -> tuple[list, dict, dict]:
    route_root = (data or {}).get("route") or {}
    buckets = None
    if mode == "driving":
        for key in ("trafast", "traoptimal", "tracomfort", "traavoidtoll", "traavoidcaronly"):
            if key in route_root:
                buckets = route_root.get(key); break
    else:
        for key in ("route", "list", "trawalking"):
            if key in route_root:
                buckets = route_root.get(key); break
    if not buckets and isinstance(route_root, dict) and route_root:
        buckets = next(iter(route_root.values()), None)

    cand_list = []
    if buckets:
        cand_list = buckets if isinstance(buckets, list) else [buckets]

    for best in cand_list:
        summary = best.get("summary") or {}
        path = _normalize_path(best.get("path"))
        if path: return path, summary, best
        merged = _merge_sections_links(best)
        if merged: return merged, summary, best

    # global scan (depth ≤3)
    def _scan(obj: Any, depth=0):
        if depth > 3 or obj is None: return None
        if isinstance(obj, list):
            for it in obj:
                r = _scan(it, depth+1); 
                if r: return r
        elif isinstance(obj, dict):
            pth = _normalize_path(obj.get("path"))
            if pth: return pth, (obj.get("summary") or {}), obj
            merged = _merge_sections_links(obj)
            if merged: return merged, (obj.get("summary") or {}), obj
            for v in obj.values():
                r = _scan(v, depth+1); 
                if r: return r
        return None
    scanned = _scan(route_root, 0)
    if scanned: return scanned
    return [], {}, {}

def _ok_or_raise_from_data(data: dict):
    if isinstance(data, dict) and data.get("_status"):
        raise HTTPException(502, f"Naver directions bad status: {data.get('_status')}")
    code = data.get("code", 0)
    if "error" in data:
        raise HTTPException(502, f"Naver directions error: {data['error']}")
    if isinstance(code, int) and code not in (0,):
        raise HTTPException(502, f"Naver directions error code={code}")
    if isinstance(code, str) and code not in ("0", ""):
        raise HTTPException(502, f"Naver directions error code={code}")

# ===== Mapbox (WALKING) =====
def _require_mapbox_token(settings: Settings | None = None) -> str:
    tok = None
    if settings:
        tok = getattr(settings, "MAPBOX_ACCESS_TOKEN", None) or getattr(settings, "mapbox_access_token", None)
    tok = tok or os.getenv("MAPBOX_ACCESS_TOKEN")
    if not tok:
        raise HTTPException(500, "MAPBOX_ACCESS_TOKEN not configured")
    return tok

async def _mapbox_directions_walking(
    o_lat: float, o_lng: float, d_lat: float, d_lng: float,
    waypoints: Optional[List[Tuple[float, float]]] = None,
    *, lang: str = "ko", steps: bool = True, settings: Settings | None = None
) -> dict:
    """
    Mapbox Directions (walking) → unified format
    returns: {"routes":[{summary,distance_text,duration_text,polyline=None,path_lnglat,steps}], "provider":"mapbox"}
    """
    token = _require_mapbox_token(settings)
    coords = [[o_lng, o_lat]]
    if waypoints:
        for lat, lng in waypoints:
            coords.append([float(lng), float(lat)])
    coords.append([d_lng, d_lat])

    coord_str = ";".join(f"{lng},{lat}" for lng, lat in coords)  # "lng,lat;lng,lat;..."
    url = f"https://api.mapbox.com/directions/v5/mapbox/walking/{coord_str}"
    params = {
        "alternatives": "false",
        "geometries": "geojson",
        "steps": "true" if steps else "false",
        "overview": "full",
        "language": lang,
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        r = await client.get(url, params=params)
    print(f"[Mapbox GET] {url} -> {r.status_code}")
    if r.status_code != 200:
        raise HTTPException(502, f"Mapbox upstream error {r.status_code}: {r.text[:300]}")
    data = r.json()

    routes = data.get("routes") or []
    if not routes:
        return {"routes": [], "provider": "mapbox"}

    best = routes[0]
    distance = float(best.get("distance", 0.0))
    duration = float(best.get("duration", 0.0))

    # geometry: {type:"LineString", coordinates:[[lng,lat],...]}
    geom = best.get("geometry") or {}
    coords_ll = geom.get("coordinates") or []
    path_lnglat = []
    for p in coords_ll:
        if isinstance(p, list) and len(p) == 2:
            try:
                path_lnglat.append([float(p[0]), float(p[1])])
            except Exception:
                continue

    steps_out = []
    for leg in best.get("legs") or []:
        for st in leg.get("steps", []):
            instr = (st.get("maneuver") or {}).get("instruction") or (st.get("name") or "")
            s_dist = float(st.get("distance", 0.0))
            s_dur  = float(st.get("duration", 0.0))
            steps_out.append({
                "instruction_html": instr,
                "distance_text": _fmt_meters(s_dist),
                "duration_text": _fmt_seconds(s_dur),
                "start_loc": {},
                "end_loc": {},
                "maneuver": (st.get("maneuver") or {}).get("type") or ""
            })

    route_out = {
        "summary": "walking route",
        "distance_text": _fmt_meters(distance),
        "duration_text": _fmt_seconds(duration),
        "polyline": None,
        "path_lnglat": path_lnglat,   # [[lng,lat], ...] → front converts to LatLng(p[1], p[0])
        "steps": steps_out
    }
    return {"routes": [route_out], "provider": "mapbox"}

# ===== Endpoints =====
@router.get("/directions")
async def directions_info():
    """GET endpoint for testing - shows API info"""
    return {
        "message": "NAVER + Mapbox Directions API", 
        "methods": ["POST"],
        "example": {
            "origin": "37.5665,126.9780",
            "destination": "37.5651,126.9895", 
            "mode": "driving"
        }
    }

@router.get("/places/autocomplete")
async def places_autocomplete(
    query: str = "",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    settings: Settings = Depends(get_settings)
):
    """Places autocomplete using NAVER Search API"""
    if not query or len(query.strip()) < 2:
        return {"predictions": []}
    
    try:
        print(f"[Places autocomplete] 검색 시작: query='{query}'")
        cid, csec = _require_naver_keys(settings)
        q = query.strip()
        
        # 사용자 위치 또는 기본 위치 (서울시청) 설정
        if lat is not None and lng is not None:
            coordinate = f"{lng},{lat}"  # NAVER API는 lng,lat 순서
            print(f"[Places autocomplete] 사용자 실제 위치 사용: {lat},{lng}")
        else:
            coordinate = "126.9780,37.5665"  # 서울시청 기본값
            print(f"[Places autocomplete] 기본 위치 사용: 서울시청")
        
        # NAVER Place API 호출 (시각장애인 도보 길안내용 - 5km 반경 제한)
        place_params = {
            "query": q,
            "display": 5,
            "coordinate": coordinate,
            "radius": 5000  # 5km 반경 (도보 접근 가능한 합리적 범위)
        }
        
        print(f"[Places autocomplete] NAVER Place API 호출: {place_params}")
        
        pdata = await _ncloud_get(
            "https://maps.apigw.ntruss.com/map-place/v1/search",
            place_params, cid, csec, strict=False
        )
        
        print(f"[Places autocomplete] Place API 응답: {type(pdata)}, _status={pdata.get('_status') if isinstance(pdata, dict) else 'N/A'}")
        
        predictions = []
        if isinstance(pdata, dict):
            if "_status" in pdata:
                print(f"[Places autocomplete] API 에러 상태: {pdata.get('_status')}, {pdata.get('error', '')}")
                # 에러가 있어도 fallback으로 geocoding 시도
                try:
                    print(f"[Places autocomplete] Geocoding fallback 시도: {q}")
                    bias_coords = (lat, lng) if (lat is not None and lng is not None) else (37.5665, 126.9780)
                    lat_result, lng_result = await _geocode_nominatim(q, bias=bias_coords)
                    predictions = [{
                        "place_id": q,
                        "description": q,
                        "structured_formatting": {
                            "main_text": q,
                            "secondary_text": f"위도: {lat_result:.4f}, 경도: {lng_result:.4f}"
                        },
                        "geometry": {
                            "location": {"lat": lat_result, "lng": lng_result}
                        }
                    }]
                    print(f"[Places autocomplete] Geocoding 성공: {lat_result}, {lng_result}")
                except Exception as e:
                    print(f"[Places autocomplete] Geocoding도 실패: {e}")
                    predictions = []
            else:
                # 정상 응답 처리
                places = pdata.get("places") or pdata.get("place") or []
                print(f"[Places autocomplete] 받은 장소 수: {len(places)}")
                
                for place in places[:5]:  # 최대 5개 결과
                    name = place.get("name", "")
                    road_addr = place.get("roadAddress", "")
                    addr = place.get("address", "")
                    address = road_addr or addr
                    
                    predictions.append({
                        "place_id": place.get("id", ""),
                        "description": name,
                        "structured_formatting": {
                            "main_text": name,
                            "secondary_text": address
                        },
                        "geometry": {
                            "location": {
                                "lat": float(place.get("y", 0)),
                                "lng": float(place.get("x", 0))
                            }
                        }
                    })
        
        if len(predictions) > 0:
            print(f"[Places autocomplete] 첫 번째 장소: {predictions[0]['description']}")
        else:
            print(f"[Places autocomplete] 장소를 찾지 못함")
        
        print(f"[Places autocomplete] 최종 반환: {len(predictions)}개 장소")
        return {"predictions": predictions}
    except Exception as e:
        print(f"[Places autocomplete] 에러: {e}")
        return {"predictions": []}

@router.get("/places/detail")
async def places_detail(
    place_id: str = "",
    query: str = "",
    settings: Settings = Depends(get_settings)
):
    """Get place details using NAVER Place API"""
    if not place_id and not query:
        return {"result": None, "status": "INVALID_REQUEST"}
    
    try:
        cid, csec = _require_naver_keys(settings)
        search_query = query if query else place_id
        
        # NAVER Place API 호출
        place_params = {"query": search_query, "display": 1}
        pdata = await _ncloud_get(
            "https://maps.apigw.ntruss.com/map-place/v1/search",
            place_params, cid, csec, strict=False
        )
        
        if isinstance(pdata, dict) and "_status" not in pdata:
            places = pdata.get("places") or []
            if places:
                place = places[0]
                result = {
                    "place_id": place.get("id", ""),
                    "name": place.get("name", ""),
                    "formatted_address": place.get("roadAddress", "") or place.get("address", ""),
                    "geometry": {
                        "location": {
                            "lat": float(place.get("y", 0)),
                            "lng": float(place.get("x", 0))
                        }
                    },
                    "rating": place.get("rating", 0),
                    "user_ratings_total": place.get("reviewCount", 0),
                    "formatted_phone_number": place.get("phoneNumber", ""),
                    "website": place.get("homePage", ""),
                    "opening_hours": {
                        "open_now": True,  # NAVER API에서 제공하지 않으므로 기본값
                        "weekday_text": []
                    }
                }
                return {"result": result, "status": "OK"}
        
        return {"result": None, "status": "NOT_FOUND"}
    except Exception as e:
        print(f"[Places detail] Error: {e}")
        return {"result": None, "status": "UNKNOWN_ERROR"}

async def _log_directions_request(user_id: str, req: DirectionsReq, result: dict, session: AsyncSession):
    """길찾기 요청 로그를 데이터베이스에 저장"""
    try:
        log_data = {
            "request": {
                "origin": req.origin,
                "destination": req.destination,
                "mode": req.mode,
                "waypoints_count": len(req.waypoints or [])
            },
            "response": {
                "provider": result.get("provider", "unknown"),
                "routes_count": len(result.get("routes", []))
            }
        }
        
        dashboard_log = DashboardLog(
            user_id=user_id,
            log_type="directions_request",
            log_data=str(log_data)
        )
        
        session.add(dashboard_log)
        await session.commit()
    except Exception as e:
        print(f"[길찾기 로그 저장 실패] {e}")

@router.post("/directions")
async def directions(
    req: DirectionsReq, 
    settings: Settings = Depends(get_settings),
    user_id: Optional[str] = None,  # 선택적 사용자 ID 파라미터
    session: AsyncSession = Depends(get_async_db)
):
    mode = (req.mode or "walking").lower()
    if mode not in ("driving", "walking"):
        mode = "walking"

    # --- Lazy key requirement & parsing ---
    o_ll = _parse_latlng(req.origin)
    d_ll = _parse_latlng(req.destination)

    # parse waypoints first (limit 23 for Mapbox)
    raw_wps = (req.waypoints or [])[:23]
    wps_parsed: List[Tuple[float, float]] = []
    wps_unresolved: List[str] = []
    for w in raw_wps:
        ll = _parse_latlng(w)
        if ll:
            wps_parsed.append(ll)
        else:
            wps_unresolved.append(w)

    need_naver = (o_ll is None) or (d_ll is None) or (len(wps_unresolved) > 0)
    cid: Optional[str] = None
    csec: Optional[str] = None
    if need_naver:
        cid, csec = _require_naver_keys(settings)

    # resolve origin/destination
    if o_ll is None:
        if cid is None or csec is None:
            raise HTTPException(500, "NAVER keys required for geocoding origin")
        o_lat, o_lng = await _to_latlng(req.origin, cid, csec)
    else:
        o_lat, o_lng = o_ll

    if d_ll is None:
        if cid is None or csec is None:
            raise HTTPException(500, "NAVER keys required for geocoding destination")
        d_lat, d_lng = await _to_latlng(req.destination, cid, csec, bias=(o_lat, o_lng))
    else:
        d_lat, d_lng = d_ll

    # resolve unresolved waypoints (if any)
    if wps_unresolved:
        if not cid:
            # cannot geocode unresolved waypoint without Naver keys
            raise HTTPException(400, "Waypoints include addresses; NAVER keys required for geocoding")
        remain = 23 - len(wps_parsed)
        for w in wps_unresolved[:remain]:
            if cid is None or csec is None:
                raise HTTPException(500, "NAVER keys required for waypoint geocoding")
            lat, lng = await _to_latlng(w, cid, csec, bias=(o_lat, o_lng))
            wps_parsed.append((lat, lng))

    # -------- walking → MAPBOX --------
    if mode == "walking":
        result = await _mapbox_directions_walking(
            o_lat, o_lng, d_lat, d_lng, waypoints=wps_parsed, lang="ko", steps=True, settings=settings
        )
        # 로그 저장 (사용자 ID가 있는 경우)
        if user_id:
            await _log_directions_request(user_id, req, result, session)
        return result

    # -------- driving → NAVER --------
    if not cid or not csec:
        cid, csec = _require_naver_keys(settings)
    
    # Type narrowing assertion
    assert cid is not None and csec is not None

    base_params = {
        "start": f"{o_lng},{o_lat}",
        "goal": f"{d_lng},{d_lat}",
        "coordType": "latlng",
    }
    if wps_parsed:
        base_params["waypoints"] = "|".join(f"{lng},{lat}" for (lat, lng) in wps_parsed)

    # try #1: v15
    url = "https://maps.apigw.ntruss.com/map-direction-15/v1/driving"
    params1 = {**base_params, "option": "trafast"}
    print("[NAVER DIRECTIONS][try#1]", url, params1)
    data = await _ncloud_get(url, params1, cid, csec, strict=False)

    # fallback: legacy (확장된 실패 조건)
    should_fallback = False
    if isinstance(data, dict):
        status = data.get("_status")
        error = data.get("error", "")
        # 404, 503 (타임아웃), JSON 파싱 에러 시 legacy로 폴백
        if (status in (404, 503) or 
            "Not Found" in str(error) or 
            "URL not found" in str(error) or
            "Request error" in str(error) or
            "Non-JSON response" in str(error)):
            should_fallback = True
    
    if should_fallback:
        url_legacy = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
        params_legacy = {**base_params, "option": "trafast"}
        print("[NAVER DIRECTIONS] fallback legacy:", url_legacy, params_legacy)
        data = await _ncloud_get(url_legacy, params_legacy, cid, csec, strict=False)

    # parse
    try:
        _ok_or_raise_from_data(data)
        path, summary, best = _extract_best_path(data, "driving")
    except HTTPException:
        path, summary, best = [], {}, {}

    # retry with swapped lat/lng (just in case)
    if not path:
        url2 = "https://maps.apigw.ntruss.com/map-direction-15/v1/driving"
        params2 = {**params1, "start": f"{o_lat},{o_lng}", "goal": f"{d_lat},{d_lng}"}
        print("[NAVER DIRECTIONS][try#2 swap lat<->lng]", url2, params2)
        data2 = await _ncloud_get(url2, params2, cid, csec, strict=False)
        try:
            _ok_or_raise_from_data(data2)
            path, summary, best = _extract_best_path(data2, "driving")
        except HTTPException:
            pass

    # retry with labels
    if not path:
        url3 = "https://maps.apigw.ntruss.com/map-direction-15/v1/driving"
        params3 = {**params1, "start": f"{o_lng},{o_lat},origin", "goal": f"{d_lng},{d_lat},dest"}
        print("[NAVER DIRECTIONS][try#3 add labels]", url3, params3)
        data3 = await _ncloud_get(url3, params3, cid, csec, strict=False)
        try:
            _ok_or_raise_from_data(data3)
            path, summary, best = _extract_best_path(data3, "driving")
        except HTTPException:
            pass

    if not path:
        try:
            top = (locals().get("data3") or locals().get("data2") or data) or {}
            top_keys = list(top.keys()) if isinstance(top, dict) else []
            rr = top.get("route") if isinstance(top, dict) else None
            route_keys = list(rr.keys()) if isinstance(rr, dict) else []
            print("[NAVER DIRECTIONS][empty] top_keys=", top_keys, " route_keys=", route_keys)
            print("[NAVER DIRECTIONS][empty] last_status=", top.get("_status", None))
        except Exception:
            pass
        return {"routes": [], "provider": "naver"}

    distance = int((summary or {}).get("distance", 0) or 0)
    duration = int((summary or {}).get("duration", 0) or 0)

    steps = []
    for sec in (best or {}).get("section", []) or []:
        try:
            s_dist = int(sec.get("distance", 0) or 0)
            s_dur  = int(sec.get("duration", 0) or 0)
        except Exception:
            s_dist, s_dur = 0, 0
        steps.append({
            "instruction_html": sec.get("name", "") or "",
            "distance_text": _fmt_meters(s_dist),
            "duration_text": _fmt_seconds(s_dur),
            "start_loc": {},
            "end_loc": {},
            "maneuver": ""
        })

    route_out = {
        "summary": f"{(summary or {}).get('start','')} → {(summary or {}).get('goal','')}".strip(" → "),
        "distance_text": _fmt_meters(distance),
        "duration_text": _fmt_seconds(duration),
        "polyline": None,            # Naver: path array
        "path_lnglat": path,         # [[lng,lat], ...] → front flips to (lat,lng)
        "steps": steps
    }
    result = {"routes": [route_out], "provider": "naver"}
    
    # 로그 저장 (사용자 ID가 있는 경우)
    if user_id:
        await _log_directions_request(user_id, req, result, session)
    
    return result
