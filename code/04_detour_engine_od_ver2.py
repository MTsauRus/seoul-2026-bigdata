"""
04_detour_engine_od_ver2.py
===========================
끊어진 서울 — 버스정류장 OD쌍 + T map 보행자 API 기반 우회비율 분석

[v1 대비 변경 사항]
  - 집계구 centroid → 버스정류장 (실제 도로 위, 의미있는 이동 기점/종점)
  - OSMnx NetworkX 경로 → T map 보행자 API (지하도·육교 포함 실제 한국 경로)
  - T map 결과 캐시 (cache/tmap_routes.pkl) → 반복 실행 시 API 미호출
  - API 키 .env 관리 (python-dotenv)

[처리 흐름]
  1. 지상철도 캐시 로드
  2. 버스정류장 OSM 다운로드 → 철도 1km 이내 필터 → 최대 300개
  3. 철도 구간별 (200m마다) 양쪽 버스정류장 K개씩 → OD쌍 생성
  4. 직선이 철도 교차 + 거리 500m~2000m 조건 필터
  5. T map 보행자 API로 실제 도보 거리·경로 계산 (캐시 우선)
  6. 구간별 평균 우회비율 집계
  7. 색상 지도 출력 (PNG + Folium HTML)

결과:
  output/detour_od_map_v2.png
  output/detour_od_interactive_v2.html
  cache/bus_stops.gpkg
  cache/tmap_routes.pkl
  cache/detour_od_results_v3.pkl

사전 설치:
  pip install osmnx geopandas folium matplotlib scipy pyproj requests python-dotenv

[성령 학습 포인트]
- STRtree: 수만 개 도형 중 겹치는 것을 O(log N)으로 찾는 공간 인덱스
- T map API: POST 요청으로 보행자 경로 계산. startX/Y = 경도/위도 (X=경도, Y=위도 순서 주의!)
- 캐싱: 동일 좌표 쌍에 대해 API를 두 번 호출하지 않도록 dict로 저장
"""

import json
import os
import pickle
import platform
import time
import warnings
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import requests
from dotenv import load_dotenv
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from pyproj import Transformer
from scipy.spatial import KDTree
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
load_dotenv()
TMAP_API_KEY = os.getenv("TMAP_API_KEY")

# ── 한글 폰트 (macOS/Windows/Linux) ─────────────────────────────
def _setup_korean_font():
    sys = platform.system()
    if sys == "Darwin":
        plt.rcParams["font.family"] = "AppleGothic"
    elif sys == "Windows":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        available = {f.name for f in fm.fontManager.ttflist}
        for c in ("NanumGothic", "UnDotum", "DejaVu Sans"):
            if c in available:
                plt.rcParams["font.family"] = c
                break
    plt.rcParams["axes.unicode_minus"] = False

_setup_korean_font()

# EPSG:5179 → WGS84 변환기
_to_wgs84 = Transformer.from_crs(5179, 4326, always_xy=True)
def _xy_to_latlon(x, y):
    """EPSG:5179 (x, y) → [lat, lon] for Folium/T map"""
    lon, lat = _to_wgs84.transform(x, y)
    return [lat, lon]

# ─────────────────────────────────────────────────────────────
# 0. 설정
# ─────────────────────────────────────────────────────────────
PLACE = "Seoul, South Korea"

DATA_DIR  = Path("data")
OUT_DIR   = Path("output")
CACHE_DIR = Path("cache")
OUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# 분석 파라미터
BUS_STOP_BUFFER_M = 1000   # 철도 1km 이내 버스정류장만 사용
MAX_STOPS         = 300    # 최대 버스정류장 수
MAX_OD_PAIRS      = 300    # 총 OD쌍 한도 = T map API 최대 호출 건수
MIN_OD_DIST_M     = 500    # OD쌍 최소 직선거리 (너무 가까운 쌍 제외)
MAX_OD_DIST_M     = 2000   # OD쌍 최대 직선거리 (도보 25분 기준)
K_NEAREST         = 5      # 구간당 반대편 최근접 버스정류장 수
RAIL_SAMPLE_M     = 200    # 철도 따라 구간 샘플 간격
RATIO_CAP         = 8.0    # 우회비율 최댓값 (이 이상은 같은 진한색)
TMAP_RATE_LIMIT_S = 0.5    # T map API 호출 간격 (초) — 초당 2회 제한


# ─────────────────────────────────────────────────────────────
# 1. 지상철도 로드
# ─────────────────────────────────────────────────────────────
def load_rail():
    p = CACHE_DIR / "surface_rail.gpkg"
    if not p.exists():
        raise FileNotFoundError(
            "cache/surface_rail.gpkg 없음 → make_detour_map_ver2.py 먼저 실행하세요"
        )
    print("[CACHE] surface_rail.gpkg 로드")
    return gpd.read_file(p)


# ─────────────────────────────────────────────────────────────
# 2. 버스정류장 로드 (OSMnx)
# ─────────────────────────────────────────────────────────────
def load_bus_stops(rail_gdf):
    """
    OSMnx로 서울 버스정류장 추출 → 지상철도 1km 이내 필터 → 최대 MAX_STOPS개

    반환: list of dict {name, x, y, lat, lon}
      - x, y: EPSG:5179 (직선거리 계산용)
      - lat, lon: WGS84 (T map API 입력용)
    """
    cache_f = CACHE_DIR / "bus_stops.gpkg"
    if cache_f.exists():
        print("[CACHE] bus_stops.gpkg 로드")
        gdf = gpd.read_file(cache_f)
    else:
        print("[1/5] 버스정류장 OSM 다운로드 중...")
        # highway=bus_stop: 서울 내 버스정류장 포인트
        stops_raw = ox.features_from_place(PLACE, tags={"highway": "bus_stop"})
        stops_raw = stops_raw[stops_raw.geometry.type == "Point"].copy()
        stops_raw = stops_raw.to_crs(5179)
        print(f"  전체 버스정류장: {len(stops_raw)}개")

        # 지상철도 BUS_STOP_BUFFER_M 이내 필터
        rail_union  = unary_union(rail_gdf.geometry)
        rail_buffer = rail_union.buffer(BUS_STOP_BUFFER_M)
        stops_near  = stops_raw[stops_raw.geometry.within(rail_buffer)].copy()
        print(f"  철도 {BUS_STOP_BUFFER_M//1000}km 이내: {len(stops_near)}개")

        # name 컬럼 정리
        if "name" in stops_near.columns:
            stops_near["stop_name"] = stops_near["name"].fillna("버스정류장")
        else:
            stops_near["stop_name"] = "버스정류장"

        # MAX_STOPS개로 제한 (random_state=42 → 재현 가능)
        if len(stops_near) > MAX_STOPS:
            stops_near = stops_near.sample(MAX_STOPS, random_state=42)

        gdf = stops_near[["stop_name", "geometry"]].copy()
        gdf.to_file(cache_f, driver="GPKG")
        print(f"  최종 사용: {len(gdf)}개 → bus_stops.gpkg 저장")

    # WGS84 좌표 추가
    _to_wgs84_local = Transformer.from_crs(5179, 4326, always_xy=True)
    result = []
    for _, row in gdf.iterrows():
        x, y = row.geometry.x, row.geometry.y
        lon, lat = _to_wgs84_local.transform(x, y)
        result.append({
            "name": row.get("stop_name", "버스정류장"),
            "x":   x,
            "y":   y,
            "lat": lat,
            "lon": lon,
        })
    print(f"  버스정류장 {len(result)}개 준비 완료")
    return result


# ─────────────────────────────────────────────────────────────
# 3. T map 보행자 API + 캐싱
# ─────────────────────────────────────────────────────────────
_TMAP_CACHE_PATH = CACHE_DIR / "tmap_routes.pkl"
_tmap_cache: dict = {}

def _tmap_cache_load():
    global _tmap_cache
    if _TMAP_CACHE_PATH.exists():
        with open(_TMAP_CACHE_PATH, "rb") as f:
            _tmap_cache = pickle.load(f)
        print(f"[CACHE] tmap_routes.pkl 로드 ({len(_tmap_cache)}건 캐시됨)")

def _tmap_cache_save():
    with open(_TMAP_CACHE_PATH, "wb") as f:
        pickle.dump(_tmap_cache, f)

def _tmap_cache_key(lat1, lon1, lat2, lon2):
    """좌표 소수점 4자리 반올림 (약 10m 정밀도) → 캐시 키"""
    return (round(lat1, 4), round(lon1, 4), round(lat2, 4), round(lon2, 4))

def tmap_walk_route(lat1, lon1, lat2, lon2):
    """
    T map 보행자 경로 API 호출 (캐시 우선).

    Args:
        lat1, lon1: 출발지 위도·경도 (WGS84)
        lat2, lon2: 도착지 위도·경도 (WGS84)

    반환:
        (path_wgs84: list[[lat, lon]], total_m: int)
        실패 시: ([], None)

    주의:
        T map API body는 startX = 경도, startY = 위도 (X=경도, Y=위도 순서!)
    """
    key = _tmap_cache_key(lat1, lon1, lat2, lon2)
    if key in _tmap_cache:
        return _tmap_cache[key]

    if not TMAP_API_KEY:
        print("  [경고] TMAP_API_KEY 미설정 — .env 파일 확인")
        return [], None

    url     = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
    headers = {"appKey": TMAP_API_KEY, "Content-Type": "application/json"}
    body    = {
        "startX":       str(lon1),   # T map: X = 경도
        "startY":       str(lat1),   # T map: Y = 위도
        "endX":         str(lon2),
        "endY":         str(lat2),
        "startName":    "출발",
        "endName":      "도착",
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "0",         # 0 = 기본 보행자 경로
    }

    try:
        resp     = requests.post(url, headers=headers, json=body, timeout=10)
        features = resp.json().get("features", [])
        path, total_m = [], 0
        for f in features:
            geom  = f.get("geometry", {})
            props = f.get("properties", {})
            if geom.get("type") == "LineString":
                # T map 응답: coordinates = [[lon, lat], ...] → Folium용 [lat, lon]으로 변환
                path.extend([[c[1], c[0]] for c in geom["coordinates"]])
            if "totalDistance" in props:
                total_m = int(props["totalDistance"])
        result = (path, total_m if total_m > 0 else None)
    except Exception as e:
        print(f"  [T map 오류] {e}")
        result = ([], None)

    _tmap_cache[key] = result
    return result


# ─────────────────────────────────────────────────────────────
# 4. 분석 준비: STRtree + KDTree 구축
# ─────────────────────────────────────────────────────────────
def prepare(stops, rail_gdf):
    """
    STRtree (철도 교차 판정) + KDTree (버스정류장 최근접 탐색) 인덱스 구축.
    반환: (stops_arr, stops_tree, rail_strtree, rail_geoms)
    """
    print("[2/5] 분석 준비 (STRtree + KDTree 구축)...")
    rail_geoms   = list(rail_gdf.geometry)
    rail_strtree = STRtree(rail_geoms)

    stops_arr  = np.array([[s["x"], s["y"]] for s in stops])
    stops_tree = KDTree(stops_arr)
    print(f"  버스정류장 {len(stops)}개 · 철도 도형 {len(rail_geoms)}개")
    return stops_arr, stops_tree, rail_strtree, rail_geoms


# ─────────────────────────────────────────────────────────────
# 5. OD쌍 생성 + T map 우회비율 계산
# ─────────────────────────────────────────────────────────────
def _collect_valid_pairs(stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf):
    """
    Phase 1: API 호출 없이 유효 OD쌍 후보 전체 수집.

    반환:
        candidate_pairs: list of (li, ri, straight_m, rail_pt_x, rail_pt_y, rail_name)
          - 같은 (li, ri)가 여러 구간에서 나올 수 있음 → 중복 제거 전 전체 목록
    """
    print(f"  [Phase 1] 유효 쌍 수집 중 (API 호출 없음)...")
    n_stops         = len(stops)
    candidate_pairs = []  # (li, ri, straight, pt_x, pt_y, name)
    skipped_nocross = 0

    for _, row in rail_gdf.iterrows():
        geom  = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        rname = row.get("name", "미상")

        for line in lines:
            total_len    = line.length
            sample_dists = np.arange(RAIL_SAMPLE_M / 2, total_len, RAIL_SAMPLE_M)

            for d in sample_dists:
                pt = line.interpolate(d)

                # 접선 → 수직 단위벡터
                p1 = line.interpolate(max(0.0, d - 20))
                p2 = line.interpolate(min(total_len, d + 20))
                tx, ty = p2.x - p1.x, p2.y - p1.y
                tlen   = (tx**2 + ty**2) ** 0.5
                if tlen < 1.0:
                    continue
                nx_, ny_ = -ty / tlen, tx / tlen

                k_query      = min(K_NEAREST * 3, n_stops)
                left_anchor  = np.array([pt.x + nx_ * 500, pt.y + ny_ * 500])
                right_anchor = np.array([pt.x - nx_ * 500, pt.y - ny_ * 500])

                _, left_idxs  = stops_tree.query(left_anchor,  k=k_query)
                _, right_idxs = stops_tree.query(right_anchor, k=k_query)

                if np.ndim(left_idxs)  == 0: left_idxs  = [int(left_idxs)]
                if np.ndim(right_idxs) == 0: right_idxs = [int(right_idxs)]

                left_cands  = [i for i in left_idxs
                               if np.linalg.norm(stops_arr[i] - [pt.x, pt.y]) <= MAX_OD_DIST_M][:K_NEAREST]
                right_cands = [i for i in right_idxs
                               if np.linalg.norm(stops_arr[i] - [pt.x, pt.y]) <= MAX_OD_DIST_M][:K_NEAREST]

                if not left_cands or not right_cands:
                    continue

                for li in left_cands:
                    for ri in right_cands:
                        if li == ri:
                            continue
                        sl, sr = stops[li], stops[ri]
                        straight = float(np.linalg.norm(
                            [sl["x"] - sr["x"], sl["y"] - sr["y"]]
                        ))
                        if straight < MIN_OD_DIST_M or straight > MAX_OD_DIST_M:
                            continue
                        line_ab    = LineString([(sl["x"], sl["y"]), (sr["x"], sr["y"])])
                        candidates = rail_strtree.query(line_ab)
                        crosses    = any(
                            line_ab.crosses(rail_geoms[c]) or line_ab.intersects(rail_geoms[c])
                            for c in candidates
                        )
                        if not crosses:
                            skipped_nocross += 1
                            continue
                        candidate_pairs.append((li, ri, straight, pt.x, pt.y, rname))

    print(f"  교차+거리 통과 후보 쌍: {len(candidate_pairs)}개 (교차 미통과: {skipped_nocross})")
    return candidate_pairs


def compute_od_detour(stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf):
    """
    버스정류장 OD쌍 기반 우회비율 계산 — 2단계 구조.

    Phase 1: 유효 쌍 전체 수집 (API 호출 없음)
      - 교차 + 거리 조건 통과 쌍 모두 수집
      - (li, ri) 중복 제거 → 고유 쌍 목록
    Phase 2: MAX_OD_PAIRS개로 제한 후 T map API 호출
      - 고유 쌍이 300개 초과 시 균등 샘플링 (random_state=42)
      - 각 고유 쌍에 대해 API 1회 호출 (캐시 우선)
    Phase 3: 구간별 결과 집계
      - API 결과를 각 철도 구간 포인트에 매핑
    """
    print(f"[3/5] OD쌍 우회비율 계산 중 (구간 {RAIL_SAMPLE_M}m마다, K={K_NEAREST})...")

    # ── Phase 1: 후보 쌍 수집 ───────────────────────────────────
    candidate_pairs = _collect_valid_pairs(
        stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf
    )
    if not candidate_pairs:
        print("  유효 쌍 없음")
        return []

    # ── Phase 2: 고유 쌍 추출 + MAX_OD_PAIRS개 제한 ────────────
    # 같은 (li, ri)가 여러 구간에서 중복될 수 있음 → set으로 고유화
    unique_pairs = {}  # (li, ri) → straight_m (첫 번째 등장 값 사용)
    for li, ri, straight, *_ in candidate_pairs:
        key = (li, ri)
        if key not in unique_pairs:
            unique_pairs[key] = straight

    print(f"  고유 OD쌍: {len(unique_pairs)}개 (한도: {MAX_OD_PAIRS}개)")

    if len(unique_pairs) > MAX_OD_PAIRS:
        rng      = np.random.RandomState(42)
        all_keys = list(unique_pairs.keys())
        chosen   = rng.choice(len(all_keys), MAX_OD_PAIRS, replace=False)
        unique_pairs = {all_keys[i]: unique_pairs[all_keys[i]] for i in chosen}
        print(f"  → {MAX_OD_PAIRS}개로 샘플링 (random_state=42)")

    selected_set = set(unique_pairs.keys())

    # ── T map API 호출 ──────────────────────────────────────────
    _tmap_cache_load()
    api_calls        = 0
    cache_hits       = 0
    skipped_api_fail = 0

    # 고유 쌍별로 API 1회 호출 (캐시 우선)
    api_results = {}  # (li, ri) → {walk_m, path_wgs84}
    print(f"  [Phase 2] T map API 호출 (최대 {len(selected_set)}건)...")
    for li, ri in selected_set:
        sl, sr   = stops[li], stops[ri]
        cache_key = _tmap_cache_key(sl["lat"], sl["lon"], sr["lat"], sr["lon"])
        if cache_key in _tmap_cache:
            cache_hits += 1
        else:
            api_calls += 1
            time.sleep(TMAP_RATE_LIMIT_S)

        path_wgs84, walk_m = tmap_walk_route(sl["lat"], sl["lon"], sr["lat"], sr["lon"])

        if walk_m is None or walk_m <= 0:
            skipped_api_fail += 1
            continue

        api_results[(li, ri)] = {"walk_m": walk_m, "path_wgs84": path_wgs84}

    if api_calls > 0:
        _tmap_cache_save()

    print(f"  신규 API {api_calls}건 · 캐시 {cache_hits}건 · 실패 {skipped_api_fail}건")

    # ── Phase 3: 구간별 결과 집계 ──────────────────────────────
    # 구간 포인트별로 유효 쌍 모아서 평균 우회비율 계산
    # candidate_pairs: (li, ri, straight, pt_x, pt_y, name)
    from collections import defaultdict
    seg_map = defaultdict(list)  # (pt_x, pt_y, name) → [(ratio, od_pair_dict), ...]

    for li, ri, straight, pt_x, pt_y, rname in candidate_pairs:
        if (li, ri) not in selected_set:
            continue
        if (li, ri) not in api_results:
            continue
        res    = api_results[(li, ri)]
        walk_m = res["walk_m"]
        ratio  = min(walk_m / straight, RATIO_CAP)
        sl, sr = stops[li], stops[ri]

        seg_key = (round(pt_x, 1), round(pt_y, 1), rname)
        seg_map[seg_key].append({
            "ratio":       round(ratio, 3),
            "od_pair": {
                "left_wgs84":  [sl["lat"], sl["lon"]],
                "right_wgs84": [sr["lat"], sr["lon"]],
                "left_gu":     sl["name"],
                "right_gu":    sr["name"],
                "straight_m":  int(straight),
                "walk_m":      int(walk_m),
                "ratio":       round(ratio, 3),
                "path_wgs84":  res["path_wgs84"],
            },
        })

    # 구간 포인트별 평균 집계 → results 리스트
    # 원래 좌표 복원을 위해 candidate_pairs에서 (pt_x, pt_y) 인덱스 매핑
    pt_coords = {}  # seg_key → (pt_x, pt_y)
    for li, ri, straight, pt_x, pt_y, rname in candidate_pairs:
        seg_key = (round(pt_x, 1), round(pt_y, 1), rname)
        pt_coords[seg_key] = (pt_x, pt_y)

    results = []
    for seg_key, entries in seg_map.items():
        pt_x, pt_y = pt_coords[seg_key]
        _, _, rname = seg_key
        ratios   = [e["ratio"]   for e in entries]
        od_pairs = [e["od_pair"] for e in entries]
        results.append({
            "x":        pt_x,
            "y":        pt_y,
            "ratio":    round(sum(ratios) / len(ratios), 3),
            "n_pairs":  len(ratios),
            "od_pairs": od_pairs,
            "name":     rname,
        })

    print(f"  완료: {len(results)}개 유효 구간 포인트")
    if results:
        ratios_all = [r["ratio"] for r in results]
        print(f"  우회비율 — 중앙: {np.median(ratios_all):.2f}, 최대: {max(ratios_all):.2f}")
    return results


# ─────────────────────────────────────────────────────────────
# 6. 시각화 (PNG + Folium HTML)
# ─────────────────────────────────────────────────────────────
def make_maps(results, rail_gdf):
    print("[4/5] 지도 렌더링...")
    if not results:
        print("  결과 없음 — 지도 생성 건너뜀")
        return

    cmap = LinearSegmentedColormap.from_list(
        "detour", ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026", "#6b0011"]
    )
    norm = mcolors.Normalize(vmin=1.0, vmax=RATIO_CAP)

    # ── PNG ──────────────────────────────────────────────────────
    BG = "#0d1117"
    fig, ax = plt.subplots(figsize=(14, 14), facecolor=BG)
    ax.set_facecolor(BG)
    rail_gdf.plot(ax=ax, color="#21262d", linewidth=4, alpha=0.8, zorder=2)

    xs     = np.array([r["x"]     for r in results])
    ys     = np.array([r["y"]     for r in results])
    ratios = np.array([r["ratio"] for r in results])
    names  = [r["name"] for r in results]

    for uname in dict.fromkeys(names):
        idxs = [i for i, n in enumerate(names) if n == uname]
        if len(idxs) < 2:
            continue
        sx, sy, sr = xs[idxs], ys[idxs], ratios[idxs]
        segs = [[[sx[i], sy[i]], [sx[i+1], sy[i+1]]] for i in range(len(sx)-1)]
        sc_r = (sr[:-1] + sr[1:]) / 2.0
        lc   = LineCollection(segs, cmap=cmap, norm=norm, linewidth=6, zorder=3, alpha=0.92)
        lc.set_array(sc_r)
        ax.add_collection(lc)

    sc   = ax.scatter(xs, ys, c=ratios, cmap=cmap, norm=norm, s=25, alpha=0.5, zorder=4, linewidths=0)
    cbar = plt.colorbar(sc, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label(f"우회비율 (1.0=단절없음, {RATIO_CAP:.0f}.0={RATIO_CAP:.0f}배 우회)",
                   color="white", fontsize=10)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=9)
    cbar.outline.set_edgecolor("#30363d")

    ax.set_title("끊어진 서울 — 지상철도 보행 단절 지도 (버스정류장 OD쌍 + T map)",
                 color="white", fontsize=17, fontweight="bold", pad=15, loc="left")
    ax.text(0.01, 0.97,
            f"버스정류장 쌍 ({MIN_OD_DIST_M//1000}~{MAX_OD_DIST_M//1000}km, 직선이 철도 교차하는 쌍만)\n"
            "T map 보행자 API 실측 | 진한 빨강 = 단절이 심한 구간",
            transform=ax.transAxes, color="#8b949e", fontsize=9, va="top")
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout(pad=0.5)
    png_path = OUT_DIR / "detour_od_map_v2.png"
    plt.savefig(png_path, dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  PNG: {png_path}")

    html_path = _make_folium(results, rail_gdf)
    print(f"  HTML: {html_path}")
    print(f"\n완료")


def _make_folium(results, rail_gdf):
    m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="CartoDB dark_matter")
    folium.TileLayer("OpenStreetMap", name="OSM 지도").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="위성사진",
    ).add_to(m)

    for _, row in rail_gdf.to_crs(4326).iterrows():
        geom = row.geometry
        for line in (list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]):
            folium.PolyLine([(c[1], c[0]) for c in line.coords],
                            color="#fff", weight=2, opacity=0.2).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    marker_data = []
    for r in results:
        latlng = _xy_to_latlon(r["x"], r["y"])
        worst  = max(r["od_pairs"], key=lambda p: p["ratio"]) if r["od_pairs"] else None
        marker_data.append({
            "latlng":  latlng,
            "ratio":   r["ratio"],
            "name":    r["name"],
            "n_pairs": r["n_pairs"],
            "worst":   worst,
        })

    slider_html = """
    <div id="slider-panel" style="
        position:fixed; top:80px; right:10px; z-index:9999;
        background:rgba(13,17,23,0.93); border:1px solid #30363d;
        border-radius:10px; padding:14px 16px; color:white;
        font-family:-apple-system,'Helvetica Neue',sans-serif;
        font-size:13px; width:260px;
        box-shadow:0 4px 20px rgba(0,0,0,0.7)">
      <div style="font-weight:700;font-size:14px;color:#e6edf3;margin-bottom:10px">
        우회비율 필터 (버스정류장 OD쌍)
      </div>
      <div style="margin-bottom:6px;display:flex;align-items:baseline;gap:6px">
        <span style="color:#8b949e">최소</span>
        <span id="threshold-display" style="color:#fd8d3c;font-weight:700;font-size:22px;line-height:1">1.0</span>
        <span style="color:#8b949e">배 이상만</span>
      </div>
      <input type="range" id="ratio-slider" min="1.0" max="8.0" step="0.5" value="1.0"
             style="width:100%;accent-color:#fd8d3c;cursor:pointer;margin:4px 0 2px">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#444c56;margin-bottom:10px">
        <span>1.0배</span><span>8.0배</span>
      </div>
      <div style="padding-top:10px;border-top:1px solid #21262d;color:#8b949e;font-size:12px" id="marker-count">
        로딩 중...</div>
      <div style="margin-top:6px;color:#444c56;font-size:11px">
        ● 점 클릭 → 최악 OD쌍 경로 표시<br>지도 빈 곳 클릭 → 경로 숨김
      </div>
    </div>"""
    m.get_root().html.add_child(folium.Element(slider_html))

    map_var = m.get_name()
    js = f"""
window.addEventListener('load', function() {{
  var map = window['{map_var}'];
  if (!map) {{
    var k = Object.keys(window).find(function(k) {{ return k.startsWith('map_'); }});
    map = k ? window[k] : null;
  }}
  if (!map) {{ console.error('Folium map not found'); return; }}

  var markerLayer = L.layerGroup().addTo(map);
  var routeLayer  = L.layerGroup().addTo(map);
  var markerData  = {json.dumps(marker_data, ensure_ascii=False)};

  var _stops = [[255,255,178],[254,204,92],[253,141,60],[240,59,32],[189,0,38],[107,0,17]];
  function getColor(ratio) {{
    var t = Math.min(1.0, Math.max(0.0, (ratio - 1.0) / 7.0));
    var n = _stops.length - 1;
    var i = Math.min(Math.floor(t * n), n - 1);
    var f = t * n - i;
    return 'rgb(' +
      Math.round(_stops[i][0] + f*(_stops[i+1][0]-_stops[i][0])) + ',' +
      Math.round(_stops[i][1] + f*(_stops[i+1][1]-_stops[i][1])) + ',' +
      Math.round(_stops[i][2] + f*(_stops[i+1][2]-_stops[i][2])) + ')';
  }}

  function showOD(d) {{
    routeLayer.clearLayers();
    var w = d.worst;
    if (!w) return;
    var col = getColor(d.ratio);

    /* ① 직선 경로 (흰 점선) */
    L.polyline([w.left_wgs84, w.right_wgs84], {{
      color:'#ffffff', weight:2, opacity:0.75, dashArray:'8 5'
    }}).bindTooltip('직선거리 ' + w.straight_m + 'm').addTo(routeLayer);

    /* ② T map 실제 보행 경로 (컬러 실선) */
    if (w.path_wgs84 && w.path_wgs84.length > 1) {{
      L.polyline(w.path_wgs84, {{
        color: col, weight: 5, opacity: 0.92
      }}).bindTooltip('T map 실제 보행 ' + w.walk_m + 'm').addTo(routeLayer);
    }}

    /* ③ 출발 버스정류장 (초록) */
    L.circleMarker(w.left_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#00e676', fillOpacity:1.0
    }}).bindTooltip('출발: ' + (w.left_gu || '?')).addTo(routeLayer);

    /* ④ 도착 버스정류장 (빨강) */
    L.circleMarker(w.right_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#ff5252', fillOpacity:1.0
    }}).bindTooltip('도착: ' + (w.right_gu || '?')).addTo(routeLayer);

    /* ⑤ 정보 팝업 */
    var from = w.left_gu  || '출발';
    var to   = w.right_gu || '도착';
    L.popup({{ maxWidth:300 }})
      .setLatLng(d.latlng)
      .setContent(
        '<div style="font-family:-apple-system,sans-serif;padding:4px 6px;min-width:240px">' +
        '<div style="font-size:15px;font-weight:700;margin-bottom:4px">' + d.name + '</div>' +
        '<div style="color:#555;font-size:11px;margin-bottom:8px">' +
          '🚌 ' + from + ' → ' + to + '</div>' +
        '<hr style="margin:6px 0;border-color:#eee">' +
        '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
        '<tr><td style="color:#888;padding:2px 0">분석 OD쌍</td>' +
            '<td style="text-align:right;font-weight:600">' + d.n_pairs + '개</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">📏 직선거리</td>' +
            '<td style="text-align:right;font-weight:600">' + w.straight_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">🚶 T map 보행</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' + w.walk_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">➕ 추가 거리</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' +
            (w.walk_m - w.straight_m) + 'm 더</td></tr>' +
        '</table>' +
        '<div style="margin-top:8px;padding:6px;background:#f8f8f8;border-radius:4px;text-align:center">' +
        '<span style="font-size:22px;font-weight:700;color:' + col + '">' + d.ratio.toFixed(2) + '배</span>' +
        '<span style="color:#888;font-size:12px"> 우회비율</span>' +
        '</div>' +
        '<div style="margin-top:6px;font-size:11px;color:#aaa">' +
        '● 초록=출발정류장 · 빨강=도착정류장 · 점선=직선 · 실선=T map경로</div>' +
        '</div>'
      ).openOn(map);
  }}

  function updateMarkers(threshold) {{
    markerLayer.clearLayers();
    var count = 0;
    markerData.forEach(function(d) {{
      if (d.ratio < threshold) return;
      count++;
      var radius = 5 + (d.ratio - 1.0) / 7.0 * 10;
      var color  = getColor(d.ratio);
      var mk = L.circleMarker(d.latlng, {{
        radius:radius, color:color, fillColor:color, fillOpacity:0.85, weight:0
      }});
      mk.bindTooltip(d.name + ' | ' + d.ratio.toFixed(1) + '배');
      mk.on('click', function(e) {{ L.DomEvent.stopPropagation(e); showOD(d); }});
      markerLayer.addLayer(mk);
    }});
    var el = document.getElementById('marker-count');
    if (el) el.textContent = count + '개 구간 표시 중 (전체 ' + markerData.length + '개)';
  }}

  map.on('click', function() {{ routeLayer.clearLayers(); }});

  var slider = document.getElementById('ratio-slider');
  if (slider) {{
    slider.addEventListener('input', function() {{
      var val = parseFloat(this.value);
      document.getElementById('threshold-display').textContent = val.toFixed(1);
      updateMarkers(val);
    }});
  }}

  updateMarkers(1.0);
}});
"""
    m.get_root().script.add_child(folium.Element(js))

    html_path = OUT_DIR / "detour_od_interactive_v2.html"
    m.save(html_path)
    return html_path


# ─────────────────────────────────────────────────────────────
# 실행 진입점
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. 지상철도 로드 (cache/surface_rail.gpkg)
    rail = load_rail()

    # 2. 버스정류장 로드/다운로드 (cache/bus_stops.gpkg)
    stops = load_bus_stops(rail)

    # 3. 분석 준비 (STRtree + KDTree)
    stops_arr, stops_tree, rail_strtree, rail_geoms = prepare(stops, rail)

    # 4. OD쌍 우회비율 계산 (캐시: cache/detour_od_results_v3.pkl)
    results_pkl = CACHE_DIR / "detour_od_results_v3.pkl"
    if results_pkl.exists():
        print("[CACHE] detour_od_results_v3.pkl 로드")
        with open(results_pkl, "rb") as f:
            results = pickle.load(f)
    else:
        print("[실행] OD쌍 계산 시작...")
        results = compute_od_detour(stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail)
        with open(results_pkl, "wb") as f:
            pickle.dump(results, f)
        print(f"  detour_od_results_v3.pkl 저장")

    # 5. 지도 출력
    make_maps(results, rail)
