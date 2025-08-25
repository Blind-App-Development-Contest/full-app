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
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(502, f"Naver upstream request error: {e!s}")

    print(f"[NCloud GET] {url} params={params} -> {r.status_code}")

    if r.status_code == 200:
        try:
            return r.json()
        except Exception:
            raise HTTPException(502, "Naver upstream returned non-JSON response")

    if strict:
        raise HTTPException(502, f"Naver upstream error {r.status_code}: {r.text[:300]}")
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    body["_status"] = r.status_code
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

async def _geocode_naver(
    query: str,
    cid: str,
    csec: str,
    bias: Optional[Tuple[float, float]] = None,  # (lat,lng)
) -> Tuple[float, float]:
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        raise HTTPException(400, "Empty query for geocoding")

    geocode_params = {"query": q}
    if bias:
        lat, lng = bias
        geocode_params["coordinate"] = f"{lng},{lat}"  # Naver expects lng,lat

    data = await _ncloud_get(
        "https://maps.apigw.ntruss.com/map-geocode/v2/geocode",
        geocode_params, cid, csec
    )
    addrs = (data or {}).get("addresses") or []
    if addrs:
        lng = float(addrs[0]["x"])
        lat = float(addrs[0]["y"])
        return (lat, lng)

    # place API fallback
    place_params = {"query": q}
    if bias:
        lat, lng = bias
        place_params["coordinate"] = f"{lng},{lat}"

    pdata = await _ncloud_get(
        "https://maps.apigw.ntruss.com/map-place/v1/search",
        place_params, cid, csec
    )
    places = (pdata or {}).get("places") or (pdata or {}).get("place") or []
    if places:
        lng = float(places[0].get("x"))
        lat = float(places[0].get("y"))
        return (lat, lng)

    raise HTTPException(404, f"Geocoding failed for: {q} (geocode=0, place=0)")

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

# ===== Endpoint =====
@router.post("/directions")
async def directions(req: DirectionsReq, settings: Settings = Depends(get_settings)):
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
    cid = csec = None
    if need_naver:
        cid, csec = _require_naver_keys(settings)

    # resolve origin/destination
    if o_ll is None:
        o_lat, o_lng = await _to_latlng(req.origin, cid, csec)
    else:
        o_lat, o_lng = o_ll

    if d_ll is None:
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
            lat, lng = await _to_latlng(w, cid, csec, bias=(o_lat, o_lng))
            wps_parsed.append((lat, lng))

    # -------- walking → MAPBOX --------
    if mode == "walking":
        return await _mapbox_directions_walking(
            o_lat, o_lng, d_lat, d_lng, waypoints=wps_parsed, lang="ko", steps=True, settings=settings
        )

    # -------- driving → NAVER --------
    if not cid:
        cid, csec = _require_naver_keys(settings)

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

    # fallback: legacy
    if isinstance(data, dict) and (
        data.get("_status") in (404,) or
        ("error" in data and ("Not Found" in str(data["error"]) or "URL not found" in str(data["error"])))
    ):
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
    return {"routes": [route_out], "provider": "naver"}
