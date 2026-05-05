"""
17_slope_dijkstra.py
경사도 적용 다익스트라 캐시 생성기

16_climate_shelter_dashboard.py와 방법론 완전 동일.
유일한 변경: weight="length"(미터) → "norm_time" = length / tobler(grade_abs).

━━━ 핵심 설계 원리 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  travel_time(edge, speed) = length / (speed × tobler(grade))
                           = [length / tobler(grade)] / speed
                              ↑ speed 무관 부분            ↑ speed

  → 최적 경로(어느 길로 갈지)는 속도가 달라도 동일.
  → 16과 마찬가지로 1회 Dijkstra로 4속도 × 3시간 전체 커버 가능.

  norm_time = length / tobler(grade_abs)  (speed=1 m/s 기준 정규화 시간)
  필터 임계값 = s["mps"] × t × 60         (16의 threshold 공식과 완전 동일)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tobler hiking function:
  tobler_ratio(g) = exp(-3.5 × (g + 0.05)) / exp(-3.5 × 0.05)
  g = grade_abs (방향 무관 절댓값, 0.5 캡 적용)
  g=0.00 → ratio=1.00  g=0.10 → ratio≈0.79  g=0.20 → ratio≈0.53

DEM 준비 (최초 1회):
  pip install elevation
  python -c "import elevation; elevation.clip(
      bounds=(126.7, 37.4, 127.2, 37.7),
      output='/Users/mtsaurus/Projects/seoul-2026-bigdata'
             '/senior_access/new-workspace/cache/dem_seoul.tif')"
  python -c "import elevation; elevation.clean()"

출력 (cache/260428/):
  17_reach_slope.json      ← 15_reach.json과 동일 구조 (heat_m/cold_m = null)
  17_hulls_slope.json      ← 15_hulls.json과 동일 구조
  17_reach_slope_gu.json
  17_hulls_slope_gu.json
"""

import json, logging, math, time
import multiprocessing
multiprocessing.set_start_method('fork', force=True)
from pathlib import Path
import numpy as np
import geopandas as gpd
import pandas as pd
import networkx as nx
import osmnx as ox
from shapely.geometry import MultiPoint
from pyproj import Transformer

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

# ── 경로 설정 ────────────────────────────────────────────────────────────────────
BASE      = Path("/Users/mtsaurus/Projects/seoul-2026-bigdata")
WS        = BASE / "senior_access/new-workspace"
GRAPH     = WS / "cache/seoul_walk_full.graphml"
DEM_PATH  = WS / "cache/dem_seoul.tif"
DONG_SHP  = BASE / "senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
DONG_POP  = BASE / "senior_access/data/interim/dong_pop.csv"
HEAT_JSON = BASE / "노인친화아이디어/data/7_서울시 무더위쉼터.json"
COLD_JSON = BASE / "노인친화아이디어/data/8_서울시 한파쉼터.json"
LINK_XLS  = BASE / "senior_access/data/1-3 행정안전부 코드와 국가데이터처 코드 연계표.xlsx"

CACHE_DIR      = WS / "cache/260428"
CACHE_DIR.mkdir(exist_ok=True)
# ver3: 캐시 파일명 분리 (잘못된 ver2 캐시 재사용 방지)
REACH_CACHE    = CACHE_DIR / "17v3_reach_slope.json"
HULL_CACHE     = CACHE_DIR / "17v3_hulls_slope.json"
REACH_GU_CACHE = CACHE_DIR / "17v3_reach_slope_gu.json"
HULL_GU_CACHE  = CACHE_DIR / "17v3_hulls_slope_gu.json"

# ── 파라미터 (16과 동일) ──────────────────────────────────────────────────────────
SPEEDS = [
    {"id": "g0", "mps": 1.28, "label": "일반인",           "color": "#1D9E75"},
    {"id": "g1", "mps": 1.12, "label": "일반 노인",         "color": "#185FA5"},
    {"id": "g2", "mps": 0.88, "label": "보행보조 노인",     "color": "#D85A30"},
    {"id": "g3", "mps": 0.70, "label": "보행보조 하위 15%", "color": "#8B1A1A"},
]
TIMES   = [15, 30, 45]
# cutoff: g0 기준 최대 도달 거리와 동일 수치 (norm_time 단위, meters / 1 m/s = m)
MAX_DIST = 1.28 * 45 * 60   # 3,456 — 16과 동일한 cutoff 값

SEOUL_GU = {
    "11010": "종로구", "11020": "중구",    "11030": "용산구", "11040": "성동구",
    "11050": "광진구", "11060": "동대문구","11070": "중랑구", "11080": "성북구",
    "11090": "강북구", "11100": "도봉구",  "11110": "노원구", "11120": "은평구",
    "11130": "서대문구","11140": "마포구", "11150": "양천구", "11160": "강서구",
    "11170": "구로구", "11180": "금천구",  "11190": "영등포구","11200": "동작구",
    "11210": "관악구", "11220": "서초구",  "11230": "강남구", "11240": "송파구",
    "11250": "강동구",
}

to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

# ── Tobler hiking function ────────────────────────────────────────────────────
_TOBLER_NORM = math.exp(-3.5 * 0.05)   # grade=0 기준 정규화 상수

def tobler_ratio(grade_abs: float) -> float:
    """
    절댓값 경사도 → 보행속도 비율 (Tobler hiking function).
    grade_abs=0.0 → 1.00, grade_abs=0.10 → 0.79, grade_abs=0.20 → 0.53.
    최대 0.5 캡 (서울 보행로 비현실 경사 방지).
    """
    g = min(grade_abs, 0.5)
    return math.exp(-3.5 * (g + 0.05)) / _TOBLER_NORM


# ── convex_hull_coords (16과 동일) ────────────────────────────────────────────
def convex_hull_coords(dx_arr, dy_arr, fallback_r, simplify_tol=30):
    """OSM 도달 노드 좌표 배열 → convex hull vertices (centroid 기준 상대 미터)"""
    if dx_arr.shape[0] >= 3:
        pts = list(zip(dx_arr.tolist(), dy_arr.tolist()))
        try:
            hull = MultiPoint(pts).convex_hull
            if hull.geom_type == "Polygon":
                simplified = hull.simplify(simplify_tol)
                ext = simplified.exterior if simplified.geom_type == "Polygon" else hull.exterior
                return [[round(x / 10) * 10, round(y / 10) * 10] for x, y in ext.coords]
        except Exception:
            pass
    n = 24
    return [
        [round(fallback_r * math.cos(2 * math.pi * i / n) / 10) * 10,
         round(fallback_r * math.sin(2 * math.pi * i / n) / 10) * 10]
        for i in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 1. OSM 그래프 로드 + DEM 표고 + 경사도 + norm_time 엣지 속성 추가
# ══════════════════════════════════════════════════════════════════════════════
log.info("그래프 로드 중 (188 MB)...")
G = ox.load_graphml(GRAPH)
log.info(f"  노드 {len(G.nodes):,}개  엣지 {len(G.edges):,}개")

if not DEM_PATH.exists():
    raise FileNotFoundError(
        f"\nDEM 파일을 찾을 수 없습니다: {DEM_PATH}\n\n"
        "다운로드 (1회):\n"
        "  pip install elevation\n"
        f"  python -c \"import elevation; elevation.clip("
        f"bounds=(126.7, 37.4, 127.2, 37.7), output='{DEM_PATH}')\""
    )

log.info(f"노드 표고 추가 (DEM: {DEM_PATH.name}, SRTM ~30m)...")
G = ox.elevation.add_node_elevations_raster(G, str(DEM_PATH), cpus=1)

log.info("엣지별 경사도 계산...")
G = ox.elevation.add_edge_grades(G)

log.info("엣지별 norm_time 계산 (= length / tobler(grade_abs))...")
for u, v, k, data in G.edges(keys=True, data=True):
    g_abs  = data.get("grade_abs", abs(data.get("grade", 0.0)))
    # grade_abs가 음수이거나 비정상 값이면 0으로 보정
    if not isinstance(g_abs, (int, float)) or g_abs < 0 or math.isnan(g_abs):
        g_abs = 0.0
    ratio  = tobler_ratio(g_abs)
    length = max(data.get("length", 1.0), 0.1)
    # norm_time: speed=1 m/s 기준 정규화 이동시간
    # → 속도별 실제 이동시간 = norm_time / speed_mps
    # → 필터 임계값 = speed_mps × t × 60  (16의 공식과 동일, cutoff도 동일)
    # norm_time >= length 보장 (경사 적용 후 비용이 평지보다 작아지면 안됨)
    data["norm_time"] = max(length / ratio, length)

G_ud = ox.convert.to_undirected(G)
log.info(f"  무방향 그래프: 노드 {G_ud.number_of_nodes():,}개  엣지 {G_ud.number_of_edges():,}개")

# undirected 변환 후 norm_time 누락 엣지 보정
# networkx는 weight 속성 없는 엣지를 1로 처리 → 비정상 도달 범위 유발
missing_nt = 0
for u, v, data in G_ud.edges(data=True):
    if "norm_time" not in data:
        length = max(data.get("length", 1.0), 0.1)
        data["norm_time"] = length  # 경사 없다고 가정하고 평지 기준 적용
        missing_nt += 1
if missing_nt:
    log.warning(f"  norm_time 누락 엣지 {missing_nt}개 → 평지 기준으로 보정")
else:
    log.info("  모든 엣지에 norm_time 정상 적용")


# ══════════════════════════════════════════════════════════════════════════════
# 2. 행정동 shapefile + 인구 (16과 동일)
# ══════════════════════════════════════════════════════════════════════════════
log.info("행정동 shapefile 로드...")
gdf = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf.columns = [c.lower() for c in gdf.columns]
gdf = gdf[gdf["adm_cd"].astype(str).str.startswith("11")].copy().reset_index(drop=True)
gdf["adm_cd"]  = gdf["adm_cd"].astype(str)
gdf["gu_code"] = gdf["adm_cd"].str[:5]
gdf["gu_name"] = gdf["gu_code"].map(SEOUL_GU).fillna("서울")
gdf["cx"] = gdf.geometry.centroid.x
gdf["cy"] = gdf.geometry.centroid.y

link_df = pd.read_excel(LINK_XLS, sheet_name="연계표", header=0).iloc[1:].copy()
link_seoul = link_df[
    (link_df["레벨"] == "읍면동") &
    (link_df["행정안전부 코드"].astype(str).str.startswith("11")) &
    (link_df["신코드:8자리"].notna())
].copy()
link_seoul["bnd_8"]   = link_seoul["신코드:8자리"].apply(lambda x: str(int(x)))
link_seoul["kosis_8"] = link_seoul["행정안전부 코드"].astype(str).str[:8]
BND_TO_KOSIS8 = dict(zip(link_seoul["bnd_8"], link_seoul["kosis_8"]))

pop_df = pd.read_csv(DONG_POP)
pop_df["kosis_8"]       = pop_df["dong_code_lp"].astype(str).str[:8]
pop_df["gu_code_kosis"] = pop_df["kosis_8"].str[:5]

gdf["kosis_8"] = gdf["adm_cd"].map(BND_TO_KOSIS8)
gdf = gdf.merge(pop_df[["kosis_8", "pop_65plus", "pop_total"]], on="kosis_8", how="left")

gu_totals = pop_df.groupby("gu_code_kosis")[["pop_65plus", "pop_total"]].sum()
BND_GU_TO_KOSIS_GU = {row["bnd_8"][:5]: row["kosis_8"][:5] for _, row in link_seoul.iterrows()}
for bnd_gu, kosis_gu in BND_GU_TO_KOSIS_GU.items():
    if kosis_gu not in gu_totals.index:
        continue
    gu_row   = gu_totals.loc[kosis_gu]
    mask_all = gdf["gu_code"] == bnd_gu
    mask_unm = mask_all & gdf["pop_65plus"].isna()
    n_unmat  = mask_unm.sum()
    if n_unmat == 0:
        continue
    matched_65  = gdf.loc[mask_all & gdf["pop_65plus"].notna(), "pop_65plus"].sum()
    matched_tot = gdf.loc[mask_all & gdf["pop_total"].notna(),  "pop_total"].sum()
    gdf.loc[mask_unm, "pop_65plus"] = max(gu_row["pop_65plus"] - matched_65, 0.0) / n_unmat
    gdf.loc[mask_unm, "pop_total"]  = max(gu_row["pop_total"]  - matched_tot, 0.0) / n_unmat

gdf["pop_65plus"] = gdf["pop_65plus"].fillna(0).round(0).astype(int)
gdf["pop_total"]  = gdf["pop_total"].fillna(0).round(0).astype(int)
log.info(f"  행정동: {len(gdf)}개  65+ 합계: {gdf['pop_65plus'].sum():,}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. 동 centroid → OSM 노드 스냅
# ══════════════════════════════════════════════════════════════════════════════
log.info("동 중심점 → OSM 노드 스냅...")
c_nodes = ox.nearest_nodes(G_ud, gdf["cx"].tolist(), gdf["cy"].tolist())
gdf["osm_node"] = c_nodes


# ══════════════════════════════════════════════════════════════════════════════
# 4. 쉼터 데이터 로드 + OSM 스냅 (16과 동일)
# ══════════════════════════════════════════════════════════════════════════════
log.info("쉼터 데이터 로드...")
with open(HEAT_JSON) as f:
    heat_raw = json.load(f)["DATA"]
HEAT_LOC = []
for s in heat_raw:
    try:
        lat, lng = float(s["lat"]), float(s["lon"])
        if 37.0 <= lat <= 38.5 and 126.0 <= lng <= 128.0:
            HEAT_LOC.append({"lat": round(lat, 6), "lng": round(lng, 6)})
    except (TypeError, ValueError, KeyError):
        pass

with open(COLD_JSON) as f:
    cold_raw = json.load(f)["DATA"]
COLD_LOC = []
for s in cold_raw:
    try:
        lat, lng = float(s["lat"]), float(s["lot"])
        if 37.0 <= lat <= 38.5 and 126.0 <= lng <= 128.0:
            COLD_LOC.append({"lat": round(lat, 6), "lng": round(lng, 6)})
    except (TypeError, ValueError, KeyError):
        pass

log.info(f"  더위쉼터: {len(HEAT_LOC)}개  한파쉼터: {len(COLD_LOC)}개")
heat_nodes     = ox.nearest_nodes(G_ud, [s["lng"] for s in HEAT_LOC], [s["lat"] for s in HEAT_LOC])
cold_nodes     = ox.nearest_nodes(G_ud, [s["lng"] for s in COLD_LOC], [s["lat"] for s in COLD_LOC])
heat_node_list = list(heat_nodes)
cold_node_list = list(cold_nodes)
log.info("  스냅 완료")


# ══════════════════════════════════════════════════════════════════════════════
# 5. 경사도 적용 Dijkstra — 동 단위 (캐시)
#    16과 동일: 동당 1회 Dijkstra, 같은 cutoff, 같은 threshold 공식
#    변경점: weight="length" → weight="norm_time"
# ══════════════════════════════════════════════════════════════════════════════
if REACH_CACHE.exists() and HULL_CACHE.exists():
    log.info(f"캐시 로드: {REACH_CACHE.name}, {HULL_CACHE.name}")
    with open(REACH_CACHE) as f:
        reach_dong = json.load(f)
    with open(HULL_CACHE) as f:
        hulls_dong = json.load(f)
    log.info(f"  로드 완료: {len(reach_dong)}개 동")
else:
    log.info(f"경사도 Dijkstra 계산 (426회, cutoff={MAX_DIST:.0f})...")
    reach_dong = {}
    hulls_dong = {}
    t0 = time.time()

    for i, (_, row) in enumerate(gdf.iterrows()):
        dc = row["adm_cd"]
        src = int(row["osm_node"])
        cx_4326, cy_4326 = float(row["cx"]), float(row["cy"])
        cx5, cy5 = to_5179.transform(cx_4326, cy_4326)

        # ── 경사도 적용 Dijkstra (1회) ─────────────────────────────────────
        lengths = nx.single_source_dijkstra_path_length(
            G_ud, src, cutoff=MAX_DIST, weight="norm_time"
        )

        # 쉼터 norm_time 배열
        heat_dists = np.array([lengths.get(n, 999999.0) for n in heat_node_list])
        cold_dists = np.array([lengths.get(n, 999999.0) for n in cold_node_list])
        nearest_heat = float(heat_dists.min())
        nearest_cold = float(cold_dists.min())

        # 도달 노드 좌표 — hull 계산용
        reachable = list(lengths.keys())
        if reachable:
            nx4  = np.array([G_ud.nodes[n].get("x", cx_4326) for n in reachable])
            ny4  = np.array([G_ud.nodes[n].get("y", cy_4326) for n in reachable])
            nx5, ny5 = to_5179.transform(nx4, ny4)
            nd   = np.array([lengths[n] for n in reachable])
            ddx  = nx5 - cx5
            ddy  = ny5 - cy5
        else:
            nd = ddx = ddy = np.array([])

        reach_dong[dc] = {s["id"]: {} for s in SPEEDS}
        hulls_dong[dc] = {str(t): {} for t in TIMES}

        # ── 16과 동일한 이중 루프, 동일한 threshold 공식 ──────────────────
        for s in SPEEDS:
            sid = s["id"]
            for t in TIMES:
                thresh = s["mps"] * t * 60   # 16의 공식과 동일

                heat_cnt = int((heat_dists <= thresh).sum())
                cold_cnt = int((cold_dists <= thresh).sum())
                reach_dong[dc][sid][str(t)] = {
                    "heat":   heat_cnt,
                    "cold":   cold_cnt,
                    "heat_m": int(nearest_heat) if nearest_heat < 90000 else None,
                    "cold_m": int(nearest_cold) if nearest_cold < 90000 else None,
                }

                if nd.size > 0:
                    mask   = nd <= thresh
                    coords = convex_hull_coords(ddx[mask], ddy[mask], fallback_r=thresh)
                else:
                    coords = convex_hull_coords(np.array([]), np.array([]), fallback_r=thresh)
                hulls_dong[dc][str(t)][sid] = coords

        if (i + 1) % 50 == 0:
            el  = time.time() - t0
            eta = el / (i + 1) * (len(gdf) - i - 1)
            log.info(f"  {i+1}/{len(gdf)}  [{el:.0f}s 경과, 잔여 ~{eta:.0f}s]")

    log.info("캐시 저장 중...")
    with open(REACH_CACHE, "w", encoding="utf-8") as f:
        json.dump(reach_dong, f, ensure_ascii=False, separators=(",", ":"))
    with open(HULL_CACHE, "w", encoding="utf-8") as f:
        json.dump(hulls_dong, f, ensure_ascii=False, separators=(",", ":"))
    log.info(f"  reach: {REACH_CACHE.stat().st_size // 1024} KB")
    log.info(f"  hull:  {HULL_CACHE.stat().st_size  // 1024} KB")


# ══════════════════════════════════════════════════════════════════════════════
# 6. GU 단위 집계 (16과 동일 로직)
# ══════════════════════════════════════════════════════════════════════════════
log.info("구 단위 집계...")
gu_dongs = {}
for _, row in gdf.iterrows():
    gu_dongs.setdefault(row["gu_code"], []).append(row["adm_cd"])

reach_gu = {}
gu_pop   = {}

for gc, dongs in gu_dongs.items():
    reach_gu[gc] = {s["id"]: {} for s in SPEEDS}
    mask_gu = gdf["gu_code"] == gc
    gu_pop[gc] = {
        "p65":   int(gdf.loc[mask_gu, "pop_65plus"].sum()),
        "total": int(gdf.loc[mask_gu, "pop_total"].sum()),
    }
    for s in SPEEDS:
        sid = s["id"]
        for t in TIMES:
            ts = str(t)
            heat_v = [reach_dong[dc][sid][ts]["heat"]   for dc in dongs if dc in reach_dong]
            cold_v = [reach_dong[dc][sid][ts]["cold"]   for dc in dongs if dc in reach_dong]
            hm_v   = [reach_dong[dc][sid][ts]["heat_m"] for dc in dongs
                      if dc in reach_dong and reach_dong[dc][sid][ts]["heat_m"] is not None]
            cm_v   = [reach_dong[dc][sid][ts]["cold_m"] for dc in dongs
                      if dc in reach_dong and reach_dong[dc][sid][ts]["cold_m"] is not None]
            reach_gu[gc][sid][ts] = {
                "heat":   round(sum(heat_v) / len(heat_v), 1) if heat_v else 0,
                "cold":   round(sum(cold_v) / len(cold_v), 1) if cold_v else 0,
                "heat_m": int(sum(hm_v) / len(hm_v)) if hm_v else None,
                "cold_m": int(sum(cm_v) / len(cm_v)) if cm_v else None,
            }


# ══════════════════════════════════════════════════════════════════════════════
# 7. GU centroid hull — 경사도 적용 (25회 Dijkstra, 16의 7단계와 동일 구조)
# ══════════════════════════════════════════════════════════════════════════════
log.info("구 단위 Hull 계산 (경사도 적용, 25회 Dijkstra)...")
gdf_gu_diss = gdf.dissolve(by="gu_code", as_index=False)
gdf_gu_diss["geometry"] = gdf_gu_diss.geometry.simplify(0.0005)
gdf_gu_diss["cx"] = gdf_gu_diss.geometry.centroid.x
gdf_gu_diss["cy"] = gdf_gu_diss.geometry.centroid.y
gu_c_nodes = ox.nearest_nodes(
    G_ud, gdf_gu_diss["cx"].tolist(), gdf_gu_diss["cy"].tolist()
)

hulls_gu    = {}
gu_centroids = {}

for i, (_, row) in enumerate(gdf_gu_diss.iterrows()):
    gc = str(row["gu_code"])
    src = gu_c_nodes[i]
    cx_4326, cy_4326 = float(row["cx"]), float(row["cy"])
    cx5, cy5 = to_5179.transform(cx_4326, cy_4326)
    gu_centroids[gc] = {"lat": round(cy_4326, 6), "lng": round(cx_4326, 6)}

    lengths = nx.single_source_dijkstra_path_length(
        G_ud, src, cutoff=MAX_DIST, weight="norm_time"
    )
    hulls_gu[gc] = {str(t): {} for t in TIMES}

    if lengths:
        reachable = list(lengths.keys())
        nx4  = np.array([G_ud.nodes[n].get("x", cx_4326) for n in reachable])
        ny4  = np.array([G_ud.nodes[n].get("y", cy_4326) for n in reachable])
        nx5, ny5 = to_5179.transform(nx4, ny4)
        nd   = np.array([lengths[n] for n in reachable])
        ddx  = nx5 - cx5
        ddy  = ny5 - cy5
    else:
        nd = ddx = ddy = np.array([])

    for t in TIMES:
        for s in SPEEDS:
            thresh = s["mps"] * t * 60
            if nd.size > 0:
                mask   = nd <= thresh
                coords = convex_hull_coords(ddx[mask], ddy[mask], fallback_r=thresh)
            else:
                coords = convex_hull_coords(np.array([]), np.array([]), fallback_r=thresh)
            hulls_gu[gc][str(t)][s["id"]] = coords

log.info(f"  구 Hull 완료: {len(hulls_gu)}개 구")


# ══════════════════════════════════════════════════════════════════════════════
# 8. GU 캐시 저장
# ══════════════════════════════════════════════════════════════════════════════
log.info("구 단위 캐시 저장...")
with open(REACH_GU_CACHE, "w", encoding="utf-8") as f:
    json.dump(reach_gu, f, ensure_ascii=False, separators=(",", ":"))
with open(HULL_GU_CACHE, "w", encoding="utf-8") as f:
    json.dump(hulls_gu, f, ensure_ascii=False, separators=(",", ":"))
log.info(f"  reach_gu: {REACH_GU_CACHE.stat().st_size // 1024} KB")
log.info(f"  hull_gu:  {HULL_GU_CACHE.stat().st_size  // 1024} KB")

log.info("=" * 60)
log.info("✅ 17_slope_dijkstra.py 완료")
log.info(f"   {REACH_CACHE}")
log.info(f"   {HULL_CACHE}")
log.info(f"   {REACH_GU_CACHE}")
log.info(f"   {HULL_GU_CACHE}")
log.info("=" * 60)
log.info(
    "\n다음 단계: 18_slope_toggle_dashboard.py\n"
    "  flat (15_reach.json + 15_hulls.json) +\n"
    "  slope (17_reach_slope.json + 17_hulls_slope.json)\n"
    "  → 경사로 적용 여부 토글 HTML 생성"
)
