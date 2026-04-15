"""
04_detour_engine_od_ver3.py
===========================
끊어진 서울 — 인구 우선순위 OD쌍 + 수동 지점 + 차량기지 분석 (v3)

[ver2 대비 변경 사항]
  1. 인구 압력 기반 구간 우선순위
       - 집계구 면적 역수(인구밀도 대리지표)로 철도 구간별 점수 계산
       - 상위 POP_PERCENTILE_CUTOFF% 구간에만 OD쌍 생성 → API 예산 집중
  2. 수동 OD 앵커 포인트 (팀원 직접 지정)
       - data/manual_od_points.json 파일로 핵심 교차 지점 수동 지정
       - 인구 필터 우회 → 항상 포함 (팀원 5명 × 1000건/일 = 5000건/일)
  3. 차량기지 레이어 시각화
       - OSM railway=depot/yard + landuse=railway 폴리곤
       - Folium 지도에 오렌지 반투명 레이어로 표시
       - 면적, 주변 인구밀도 팝업
  4. T map 다중 키 지원 (round-robin)
       - .env에 TMAP_API_KEY_1 ~ TMAP_API_KEY_5 설정

[처리 흐름]
  1. 지상철도 / 버스정류장 로드
  2. 집계구 중심점 로드 → 인구 압력 계산
  3. 수동 앵커 포인트 로드 (JSON)
  4. 차량기지 폴리곤 로드 (OSMnx)
  5. Phase 1: 유효 쌍 수집 (인구 상위 구간 + 수동 앵커)
  6. Phase 2: MAX_OD_PAIRS개 제한 → T map API 호출
  7. 지도 출력 (차량기지 레이어 포함)

결과:
  output/detour_od_map_v3.png
  output/detour_od_interactive_v3.html

캐시:
  cache/bus_stops.gpkg
  cache/pop_centroids.npy / pop_weights.npy
  cache/pop_pressure.pkl
  cache/depots.gpkg
  cache/tmap_routes.pkl
  cache/detour_od_results_ver3.pkl
"""

import json
import os
import pickle
import platform
import time
import warnings
from collections import defaultdict
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
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
load_dotenv()

# T map 다중 키 (round-robin)
_TMAP_KEYS = [
    k for k in [os.getenv(f"TMAP_API_KEY_{i}") for i in range(1, 6)]
    if k
]
# 단일 키 폴백
if not _TMAP_KEYS and os.getenv("TMAP_API_KEY"):
    _TMAP_KEYS = [os.getenv("TMAP_API_KEY")]
_tmap_key_idx = 0

def _next_tmap_key() -> str | None:
    global _tmap_key_idx
    if not _TMAP_KEYS:
        return None
    key = _TMAP_KEYS[_tmap_key_idx % len(_TMAP_KEYS)]
    _tmap_key_idx += 1
    return key

# ── 한글 폰트 ──────────────────────────────────────────────────
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

_to_wgs84 = Transformer.from_crs(5179, 4326, always_xy=True)
_from_wgs84 = Transformer.from_crs(4326, 5179, always_xy=True)

def _xy_to_latlon(x, y):
    lon, lat = _to_wgs84.transform(x, y)
    return [lat, lon]

def _latlon_to_xy(lat, lon):
    x, y = _from_wgs84.transform(lon, lat)
    return x, y

# ─────────────────────────────────────────────────────────────
# 0. 설정
# ─────────────────────────────────────────────────────────────
PLACE = "Seoul, South Korea"

DATA_DIR  = Path("data")
OUT_DIR   = Path("output")
CACHE_DIR = Path("cache")
OUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

SHP_PATH       = DATA_DIR / "bnd_oa_11_2025_2Q" / "bnd_oa_11_2025_2Q.shp"
MANUAL_OD_PATH = DATA_DIR / "manual_od_points.json"

# 기본 파라미터
BUS_STOP_BUFFER_M    = 1000   # 버스정류장 검색 반경
MAX_STOPS            = 300    # 최대 버스정류장 수
MAX_OD_PAIRS         = 300    # T map API 호출 한도 (다중 키 사용 시 늘릴 것)
MIN_OD_DIST_M        = 500
MAX_OD_DIST_M        = 2000
K_NEAREST            = 5
RAIL_SAMPLE_M        = 200
RATIO_CAP            = 8.0
TMAP_RATE_LIMIT_S    = 0.5

# ver3 신규 파라미터
POP_SCORE_RADIUS_M   = 1000   # 인구 압력 계산 반경
POP_PERCENTILE_CUTOFF = 70    # 인구 압력 상위 X% 구간만 자동 OD 생성 (나머지 제외)
DEPOT_MIN_AREA_M2    = 20_000 # 차량기지 최소 면적 (landuse=railway 필터용)
DEPOT_POP_RADIUS_M   = 500    # 차량기지 주변 인구 계산 반경


# ─────────────────────────────────────────────────────────────
# 1. 철도 / 버스정류장 로드 (ver2와 동일)
# ─────────────────────────────────────────────────────────────
def load_rail():
    p = CACHE_DIR / "surface_rail.gpkg"
    if not p.exists():
        raise FileNotFoundError("cache/surface_rail.gpkg 없음 → make_detour_map_ver2.py 먼저 실행")
    print("[CACHE] surface_rail.gpkg 로드")
    return gpd.read_file(p)


def load_bus_stops(rail_gdf):
    cache_f = CACHE_DIR / "bus_stops.gpkg"
    if cache_f.exists():
        print("[CACHE] bus_stops.gpkg 로드")
        gdf = gpd.read_file(cache_f)
    else:
        print("[데이터] 버스정류장 OSM 다운로드...")
        stops_raw = ox.features_from_place(PLACE, tags={"highway": "bus_stop"})
        stops_raw = stops_raw[stops_raw.geometry.type == "Point"].copy()
        stops_raw = stops_raw.to_crs(5179)
        rail_buffer = unary_union(rail_gdf.geometry).buffer(BUS_STOP_BUFFER_M)
        stops_near  = stops_raw[stops_raw.geometry.within(rail_buffer)].copy()
        if "name" in stops_near.columns:
            stops_near["stop_name"] = stops_near["name"].fillna("버스정류장")
        else:
            stops_near["stop_name"] = "버스정류장"
        if len(stops_near) > MAX_STOPS:
            stops_near = stops_near.sample(MAX_STOPS, random_state=42)
        gdf = stops_near[["stop_name", "geometry"]].copy()
        gdf.to_file(cache_f, driver="GPKG")
        print(f"  {len(gdf)}개 저장 → bus_stops.gpkg")

    _t = Transformer.from_crs(5179, 4326, always_xy=True)
    result = []
    for _, row in gdf.iterrows():
        x, y = row.geometry.x, row.geometry.y
        lon, lat = _t.transform(x, y)
        result.append({"name": row.get("stop_name", "버스정류장"),
                       "x": x, "y": y, "lat": lat, "lon": lon})
    print(f"  버스정류장 {len(result)}개 준비")
    return result


# ─────────────────────────────────────────────────────────────
# 2. 집계구 인구 대리지표 (면적 역수)
# ─────────────────────────────────────────────────────────────
def load_census_centroids():
    """
    집계구 폴리곤 로드 → 중심점 + 인구 대리지표(면적 역수) 반환.

    [코드 체계 불일치 이슈]
    bnd_oa_11_2025_2Q.shp (TOT_OA_CD, 14자리)와
    LOCAL_PEOPLE_20260409.csv (집계구코드, 13자리)는
    서로 다른 기준연도 코드 체계를 사용하여 직접 조인 불가.
    → 집계구 면적 역수(1/m²)를 인구밀도 대리지표로 사용.
      (도심 고밀 지역 = 집계구 작음 = 역수 큼 = 높은 가중치)

    반환:
        cent_xy:   np.ndarray (N, 2) — (x, y) EPSG:5179
        pop_wts:   np.ndarray (N,)  — 1/area_m2 × 1e6 (무차원 밀도 지표)
        cent_tree: KDTree
    """
    xy_cache  = CACHE_DIR / "pop_centroids.npy"
    wt_cache  = CACHE_DIR / "pop_weights.npy"

    if xy_cache.exists() and wt_cache.exists():
        print("[CACHE] pop_centroids / pop_weights 로드")
        return np.load(xy_cache), np.load(wt_cache), KDTree(np.load(xy_cache))

    print("[데이터] 집계구 SHP 로드 (인구밀도 대리지표 계산)...")
    oa = gpd.read_file(SHP_PATH, encoding="euc-kr")
    oa = oa.to_crs(5179)
    centroids = oa.geometry.centroid
    areas     = oa.geometry.area.clip(lower=1.0)  # 0 방지

    cent_xy  = np.array([[g.x, g.y] for g in centroids])
    pop_wts  = (1.0 / areas.values) * 1e6  # 역수 × 스케일

    np.save(xy_cache, cent_xy)
    np.save(wt_cache, pop_wts)
    print(f"  집계구 {len(cent_xy)}개 처리 → pop_centroids.npy 저장")
    return cent_xy, pop_wts, KDTree(cent_xy)


# ─────────────────────────────────────────────────────────────
# 3. 공통 철도 샘플 포인트 생성기 (핵심: 두 곳에서 동일하게 사용)
# ─────────────────────────────────────────────────────────────
def _iter_rail_sample_points(rail_gdf, sample_m=RAIL_SAMPLE_M):
    """
    철도 구간을 sample_m 간격으로 순회하며 샘플 포인트 yield.

    Yield: (pt, nx_, ny_, rname)
      - pt:   Shapely Point (EPSG:5179)
      - nx_, ny_: 철도 수직 단위벡터 (좌/우 구분용)
      - rname: 노선명
    """
    for _, row in rail_gdf.iterrows():
        geom  = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        rname = row.get("name", "미상")
        for line in lines:
            total_len    = line.length
            sample_dists = np.arange(sample_m / 2, total_len, sample_m)
            for d in sample_dists:
                pt = line.interpolate(d)
                p1 = line.interpolate(max(0.0, d - 20))
                p2 = line.interpolate(min(total_len, d + 20))
                tx, ty = p2.x - p1.x, p2.y - p1.y
                tlen   = (tx**2 + ty**2) ** 0.5
                if tlen < 1.0:
                    continue
                nx_, ny_ = -ty / tlen, tx / tlen
                yield pt, nx_, ny_, rname


# ─────────────────────────────────────────────────────────────
# 4. 인구 압력 점수 계산
# ─────────────────────────────────────────────────────────────
def compute_pop_pressure(rail_gdf, cent_xy, pop_wts, cent_tree):
    """
    각 철도 샘플 포인트별 반경 POP_SCORE_RADIUS_M 내 인구 밀도 합산.

    반환:
        pop_scores: dict { (round(pt.x,1), round(pt.y,1)): float }

    [_iter_rail_sample_points와 동일한 루프로 key 일치 보장]
    """
    cache_f = CACHE_DIR / "pop_pressure.pkl"
    if cache_f.exists():
        print("[CACHE] pop_pressure.pkl 로드")
        with open(cache_f, "rb") as f:
            return pickle.load(f)

    print("[계산] 철도 구간별 인구 압력 점수 계산 중...")
    pop_scores = {}
    for pt, *_ in _iter_rail_sample_points(rail_gdf):
        idxs  = cent_tree.query_ball_point([pt.x, pt.y], POP_SCORE_RADIUS_M)
        score = float(pop_wts[idxs].sum()) if idxs else 0.0
        pop_scores[(round(pt.x, 1), round(pt.y, 1))] = score

    with open(cache_f, "wb") as f:
        pickle.dump(pop_scores, f)
    print(f"  {len(pop_scores)}개 구간 점수 산출 → pop_pressure.pkl 저장")
    return pop_scores


# ─────────────────────────────────────────────────────────────
# 5. 수동 앵커 포인트 (팀원 직접 지정)
# ─────────────────────────────────────────────────────────────
def load_manual_anchors():
    """
    data/manual_od_points.json 로드.

    JSON 형식:
    [
      {
        "name": "수색차량기지 남쪽 교차",
        "lat": 37.574,
        "lon": 126.893,
        "note": "수색역~능곡역 구간, 차량기지 남단 단절 심각"
      },
      ...
    ]

    반환: list of dict (x, y 추가됨, EPSG:5179)
    """
    if not MANUAL_OD_PATH.exists():
        print(f"  [INFO] {MANUAL_OD_PATH} 없음 → 수동 앵커 없이 진행")
        return []
    with open(MANUAL_OD_PATH, encoding="utf-8") as f:
        pts = json.load(f)
    for p in pts:
        p["x"], p["y"] = _latlon_to_xy(p["lat"], p["lon"])
    print(f"  수동 앵커 포인트 {len(pts)}개 로드")
    return pts


def _nearest_rail_point(x, y, rail_gdf):
    """
    (x, y) EPSG:5179 좌표에서 가장 가까운 철도 위의 점과 수직 벡터 반환.

    반환: (pt_x, pt_y, nx_, ny_, rname)
    """
    best_dist = float("inf")
    best_pt   = None
    best_nx   = 0.0
    best_ny   = 1.0
    best_name = "미상"
    query_pt  = Point(x, y)

    for _, row in rail_gdf.iterrows():
        geom  = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            _, proj = nearest_points(query_pt, line)
            dist    = query_pt.distance(proj)
            if dist < best_dist:
                best_dist = dist
                # 접선 계산: 투영점 앞뒤 20m
                d   = line.project(proj)
                tot = line.length
                p1  = line.interpolate(max(0.0, d - 20))
                p2  = line.interpolate(min(tot, d + 20))
                tx, ty = p2.x - p1.x, p2.y - p1.y
                tlen   = (tx**2 + ty**2) ** 0.5
                if tlen >= 1.0:
                    best_pt   = proj
                    best_nx   = -ty / tlen
                    best_ny   =  tx / tlen
                    best_name = row.get("name", "미상")

    if best_pt is None:
        return x, y, 0.0, 1.0, "미상"
    return best_pt.x, best_pt.y, best_nx, best_ny, best_name


def _pairs_from_anchor(anchor, stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf):
    """
    수동 앵커 포인트 1개에서 유효 OD쌍 후보 생성.

    반환: list of (li, ri, straight, pt_x, pt_y, rname)
          — _collect_valid_pairs와 동일 형식
    """
    pt_x, pt_y, nx_, ny_, rname = _nearest_rail_point(anchor["x"], anchor["y"], rail_gdf)
    anchor_name = f"[수동] {anchor.get('name', '?')}"

    k_query = min(K_NEAREST * 3, len(stops))
    left_anchor  = np.array([pt_x + nx_ * 500, pt_y + ny_ * 500])
    right_anchor = np.array([pt_x - nx_ * 500, pt_y - ny_ * 500])
    _, left_idxs  = stops_tree.query(left_anchor,  k=k_query)
    _, right_idxs = stops_tree.query(right_anchor, k=k_query)
    if np.ndim(left_idxs)  == 0: left_idxs  = [int(left_idxs)]
    if np.ndim(right_idxs) == 0: right_idxs = [int(right_idxs)]

    left_cands  = [i for i in left_idxs
                   if np.linalg.norm(stops_arr[i] - [pt_x, pt_y]) <= MAX_OD_DIST_M][:K_NEAREST]
    right_cands = [i for i in right_idxs
                   if np.linalg.norm(stops_arr[i] - [pt_x, pt_y]) <= MAX_OD_DIST_M][:K_NEAREST]

    pairs = []
    for li in left_cands:
        for ri in right_cands:
            if li == ri:
                continue
            sl, sr = stops[li], stops[ri]
            straight = float(np.linalg.norm([sl["x"] - sr["x"], sl["y"] - sr["y"]]))
            if straight < MIN_OD_DIST_M or straight > MAX_OD_DIST_M:
                continue
            line_ab    = LineString([(sl["x"], sl["y"]), (sr["x"], sr["y"])])
            candidates = rail_strtree.query(line_ab)
            crosses    = any(
                line_ab.crosses(rail_geoms[c]) or line_ab.intersects(rail_geoms[c])
                for c in candidates
            )
            if not crosses:
                continue
            pairs.append((li, ri, straight, pt_x, pt_y, anchor_name))
    return pairs


# ─────────────────────────────────────────────────────────────
# 6. 차량기지 로드
# ─────────────────────────────────────────────────────────────
def load_depots(cent_xy, pop_wts, cent_tree):
    """
    OSMnx로 서울 차량기지(depot/yard) 폴리곤 로드.

    쿼리 전략:
      A. railway=depot / railway=yard   → 모든 폴리곤 (면적 제한 없음)
      B. landuse=railway                → 폴리곤 면적 > DEPOT_MIN_AREA_M2 만
         (B는 선로 회랑까지 포함하므로 큰 것만)

    반환: GeoDataFrame [name, area_m2, nearby_pop, geometry(Polygon)] EPSG:5179
    """
    cache_f = CACHE_DIR / "depots.gpkg"
    if cache_f.exists():
        print("[CACHE] depots.gpkg 로드")
        dep = gpd.read_file(cache_f)
    else:
        print("[데이터] 차량기지 OSM 다운로드...")
        frames = []

        try:
            d1 = ox.features_from_place(PLACE, tags={"railway": ["depot", "yard"]})
            d1 = d1[d1.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            frames.append(d1)
            print(f"  railway=depot/yard: {len(d1)}개")
        except Exception as e:
            print(f"  railway=depot/yard 쿼리 실패: {e}")

        try:
            d2 = ox.features_from_place(PLACE, tags={"landuse": "railway"})
            d2 = d2[d2.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            frames.append(d2)
            print(f"  landuse=railway: {len(d2)}개 (면적 필터 전)")
        except Exception as e:
            print(f"  landuse=railway 쿼리 실패: {e}")

        if not frames:
            print("  차량기지 데이터 없음")
            return gpd.GeoDataFrame(columns=["name", "area_m2", "nearby_pop", "geometry"],
                                    crs="EPSG:5179")

        import pandas as _pd
        combined = _pd.concat([f[["name", "geometry"]] if "name" in f.columns
                                else f[["geometry"]].assign(name="미상") for f in frames],
                               ignore_index=True)
        combined = gpd.GeoDataFrame(combined, crs="EPSG:4326").to_crs(5179)
        combined["area_m2"] = combined.geometry.area

        # landuse=railway 소형 조각 제거
        combined = combined[combined["area_m2"] >= DEPOT_MIN_AREA_M2].copy()

        # 중복 제거: 중심점 거리 50m 이내면 더 큰 것만
        centroids = combined.geometry.centroid
        cent_pts  = np.array([[g.x, g.y] for g in centroids])
        keep      = np.ones(len(combined), dtype=bool)
        for i in range(len(combined)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(combined)):
                if not keep[j]:
                    continue
                d = np.linalg.norm(cent_pts[i] - cent_pts[j])
                if d < 50:
                    if combined.iloc[i]["area_m2"] >= combined.iloc[j]["area_m2"]:
                        keep[j] = False
                    else:
                        keep[i] = False
                        break
        combined = combined[keep].copy()

        # name 정리
        if "name" in combined.columns:
            combined["name"] = combined["name"].fillna("미상 차량기지")
        else:
            combined["name"] = "미상 차량기지"

        dep = combined[["name", "area_m2", "geometry"]].copy()
        dep.to_file(cache_f, driver="GPKG")
        print(f"  최종 차량기지: {len(dep)}개 → depots.gpkg 저장")

    # 주변 인구 밀도 계산
    dep_centroids = dep.geometry.centroid
    nearby_pop = []
    for g in dep_centroids:
        idxs = cent_tree.query_ball_point([g.x, g.y], DEPOT_POP_RADIUS_M)
        nearby_pop.append(float(pop_wts[idxs].sum()) if idxs else 0.0)
    dep["nearby_pop"] = nearby_pop

    print(f"  차량기지 {len(dep)}개 (총 면적: {dep['area_m2'].sum()/1e6:.2f} km²)")
    return dep


# ─────────────────────────────────────────────────────────────
# 7. T map API + 캐싱 (다중 키 지원)
# ─────────────────────────────────────────────────────────────
_TMAP_CACHE_PATH = CACHE_DIR / "tmap_routes.pkl"
_tmap_cache: dict = {}

def _tmap_cache_load():
    global _tmap_cache
    if _TMAP_CACHE_PATH.exists():
        with open(_TMAP_CACHE_PATH, "rb") as f:
            _tmap_cache = pickle.load(f)
        print(f"[CACHE] tmap_routes.pkl ({len(_tmap_cache)}건)")

def _tmap_cache_save():
    with open(_TMAP_CACHE_PATH, "wb") as f:
        pickle.dump(_tmap_cache, f)

def _tmap_cache_key(lat1, lon1, lat2, lon2):
    return (round(lat1, 4), round(lon1, 4), round(lat2, 4), round(lon2, 4))

def tmap_walk_route(lat1, lon1, lat2, lon2):
    """T map 보행자 경로 (캐시 우선, 다중 키 round-robin)."""
    key = _tmap_cache_key(lat1, lon1, lat2, lon2)
    if key in _tmap_cache:
        return _tmap_cache[key]

    api_key = _next_tmap_key()
    if not api_key:
        print("  [경고] T map API 키 없음 — .env 설정 확인")
        return [], None

    url     = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
    headers = {"appKey": api_key, "Content-Type": "application/json"}
    body    = {
        "startX": str(lon1), "startY": str(lat1),   # T map: X=경도, Y=위도
        "endX":   str(lon2), "endY":   str(lat2),
        "startName": "출발", "endName": "도착",
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "searchOption": "0",
    }
    try:
        resp     = requests.post(url, headers=headers, json=body, timeout=10)
        features = resp.json().get("features", [])
        path, total_m = [], 0
        for f in features:
            geom  = f.get("geometry", {})
            props = f.get("properties", {})
            if geom.get("type") == "LineString":
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
# 8. 분석 준비
# ─────────────────────────────────────────────────────────────
def prepare(stops, rail_gdf):
    print("[준비] STRtree + KDTree 구축...")
    rail_geoms   = list(rail_gdf.geometry)
    rail_strtree = STRtree(rail_geoms)
    stops_arr    = np.array([[s["x"], s["y"]] for s in stops])
    stops_tree   = KDTree(stops_arr)
    print(f"  버스정류장 {len(stops)}개 · 철도 도형 {len(rail_geoms)}개")
    return stops_arr, stops_tree, rail_strtree, rail_geoms


# ─────────────────────────────────────────────────────────────
# 9. 유효 쌍 수집 (인구 필터 적용)
# ─────────────────────────────────────────────────────────────
def _collect_valid_pairs(stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf,
                         pop_scores=None, pop_threshold=0.0):
    """
    Phase 1: API 없이 유효 OD쌍 후보 수집.

    pop_scores가 주어지면 pop_threshold 미만 구간 건너뜀.
    → 인구 밀집 구간에만 OD쌍 생성
    """
    n_stops         = len(stops)
    candidate_pairs = []
    skipped_pop     = 0
    skipped_cross   = 0

    for pt, nx_, ny_, rname in _iter_rail_sample_points(rail_gdf):
        # 인구 압력 필터
        if pop_scores is not None:
            score = pop_scores.get((round(pt.x, 1), round(pt.y, 1)), 0.0)
            if score < pop_threshold:
                skipped_pop += 1
                continue

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
                sl, sr   = stops[li], stops[ri]
                straight = float(np.linalg.norm([sl["x"] - sr["x"], sl["y"] - sr["y"]]))
                if straight < MIN_OD_DIST_M or straight > MAX_OD_DIST_M:
                    continue
                line_ab    = LineString([(sl["x"], sl["y"]), (sr["x"], sr["y"])])
                candidates = rail_strtree.query(line_ab)
                crosses    = any(
                    line_ab.crosses(rail_geoms[c]) or line_ab.intersects(rail_geoms[c])
                    for c in candidates
                )
                if not crosses:
                    skipped_cross += 1
                    continue
                candidate_pairs.append((li, ri, straight, pt.x, pt.y, rname))

    print(f"  후보 쌍: {len(candidate_pairs)}개 "
          f"(인구필터 제외: {skipped_pop}, 교차 미통과: {skipped_cross})")
    return candidate_pairs


# ─────────────────────────────────────────────────────────────
# 10. OD쌍 우회비율 계산 (2단계)
# ─────────────────────────────────────────────────────────────
def compute_od_detour(stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf,
                      pop_scores=None, manual_anchors=None):
    """
    인구 우선순위 + 수동 앵커 OD쌍 기반 우회비율 계산.

    Phase 1a: 자동 쌍 수집 (인구 상위 구간만)
    Phase 1b: 수동 앵커 쌍 추가 (인구 필터 우회)
    Phase 2:  고유 쌍 300개 제한 → T map API
    Phase 3:  구간별 결과 집계
    """
    print("[계산] OD쌍 우회비율 계산 시작...")

    # ── Phase 1a: 자동 쌍 (인구 필터) ──────────────────────────
    pop_threshold = 0.0
    if pop_scores:
        scores_arr    = np.array(list(pop_scores.values()))
        pop_threshold = float(np.percentile(scores_arr, POP_PERCENTILE_CUTOFF))
        print(f"  인구 임계값 (p{POP_PERCENTILE_CUTOFF}): {pop_threshold:.2f} "
              f"(상위 {100-POP_PERCENTILE_CUTOFF}% 구간만)")

    candidate_pairs = _collect_valid_pairs(
        stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail_gdf,
        pop_scores=pop_scores, pop_threshold=pop_threshold,
    )

    # ── Phase 1b: 수동 앵커 쌍 (항상 포함) ─────────────────────
    if manual_anchors:
        n_before = len(candidate_pairs)
        for anchor in manual_anchors:
            anchor_pairs = _pairs_from_anchor(
                anchor, stops, stops_arr, stops_tree,
                rail_strtree, rail_geoms, rail_gdf
            )
            candidate_pairs.extend(anchor_pairs)
        print(f"  수동 앵커 추가: {len(candidate_pairs) - n_before}쌍")

    if not candidate_pairs:
        print("  유효 쌍 없음")
        return []

    # ── Phase 2: 고유 쌍 추출 + MAX_OD_PAIRS 제한 ─────────────
    unique_pairs = {}
    for li, ri, straight, *_ in candidate_pairs:
        key = (li, ri)
        if key not in unique_pairs:
            unique_pairs[key] = straight

    print(f"  고유 OD쌍: {len(unique_pairs)}개 / 한도: {MAX_OD_PAIRS}개")

    if len(unique_pairs) > MAX_OD_PAIRS:
        rng      = np.random.RandomState(42)
        all_keys = list(unique_pairs.keys())
        chosen   = rng.choice(len(all_keys), MAX_OD_PAIRS, replace=False)
        unique_pairs = {all_keys[i]: unique_pairs[all_keys[i]] for i in chosen}
        print(f"  → {MAX_OD_PAIRS}개 샘플링")

    selected_set = set(unique_pairs.keys())

    # ── T map API 호출 ──────────────────────────────────────────
    _tmap_cache_load()
    api_calls, cache_hits, api_fail = 0, 0, 0
    api_results = {}

    print(f"  T map API 호출 (최대 {len(selected_set)}건, 키 {len(_TMAP_KEYS)}개)...")
    for li, ri in selected_set:
        sl, sr    = stops[li], stops[ri]
        cache_key = _tmap_cache_key(sl["lat"], sl["lon"], sr["lat"], sr["lon"])
        if cache_key in _tmap_cache:
            cache_hits += 1
        else:
            api_calls += 1
            time.sleep(TMAP_RATE_LIMIT_S)

        path_wgs84, walk_m = tmap_walk_route(sl["lat"], sl["lon"], sr["lat"], sr["lon"])

        if walk_m is None or walk_m <= 0:
            api_fail += 1
            continue
        api_results[(li, ri)] = {"walk_m": walk_m, "path_wgs84": path_wgs84}

    if api_calls > 0:
        _tmap_cache_save()
    print(f"  신규 {api_calls}건 · 캐시 {cache_hits}건 · 실패 {api_fail}건")

    # ── Phase 3: 구간별 집계 ────────────────────────────────────
    seg_map   = defaultdict(list)
    pt_coords = {}

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
            "ratio": round(ratio, 3),
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
        pt_coords[seg_key] = (pt_x, pt_y)

    results = []
    for seg_key, entries in seg_map.items():
        pt_x, pt_y = pt_coords[seg_key]
        _, _, rname = seg_key
        ratios   = [e["ratio"]   for e in entries]
        od_pairs = [e["od_pair"] for e in entries]
        results.append({
            "x": pt_x, "y": pt_y,
            "ratio":    round(sum(ratios) / len(ratios), 3),
            "n_pairs":  len(ratios),
            "od_pairs": od_pairs,
            "name":     rname,
        })

    print(f"  완료: {len(results)}개 구간 포인트")
    if results:
        rv = [r["ratio"] for r in results]
        print(f"  우회비율 — 중앙: {np.median(rv):.2f} / 최대: {max(rv):.2f}")
    return results


# ─────────────────────────────────────────────────────────────
# 11. 시각화
# ─────────────────────────────────────────────────────────────
def make_maps(results, rail_gdf, depots_gdf=None):
    print("[시각화] 지도 렌더링...")
    if not results:
        print("  결과 없음")
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

    # 차량기지 레이어 (오렌지 반투명)
    if depots_gdf is not None and len(depots_gdf) > 0:
        depots_gdf.plot(ax=ax, facecolor="#ff8c00", edgecolor="#ff6600",
                        alpha=0.45, linewidth=1.5, zorder=3)

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
        lc   = LineCollection(segs, cmap=cmap, norm=norm, linewidth=6, zorder=4, alpha=0.92)
        lc.set_array(sc_r)
        ax.add_collection(lc)

    sc   = ax.scatter(xs, ys, c=ratios, cmap=cmap, norm=norm, s=25, alpha=0.5, zorder=5, linewidths=0)
    cbar = plt.colorbar(sc, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label(f"우회비율 (1.0=단절없음 / {RATIO_CAP:.0f}.0배)",
                   color="white", fontsize=10)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=9)
    cbar.outline.set_edgecolor("#30363d")

    ax.set_title("끊어진 서울 — 지상철도 보행 단절 지도 (인구 우선순위 OD쌍 + T map)",
                 color="white", fontsize=16, fontweight="bold", pad=15, loc="left")
    ax.text(0.01, 0.97,
            f"인구밀도 상위 {100-POP_PERCENTILE_CUTOFF}% 구간 + 수동 앵커 | T map 보행자 API\n"
            "오렌지 = 차량기지 (depot/yard) | 진한 빨강 = 단절 심각",
            transform=ax.transAxes, color="#8b949e", fontsize=9, va="top")
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout(pad=0.5)
    png_path = OUT_DIR / "detour_od_map_v3.png"
    plt.savefig(png_path, dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  PNG: {png_path}")

    html_path = _make_folium(results, rail_gdf, depots_gdf)
    print(f"  HTML: {html_path}")


def _make_folium(results, rail_gdf, depots_gdf=None):
    m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="CartoDB dark_matter")
    folium.TileLayer("OpenStreetMap", name="OSM 지도").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="위성사진",
    ).add_to(m)

    # 철도 선형
    for _, row in rail_gdf.to_crs(4326).iterrows():
        geom = row.geometry
        for line in (list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]):
            folium.PolyLine([(c[1], c[0]) for c in line.coords],
                            color="#fff", weight=2, opacity=0.2).add_to(m)

    # 차량기지 레이어
    if depots_gdf is not None and len(depots_gdf) > 0:
        depot_fg = folium.FeatureGroup(name="차량기지 (Depot/Yard)", show=True)
        for _, dep in depots_gdf.to_crs(4326).iterrows():
            geom = dep.geometry
            polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
            for poly in polys:
                coords = [[c[1], c[0]] for c in poly.exterior.coords]
                area_km2 = dep.get("area_m2", 0) / 1e6
                pop_v    = dep.get("nearby_pop", 0)
                dname    = dep.get("name", "미상 차량기지")
                folium.Polygon(
                    locations=coords,
                    color="#ff6600", fill=True,
                    fill_color="#ff8c00", fill_opacity=0.4,
                    weight=2, opacity=0.8,
                ).add_child(folium.Popup(
                    f"<div style='font-family:-apple-system,sans-serif;padding:4px'>"
                    f"<b style='font-size:14px'>🚉 {dname}</b><br>"
                    f"<span style='color:#666'>면적: {area_km2:.3f} km²</span><br>"
                    f"<span style='color:#666'>주변 밀도지수 (500m): {pop_v:.1f}</span><br>"
                    f"<span style='color:#999;font-size:11px'>2040 서울플랜 지하화 대상</span>"
                    f"</div>",
                    max_width=220,
                )).add_to(depot_fg)
        depot_fg.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    # OD쌍 마커 데이터
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
        우회비율 필터
      </div>
      <div style="margin-bottom:6px;display:flex;align-items:baseline;gap:6px">
        <span style="color:#8b949e">최소</span>
        <span id="threshold-display"
              style="color:#fd8d3c;font-weight:700;font-size:22px;line-height:1">1.0</span>
        <span style="color:#8b949e">배 이상만</span>
      </div>
      <input type="range" id="ratio-slider" min="1.0" max="8.0" step="0.5" value="1.0"
             style="width:100%;accent-color:#fd8d3c;cursor:pointer;margin:4px 0 2px">
      <div style="display:flex;justify-content:space-between;font-size:11px;
                  color:#444c56;margin-bottom:10px">
        <span>1.0배</span><span>8.0배</span>
      </div>
      <div style="padding-top:10px;border-top:1px solid #21262d;
                  color:#8b949e;font-size:12px" id="marker-count">로딩 중...</div>
      <div style="margin-top:6px;color:#444c56;font-size:11px">
        ● 점 클릭 → 최악 OD쌍 경로<br>지도 빈 곳 → 경로 숨김
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
    L.polyline([w.left_wgs84, w.right_wgs84], {{
      color:'#ffffff', weight:2, opacity:0.75, dashArray:'8 5'
    }}).bindTooltip('직선거리 ' + w.straight_m + 'm').addTo(routeLayer);
    if (w.path_wgs84 && w.path_wgs84.length > 1) {{
      L.polyline(w.path_wgs84, {{
        color:col, weight:5, opacity:0.92
      }}).bindTooltip('T map 실제 보행 ' + w.walk_m + 'm').addTo(routeLayer);
    }}
    L.circleMarker(w.left_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#00e676', fillOpacity:1.0
    }}).bindTooltip('출발: ' + (w.left_gu || '?')).addTo(routeLayer);
    L.circleMarker(w.right_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#ff5252', fillOpacity:1.0
    }}).bindTooltip('도착: ' + (w.right_gu || '?')).addTo(routeLayer);
    L.popup({{ maxWidth:300 }})
      .setLatLng(d.latlng)
      .setContent(
        '<div style="font-family:-apple-system,sans-serif;padding:4px 6px;min-width:240px">' +
        '<div style="font-size:15px;font-weight:700;margin-bottom:4px">' + d.name + '</div>' +
        '<div style="color:#555;font-size:11px;margin-bottom:8px">' +
          '🚌 ' + (w.left_gu||'출발') + ' → ' + (w.right_gu||'도착') + '</div>' +
        '<hr style="margin:6px 0;border-color:#eee">' +
        '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
        '<tr><td style="color:#888;padding:2px 0">분석 OD쌍</td>' +
            '<td style="text-align:right;font-weight:600">' + d.n_pairs + '개</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">📏 직선거리</td>' +
            '<td style="text-align:right;font-weight:600">' + w.straight_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">🚶 T map 보행</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' +
            w.walk_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">➕ 추가 거리</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' +
            (w.walk_m - w.straight_m) + 'm 더</td></tr>' +
        '</table>' +
        '<div style="margin-top:8px;padding:6px;background:#f8f8f8;border-radius:4px;' +
             'text-align:center">' +
        '<span style="font-size:22px;font-weight:700;color:' + col + '">' +
            d.ratio.toFixed(2) + '배</span>' +
        '<span style="color:#888;font-size:12px"> 우회비율</span>' +
        '</div>' +
        '<div style="margin-top:6px;font-size:11px;color:#aaa">' +
        '● 초록=출발 · 빨강=도착 · 점선=직선 · 실선=T map경로</div>' +
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
    if (el) el.textContent = count + '개 구간 (전체 ' + markerData.length + '개)';
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
    html_path = OUT_DIR / "detour_od_interactive_v3.html"
    m.save(html_path)
    return html_path


# ─────────────────────────────────────────────────────────────
# 실행 진입점
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. 기본 데이터
    rail  = load_rail()
    stops = load_bus_stops(rail)
    stops_arr, stops_tree, rail_strtree, rail_geoms = prepare(stops, rail)

    # 2. 인구 압력 (집계구 면적 역수 기반)
    cent_xy, pop_wts, cent_tree = load_census_centroids()
    pop_scores = compute_pop_pressure(rail, cent_xy, pop_wts, cent_tree)

    # 3. 수동 앵커 포인트 (data/manual_od_points.json)
    manual_anchors = load_manual_anchors()

    # 4. 차량기지
    depots = load_depots(cent_xy, pop_wts, cent_tree)

    # 5. OD쌍 우회비율 계산
    results_pkl = CACHE_DIR / "detour_od_results_ver3.pkl"
    if results_pkl.exists():
        print("[CACHE] detour_od_results_ver3.pkl 로드")
        with open(results_pkl, "rb") as f:
            results = pickle.load(f)
    else:
        results = compute_od_detour(
            stops, stops_arr, stops_tree, rail_strtree, rail_geoms, rail,
            pop_scores=pop_scores,
            manual_anchors=manual_anchors,
        )
        with open(results_pkl, "wb") as f:
            pickle.dump(results, f)
        print(f"  detour_od_results_ver3.pkl 저장")

    # 6. 지도 출력
    make_maps(results, rail, depots_gdf=depots)
