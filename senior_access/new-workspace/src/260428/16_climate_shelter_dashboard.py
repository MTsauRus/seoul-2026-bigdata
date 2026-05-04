"""
15_climate_shelter_dashboard.py
기후 파트 — 더위쉼터 · 한파쉼터 · 결빙위험구역 통합 대시보드
대재현(infra_dashboard_2) 양식 + OSM Convex Hull 보행가능권 모식도

파라미터 (지시서 기준):
  속도: 1.28 / 1.12 / 0.88 / 0.70 m/s
  시간: 15 / 30 / 45분
  거리 계산: OSM 보행 네트워크 + 다익스트라
  공간 단위: 행정동 426개 (동↔구 토글)
"""

import json, logging, math, time
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

# ── 경로 ────────────────────────────────────────────────────────────────────────
BASE        = Path("/Users/mtsaurus/Projects/seoul-2026-bigdata")
WS          = BASE / "senior_access/new-workspace"
CDN_DIR     = WS / "cache/cdn"
GRAPH       = WS / "cache/seoul_walk_full.graphml"
DONG_SHP    = BASE / "senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
DONG_POP    = BASE / "senior_access/data/interim/dong_pop.csv"
HEAT_JSON   = BASE / "노인친화아이디어/data/7_서울시 무더위쉼터.json"
COLD_JSON   = BASE / "노인친화아이디어/data/8_서울시 한파쉼터.json"
ICING_CACHE   = WS / "cache/260421/icing_v3.json"
CACHE_DIR     = WS / "cache/260428"
CACHE_DIR.mkdir(exist_ok=True)
REACH_CACHE   = CACHE_DIR / "15_reach.json"
HULL_CACHE    = CACHE_DIR / "15_hulls.json"
JISEOL_CACHE  = CACHE_DIR / "15_jiseol_boxes.json"
OUT_DIR     = WS / "outputs/260428"
OUT_DIR.mkdir(exist_ok=True)

# ── 파라미터 ─────────────────────────────────────────────────────────────────────
SPEEDS = [
    {"id": "g0", "mps": 1.28, "label": "일반인",           "color": "#1D9E75"},
    {"id": "g1", "mps": 1.12, "label": "일반 노인",         "color": "#185FA5"},
    {"id": "g2", "mps": 0.88, "label": "보행보조 노인",     "color": "#D85A30"},
    {"id": "g3", "mps": 0.70, "label": "보행보조 하위 15%", "color": "#8B1A1A"},
]
TIMES = [15, 30, 45]
MAX_DIST = 1.28 * 45 * 60  # 3,456 m (최대 탐색 반경)

SEOUL_GU = {
    "11010": "종로구", "11020": "중구", "11030": "용산구", "11040": "성동구",
    "11050": "광진구", "11060": "동대문구", "11070": "중랑구", "11080": "성북구",
    "11090": "강북구", "11100": "도봉구", "11110": "노원구", "11120": "은평구",
    "11130": "서대문구", "11140": "마포구", "11150": "양천구", "11160": "강서구",
    "11170": "구로구", "11180": "금천구", "11190": "영등포구", "11200": "동작구",
    "11210": "관악구", "11220": "서초구", "11230": "강남구", "11240": "송파구",
    "11250": "강동구",
}

to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def convex_hull_coords(dx_arr, dy_arr, fallback_r, simplify_tol=30):
    """OSM 도달 노드 좌표 배열 → convex hull polygon vertices (centroid 기준 상대 미터 좌표)"""
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
    # fallback: 원형 근사
    n = 24
    return [
        [round(fallback_r * math.cos(2 * math.pi * i / n) / 10) * 10,
         round(fallback_r * math.sin(2 * math.pi * i / n) / 10) * 10]
        for i in range(n)
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. OSM 그래프 로드
# ═══════════════════════════════════════════════════════════════════════════════
log.info("그래프 로드 중 (188 MB)...")
G = ox.load_graphml(GRAPH)
G_ud = ox.convert.to_undirected(G)
log.info(f"  노드 {G_ud.number_of_nodes():,}개  엣지 {G_ud.number_of_edges():,}개")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. 행정동 shapefile + 인구
# ═══════════════════════════════════════════════════════════════════════════════
log.info("행정동 shapefile 로드...")
gdf = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf.columns = [c.lower() for c in gdf.columns]
gdf = gdf[gdf["adm_cd"].astype(str).str.startswith("11")].copy().reset_index(drop=True)
gdf["adm_cd"] = gdf["adm_cd"].astype(str)
gdf["gu_code"] = gdf["adm_cd"].str[:5]
gdf["gu_name"] = gdf["gu_code"].map(SEOUL_GU).fillna("서울")
gdf["cx"] = gdf.geometry.centroid.x
gdf["cy"] = gdf.geometry.centroid.y
log.info(f"  서울 행정동: {len(gdf)}개")

# 인구 join — 행정안전부↔국가데이터처 연계표로 BND ADM_CD → KOSIS 8자리 코드 매핑
LINK_XLS = BASE / "senior_access/data/1-3 행정안전부 코드와 국가데이터처 코드 연계표.xlsx"
link_df = pd.read_excel(LINK_XLS, sheet_name="연계표", header=0).iloc[1:].copy()
link_seoul = link_df[
    (link_df["레벨"] == "읍면동") &
    (link_df["행정안전부 코드"].astype(str).str.startswith("11")) &
    (link_df["신코드:8자리"].notna())
].copy()
link_seoul["bnd_8"]    = link_seoul["신코드:8자리"].apply(lambda x: str(int(x)))
link_seoul["kosis_8"]  = link_seoul["행정안전부 코드"].astype(str).str[:8]
BND_TO_KOSIS8 = dict(zip(link_seoul["bnd_8"], link_seoul["kosis_8"]))

pop_df = pd.read_csv(DONG_POP)
pop_df["kosis_8"] = pop_df["dong_code_lp"].astype(str).str[:8]
pop_df["gu_code_kosis"] = pop_df["kosis_8"].str[:5]

gdf["kosis_8"] = gdf["adm_cd"].map(BND_TO_KOSIS8)
gdf = gdf.merge(pop_df[["kosis_8", "pop_65plus", "pop_total"]], on="kosis_8", how="left")

# 미매칭 동(10개): 구 단위 잔여 인구를 동수로 균등 배분
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
log.info(f"  인구 join: {(gdf['pop_65plus']>0).sum()}개 동 매칭, 65+ 합계 = {gdf['pop_65plus'].sum():,}")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. 동 centroid → OSM 노드 스냅
# ═══════════════════════════════════════════════════════════════════════════════
log.info("동 중심점 → OSM 노드 스냅...")
c_nodes = ox.nearest_nodes(G_ud, gdf["cx"].tolist(), gdf["cy"].tolist())
gdf["osm_node"] = c_nodes

# ═══════════════════════════════════════════════════════════════════════════════
# 4. 쉼터 데이터 로드 + 스냅
# ═══════════════════════════════════════════════════════════════════════════════
log.info("쉼터 데이터 로드...")

with open(HEAT_JSON) as f:
    heat_raw = json.load(f)["DATA"]
HEAT_LOC = []
for s in heat_raw:
    try:
        lat, lng = float(s["lat"]), float(s["lon"])
        if 37.0 <= lat <= 38.5 and 126.0 <= lng <= 128.0:
            HEAT_LOC.append({
                "name": s.get("r_area_nm", "더위쉼터"),
                "type": s.get("facility_type2", ""),
                "lat":  round(lat, 6),
                "lng":  round(lng, 6),
            })
    except (TypeError, ValueError, KeyError):
        pass

with open(COLD_JSON) as f:
    cold_raw = json.load(f)["DATA"]
COLD_LOC = []
for s in cold_raw:
    try:
        lat, lng = float(s["lat"]), float(s["lot"])
        if 37.0 <= lat <= 38.5 and 126.0 <= lng <= 128.0:
            COLD_LOC.append({
                "name": s.get("restarea_nm", "한파쉼터"),
                "type": s.get("facility_type2", ""),
                "lat":  round(lat, 6),
                "lng":  round(lng, 6),
            })
    except (TypeError, ValueError, KeyError):
        pass

log.info(f"  더위쉼터: {len(HEAT_LOC)}개  한파쉼터: {len(COLD_LOC)}개")

log.info("쉼터 → OSM 노드 스냅...")
heat_nodes = ox.nearest_nodes(G_ud, [s["lng"] for s in HEAT_LOC], [s["lat"] for s in HEAT_LOC])
cold_nodes = ox.nearest_nodes(G_ud, [s["lng"] for s in COLD_LOC], [s["lat"] for s in COLD_LOC])
heat_node_list = list(heat_nodes)
cold_node_list = list(cold_nodes)
log.info("  완료")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Forward Dijkstra → 접근성 + Convex Hull (캐시 사용)
# ═══════════════════════════════════════════════════════════════════════════════
if REACH_CACHE.exists() and HULL_CACHE.exists():
    log.info(f"캐시 로드: reach={REACH_CACHE.name}, hull={HULL_CACHE.name}")
    with open(REACH_CACHE) as f:
        reach_dong = json.load(f)
    with open(HULL_CACHE) as f:
        hulls_dong = json.load(f)
    log.info(f"  로드 완료: {len(reach_dong)}개 동")
else:
    log.info(f"전방향 Dijkstra 계산 (총 {len(gdf)}회, cutoff={MAX_DIST:.0f}m)...")
    reach_dong  = {}
    hulls_dong  = {}
    t0 = time.time()

    for i, (_, row) in enumerate(gdf.iterrows()):
        dc    = row["adm_cd"]
        src   = int(row["osm_node"])
        cx_4326, cy_4326 = float(row["cx"]), float(row["cy"])
        cx5, cy5 = to_5179.transform(cx_4326, cy_4326)

        lengths = nx.single_source_dijkstra_path_length(
            G_ud, src, cutoff=MAX_DIST, weight="length"
        )

        # 쉼터 거리 배열
        heat_dists = np.array([lengths.get(n, 999999.0) for n in heat_node_list])
        cold_dists = np.array([lengths.get(n, 999999.0) for n in cold_node_list])
        nearest_heat = float(heat_dists.min())
        nearest_cold = float(cold_dists.min())

        # 도달 노드 좌표 (EPSG:5179 상대 좌표)
        reachable = list(lengths.keys())
        if reachable:
            nx4 = np.array([G_ud.nodes[n].get("x", cx_4326) for n in reachable])
            ny4 = np.array([G_ud.nodes[n].get("y", cy_4326) for n in reachable])
            nx5, ny5 = to_5179.transform(nx4, ny4)
            nd   = np.array([lengths[n] for n in reachable])
            ddx  = nx5 - cx5
            ddy  = ny5 - cy5
        else:
            nd = ddx = ddy = np.array([])

        reach_dong[dc]  = {s["id"]: {} for s in SPEEDS}
        hulls_dong[dc]  = {str(t): {} for t in TIMES}

        for s in SPEEDS:
            sid    = s["id"]
            for t in TIMES:
                thresh = s["mps"] * t * 60
                heat_cnt = int((heat_dists <= thresh).sum())
                cold_cnt = int((cold_dists <= thresh).sum())
                reach_dong[dc][sid][str(t)] = {
                    "heat":   heat_cnt,
                    "cold":   cold_cnt,
                    "heat_m": int(nearest_heat) if nearest_heat < 90000 else None,
                    "cold_m": int(nearest_cold) if nearest_cold < 90000 else None,
                }

                # Convex hull
                if nd.size > 0:
                    mask = nd <= thresh
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
    log.info(f"  reach: {REACH_CACHE.stat().st_size//1024} KB  hull: {HULL_CACHE.stat().st_size//1024} KB")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. GU 단위 집계
# ═══════════════════════════════════════════════════════════════════════════════
log.info("구 단위 집계...")
gu_dongs = {}   # gu_code → [dong_codes]
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

# ═══════════════════════════════════════════════════════════════════════════════
# 7. GU centroid hull 계산 (25회 Dijkstra)
# ═══════════════════════════════════════════════════════════════════════════════
log.info("구 단위 Hull 계산 (25회 Dijkstra)...")
# dissolve 원본 동 → simplify: 선 simplify 후 dissolve하면 경계 artifact 발생
gdf_gu_diss = gdf.dissolve(by="gu_code", as_index=False)
gdf_gu_diss["geometry"] = gdf_gu_diss.geometry.simplify(0.0005)
gdf_gu_diss["cx"] = gdf_gu_diss.geometry.centroid.x
gdf_gu_diss["cy"] = gdf_gu_diss.geometry.centroid.y
gu_c_nodes = ox.nearest_nodes(
    G_ud, gdf_gu_diss["cx"].tolist(), gdf_gu_diss["cy"].tolist()
)

hulls_gu  = {}
gu_centroids = {}
for i, (_, row) in enumerate(gdf_gu_diss.iterrows()):
    gc = str(row["gu_code"])
    src = gu_c_nodes[i]
    cx_4326, cy_4326 = float(row["cx"]), float(row["cy"])
    cx5, cy5 = to_5179.transform(cx_4326, cy_4326)
    gu_centroids[gc] = {"lat": round(cy_4326, 6), "lng": round(cx_4326, 6)}

    lengths = nx.single_source_dijkstra_path_length(
        G_ud, src, cutoff=MAX_DIST, weight="length"
    )
    hulls_gu[gc] = {str(t): {} for t in TIMES}

    if lengths:
        reachable = list(lengths.keys())
        nx4 = np.array([G_ud.nodes[n].get("x", cx_4326) for n in reachable])
        ny4 = np.array([G_ud.nodes[n].get("y", cy_4326) for n in reachable])
        nx5, ny5 = to_5179.transform(nx4, ny4)
        nd  = np.array([lengths[n] for n in reachable])
        ddx = nx5 - cx5
        ddy = ny5 - cy5
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

# ═══════════════════════════════════════════════════════════════════════════════
# 8. GeoJSON 생성
# ═══════════════════════════════════════════════════════════════════════════════
log.info("GeoJSON 생성...")

# 동 GeoJSON
gdf_ds = gdf.copy()
gdf_ds["geometry"] = gdf_ds.geometry.simplify(0.0003)

dong_features = []
for _, row in gdf_ds.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    dc = row["adm_cd"]
    d  = reach_dong.get(dc, {})
    h30 = d.get("g2", {}).get("30", {}).get("heat", 0)
    c30 = d.get("g2", {}).get("30", {}).get("cold", 0)
    g0h = d.get("g0", {}).get("30", {}).get("heat", 1) or 1
    loss = round((1 - h30 / g0h) * 100, 1) if g0h else 0
    dong_features.append({
        "type": "Feature",
        "geometry": geom.__geo_interface__,
        "properties": {
            "nm":   row["adm_nm"],
            "cd":   dc,
            "gc":   row["gu_code"],
            "p65":  int(row["pop_65plus"]),
            "h30":  h30,
            "c30":  c30,
            "loss": loss,
        },
    })
dong_geo_js = json.dumps(
    {"type": "FeatureCollection", "features": dong_features},
    ensure_ascii=False, separators=(",", ":"),
)
log.info(f"  동 GeoJSON: {len(dong_features)}개 {len(dong_geo_js)//1024}KB")

# 구 GeoJSON
gu_features = []
for _, row in gdf_gu_diss.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    gc = str(row["gu_code"])
    r  = reach_gu.get(gc, {})
    h30 = r.get("g2", {}).get("30", {}).get("heat", 0)
    c30 = r.get("g2", {}).get("30", {}).get("cold", 0)
    g0h = r.get("g0", {}).get("30", {}).get("heat", 1) or 1
    loss = round((1 - h30 / g0h) * 100, 1) if g0h else 0
    gu_features.append({
        "type": "Feature",
        "geometry": geom.__geo_interface__,
        "properties": {
            "nm":   SEOUL_GU.get(gc, gc),
            "cd":   gc,
            "p65":  gu_pop.get(gc, {}).get("p65", 0),
            "h30":  h30,
            "c30":  c30,
            "loss": loss,
        },
    })
gu_geo_js = json.dumps(
    {"type": "FeatureCollection", "features": gu_features},
    ensure_ascii=False, separators=(",", ":"),
)
log.info(f"  구 GeoJSON: {len(gu_features)}개 {len(gu_geo_js)//1024}KB")

# ═══════════════════════════════════════════════════════════════════════════════
# 9. 결빙 데이터
# ═══════════════════════════════════════════════════════════════════════════════
log.info("결빙 캐시 로드 (stats)...")
with open(ICING_CACHE) as f:
    icing = json.load(f)
ist = icing["stats"]

# 제설함 데이터 로드
with open(JISEOL_CACHE) as f:
    jiseol_boxes = json.load(f)
jiseol_js = json.dumps(jiseol_boxes, ensure_ascii=False, separators=(",", ":"))
log.info(f"  제설함: {len(jiseol_boxes)}개 ({len(jiseol_js)//1024}KB)")

# 서울 외곽 (결빙 레이어용 evenodd 바깥 테두리)
# Dong union → 행정동 범위 (한강 본류는 행정동에 미포함되어 자동 제외)
log.info("서울 외곽 계산...")
from shapely.geometry import MultiPolygon as _MP
seoul_union_raw = gdf.unary_union.simplify(0.0001)
if hasattr(seoul_union_raw, "geoms"):
    seoul_outer_geom = max(seoul_union_raw.geoms, key=lambda g: g.area)
else:
    seoul_outer_geom = seoul_union_raw
seoul_outline = [[round(x, 5), round(y, 5)] for x, y in seoul_outer_geom.exterior.coords]
seoul_outline_js = json.dumps(seoul_outline, separators=(",", ":"))
log.info(f"  서울 외곽: {len(seoul_outline)}개 꼭짓점 {len(seoul_outline_js)//1024}KB")

# ═══════════════════════════════════════════════════════════════════════════════
# 10. JS 메타 데이터 준비
# ═══════════════════════════════════════════════════════════════════════════════

# 동 메타 (selector용)
dong_meta = []
for _, row in gdf.iterrows():
    dong_meta.append({
        "cd":  row["adm_cd"],
        "nm":  row["adm_nm"],
        "gc":  row["gu_code"],
        "gnm": row["gu_name"],
        "lat": round(float(row["cy"]), 5),
        "lng": round(float(row["cx"]), 5),
        "p65": int(row["pop_65plus"]),
    })
dong_meta.sort(key=lambda x: (x["gc"], x["nm"]))

# 구 메타 (spatial join으로 쉼터 수 계산 후 구성)
heat_gdf = gpd.GeoDataFrame(
    HEAT_LOC,
    geometry=gpd.points_from_xy([s["lng"] for s in HEAT_LOC], [s["lat"] for s in HEAT_LOC]),
    crs="EPSG:4326",
)
cold_gdf = gpd.GeoDataFrame(
    COLD_LOC,
    geometry=gpd.points_from_xy([s["lng"] for s in COLD_LOC], [s["lat"] for s in COLD_LOC]),
    crs="EPSG:4326",
)
gu_boundary = gdf[["gu_code", "gu_name", "geometry"]].copy()
gu_boundary = gu_boundary.dissolve(by="gu_code", as_index=False)

heat_join = gpd.sjoin(heat_gdf, gu_boundary[["gu_code", "geometry"]], how="left", predicate="within")
cold_join = gpd.sjoin(cold_gdf, gu_boundary[["gu_code", "geometry"]], how="left", predicate="within")
heat_cnt_by_gu = heat_join.groupby("gu_code").size().to_dict()
cold_cnt_by_gu = cold_join.groupby("gu_code").size().to_dict()

gu_meta = []
for gc, gnm in sorted(SEOUL_GU.items()):
    if gc in gu_centroids:
        c   = gu_centroids[gc]
        pop = gu_pop.get(gc, {"p65": 0, "total": 0})
        gu_meta.append({
            "cd":   gc,
            "nm":   gnm,
            "lat":  c["lat"],
            "lng":  c["lng"],
            "p65":  pop["p65"],
            "heat": heat_cnt_by_gu.get(gc, 0),
            "cold": cold_cnt_by_gu.get(gc, 0),
        })

# ═══════════════════════════════════════════════════════════════════════════════
# 11. CDN 인라인
# ═══════════════════════════════════════════════════════════════════════════════
leaflet_css = (CDN_DIR / "leaflet.css").read_text()
leaflet_js  = (CDN_DIR / "leaflet.js").read_text()
chartjs     = (CDN_DIR / "chartjs.min.js").read_text()

# JSON 직렬화
speeds_js    = json.dumps(SPEEDS, ensure_ascii=False)
heat_loc_js  = json.dumps(HEAT_LOC, ensure_ascii=False, separators=(",", ":"))
cold_loc_js  = json.dumps(COLD_LOC, ensure_ascii=False, separators=(",", ":"))
reach_d_js   = json.dumps(reach_dong, ensure_ascii=False, separators=(",", ":"))
reach_g_js   = json.dumps(reach_gu,   ensure_ascii=False, separators=(",", ":"))
hulls_d_js   = json.dumps(hulls_dong, ensure_ascii=False, separators=(",", ":"))
hulls_g_js   = json.dumps(hulls_gu,   ensure_ascii=False, separators=(",", ":"))
dong_meta_js = json.dumps(dong_meta,  ensure_ascii=False, separators=(",", ":"))
gu_meta_js   = json.dumps(gu_meta,    ensure_ascii=False, separators=(",", ":"))
gu_pop_js    = json.dumps(gu_pop,     ensure_ascii=False, separators=(",", ":"))
icing_s_js   = json.dumps(ist,        ensure_ascii=False)
seoul_ol_js  = seoul_outline_js

N_DONG = len(gdf)
HEAT_N = len(HEAT_LOC)
COLD_N = len(COLD_LOC)

# ═══════════════════════════════════════════════════════════════════════════════
# 12. HTML 생성
# ═══════════════════════════════════════════════════════════════════════════════
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>노인 보행일상권 — ③ 기후 안전권</title>
<style>{leaflet_css}</style>
<script>{leaflet_js}</script>
<script>{chartjs}</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Noto Sans KR','Apple SD Gothic Neo',sans-serif;background:#f5f4f0;color:#2c2c2a;font-size:14px;line-height:1.5;overflow-y:scroll}}
header{{background:#2c2c2a;color:#f1efe8;padding:16px 28px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}}
header h1{{font-size:17px;font-weight:500}}
header p{{font-size:12px;opacity:.55}}
.wrap{{max-width:1340px;margin:0 auto;padding:18px 18px 60px}}
/* 컨트롤 */
.ctrl{{background:#fff;border:.5px solid #d3d1c7;border-radius:12px;padding:14px 20px;margin-bottom:14px}}
.crow{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px}}
.crow:last-child{{margin-bottom:0}}
.lbl{{font-size:11px;font-weight:500;letter-spacing:.06em;color:#888780;white-space:nowrap;margin-right:2px}}
.btn{{font-size:12px;padding:5px 14px;border-radius:20px;border:.5px solid #b4b2a9;background:transparent;color:#5f5e5a;cursor:pointer;transition:all .14s;font-family:inherit;white-space:nowrap}}
.btn:hover{{border-color:#5f5e5a;color:#2c2c2a}}
.btn.on{{background:#2c2c2a;color:#f1efe8;border-color:#2c2c2a}}
.bw{{border-radius:8px}}
select{{font-family:inherit;font-size:12px;padding:5px 10px;border:.5px solid #b4b2a9;border-radius:6px;background:#fff;color:#2c2c2a;cursor:pointer;outline:none}}
select:focus{{border-color:#5f5e5a}}
/* 통계 카드 */
.sgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}}
.sc{{background:#f5f4f0;border-radius:8px;padding:12px 14px}}
.sl{{font-size:11px;color:#888780;margin-bottom:3px}}
.sv{{font-size:22px;font-weight:500}}
.sv.red{{color:#c0392b}} .sv.green{{color:#0f6e56}} .sv.blue{{color:#185FA5}}
.ss{{font-size:11px;color:#888780;margin-top:2px}}
/* 2열 그리드 */
.r2{{display:grid;grid-template-columns:1.45fr 1fr;gap:14px;margin-bottom:14px}}
.r2b{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}
.card{{background:#fff;border:.5px solid #d3d1c7;border-radius:12px;padding:16px 18px}}
.ct{{font-size:11px;font-weight:500;letter-spacing:.06em;color:#888780;text-transform:uppercase;margin-bottom:10px}}
/* 지도 */
.map-wrap{{position:relative;height:420px;border-radius:8px;overflow:hidden;background:#e8e4db}}
.lmap{{position:absolute;inset:0;height:100%!important}}
.leg{{display:flex;gap:14px;flex-wrap:wrap;margin-top:9px}}
.li{{display:flex;align-items:center;gap:5px;font-size:11px;color:#5f5e5a}}
.ld{{width:12px;height:12px;border-radius:2px;flex-shrink:0}}
.chart-wrap{{position:relative;height:260px;width:100%}}
/* 창의 시각화 패널 */
.viz-tabs{{display:flex;gap:5px;margin-bottom:10px;flex-wrap:wrap}}
.vtab{{font-size:11px;padding:4px 12px;border-radius:16px;border:.5px solid #b4b2a9;background:transparent;color:#5f5e5a;cursor:pointer;font-family:inherit;white-space:nowrap;transition:all .14s}}
.vtab:hover{{border-color:#5f5e5a}}
.vtab.on{{background:#2c2c2a;color:#f1efe8;border-color:#2c2c2a}}
.viz-panel{{display:none}}
.viz-panel.active{{display:block}}
.dark-canvas{{display:block;width:100%;border-radius:8px;background:#080a10}}
/* 탭 */
.main-tabs{{display:flex;gap:6px;margin-bottom:14px}}
.mtab{{font-size:13px;padding:8px 20px;border-radius:24px;border:.5px solid #d3d1c7;background:#fff;color:#5f5e5a;cursor:pointer;font-family:inherit;font-weight:500;transition:all .14s}}
.mtab:hover{{border-color:#5f5e5a}}
.mtab.on{{background:#2c2c2a;color:#f1efe8;border-color:#2c2c2a}}
/* 노트 */
.note{{background:#faeeda;border:.5px solid #ef9f27;border-radius:8px;padding:10px 14px;font-size:12px;color:#633806;line-height:1.7;margin-top:10px}}
.note-b{{background:#e8f4fd;border:.5px solid #3498db;border-radius:8px;padding:10px 14px;font-size:12px;color:#1a5276;line-height:1.7;margin-top:8px}}
.src{{font-size:11px;color:#888780;margin-top:8px;line-height:1.7}}
/* 테이블 */
#tbl-wrap{{overflow-x:auto;margin-top:14px}}
#tbl{{width:100%;border-collapse:collapse;font-size:12px}}
#tbl th{{background:#f5f4f0;padding:8px 10px;text-align:left;font-weight:500;color:#5f5e5a;border-bottom:1px solid #d3d1c7;white-space:nowrap}}
#tbl td{{padding:7px 10px;border-bottom:.5px solid #e8e6e0;color:#2c2c2a}}
#tbl tr:last-child td{{border-bottom:none}}
#tbl tr.sel td{{background:#f9f8f4;font-weight:500}}
.pill{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500}}
.phi{{background:#d4edda;color:#155724}} .pmd{{background:#fff3cd;color:#856404}} .plo{{background:#f8d7da;color:#721c24}}
/* 툴팁 */
.tip-box{{position:fixed;z-index:9999;background:#fff;border:.5px solid #d3d1c7;border-radius:8px;padding:10px 14px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.12);pointer-events:none;display:none;max-width:240px;line-height:1.7}}
@media(max-width:900px){{.r2,.r2b,.sgrid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>③ 기후 — 노인 기후안전권 분석</h1>
  <p>더위쉼터 {HEAT_N:,}개 · 한파쉼터 {COLD_N:,}개 · 행정동 {N_DONG}개 · OSM 보행 네트워크 + 다익스트라 · 서울시 2025</p>
</header>

<div class="wrap">

  <!-- 메인 탭 -->
  <div class="main-tabs">
    <button class="mtab on" onclick="setTab('heat',this)">🌡️ 더위쉼터</button>
    <button class="mtab"    onclick="setTab('cold',this)">❄️ 한파쉼터</button>
    <button class="mtab"    onclick="setTab('ice',this)">🧊 결빙위험구역</button>
  </div>

  <!-- ══ 더위/한파 공통 섹션 ══ -->
  <div id="sec-shelter">

    <!-- 컨트롤 패널 -->
    <div class="ctrl">
      <div class="crow">
        <span class="lbl">보행자 유형</span>
        <button class="btn bw on" id="wb0" onclick="setW(0,this)">🚶 일반인 1.28 m/s</button>
        <button class="btn bw"    id="wb1" onclick="setW(1,this)">🧓 일반 노인 1.12 m/s</button>
        <button class="btn bw"    id="wb2" onclick="setW(2,this)">🦽 보행보조 노인 0.88 m/s</button>
        <button class="btn bw"    id="wb3" onclick="setW(3,this)">🦽 보행보조 하위 15% 0.70 m/s</button>
        <span style="flex:1"></span>
        <span class="lbl">보행 시간</span>
        <button class="btn" id="tb15" onclick="setT(15,this)">15분</button>
        <button class="btn on" id="tb30" onclick="setT(30,this)">30분</button>
        <button class="btn" id="tb45" onclick="setT(45,this)">45분</button>
      </div>
      <div class="crow">
        <span class="lbl">행정 단위</span>
        <button class="btn on" id="unit-gu"   onclick="setUnit('gu',this)">자치구</button>
        <button class="btn"    id="unit-dong" onclick="setUnit('dong',this)">행정동</button>
        <span style="flex:1"></span>
        <span class="lbl">기준 지역</span>
        <select id="sel-area" onchange="setSel(this.value)" style="min-width:160px"></select>
      </div>
      <div class="sgrid" id="stat-cards"></div>
    </div>

    <!-- 지도 + 캔버스 -->
    <div class="r2">
      <div class="card">
        <div class="ct" id="map-title">서울시 기후 쉼터 접근성 지도</div>
        <div class="map-wrap"><div id="map" class="lmap"></div></div>
        <div class="leg">
          <div class="li"><div class="ld" style="background:#1D9E75"></div>도달 가능 (선택 속도)</div>
          <div class="li"><div class="ld" style="background:#E74C3C"></div>도달 불가</div>
          <div class="li" id="leg-heat"><div class="ld" style="background:#FF8C00;border-radius:50%"></div>더위쉼터</div>
          <div class="li" id="leg-cold" style="display:none"><div class="ld" style="background:#4A90D9;border-radius:50%"></div>한파쉼터</div>
        </div>
        <div class="src">
          multi-source Dijkstra · 쉼터 → 전체 OSM 노드 최단 보행 거리 사전계산<br>
          클릭: 해당 지역 선택 · 툴팁: 속도별 소요 시간
        </div>
      </div>
      <div class="card">
        <div class="ct">보행 한계 — 4가지 시점</div>
        <div class="viz-tabs">
          <button class="vtab on" onclick="setVizTab(0,this)">🌌 중력궤도</button>
          <button class="vtab"    onclick="setVizTab(1,this)">🔗 단절망</button>
        </div>
        <!-- 0: 중력궤도 (Gravity Rings) -->
        <div class="viz-panel active">
          <canvas id="cv-gravity" class="dark-canvas" width="500" height="370"></canvas>
          <div class="src" style="margin-top:5px">선택 지역 centroid 기준 · 동심원 = 속도별 도달 반경 · 점 = 쉼터 (직선거리) · 녹색=도달/적색=불가</div>
        </div>
        <!-- 1: 단절망 (Shattered Network) -->
        <div class="viz-panel">
          <canvas id="cv-network" class="dark-canvas" width="500" height="370"></canvas>
          <div class="src" style="margin-top:5px">중심→쉼터 광섬유 연결 · 도달 가능=빛나는 라인 / 불가=단절된 파편</div>
        </div>
      </div>
    </div>

    <!-- 차트 2열 -->
    <div class="r2b">
      <div class="card">
        <div class="ct">자치구별 도달 가능 쉼터 수</div>
        <div class="chart-wrap"><canvas id="gc-chart"></canvas></div>
      </div>
      <div class="card">
        <div class="ct">선택 지역 — 시간대별 도달 쉼터 비교</div>
        <div class="chart-wrap"><canvas id="wc-chart"></canvas></div>
      </div>
    </div>

    <!-- 상세표 -->
    <div class="card">
      <div class="ct">자치구별 기후 쉼터 접근성 상세표</div>
      <div id="tbl-wrap"></div>
    </div>
  </div>

  <!-- ══ 결빙 섹션 ══ -->
  <div id="sec-ice" style="display:none">
    <div class="ctrl">
      <div class="crow">
        <span class="lbl">제설함 반경</span>
        <button class="btn bw on" id="ibuf100" onclick="setIceBuf(100,this)">100m</button>
        <button class="btn bw"    id="ibuf200" onclick="setIceBuf(200,this)">200m</button>
        <span style="margin-left:14px;color:#888780">|</span>
        <button class="btn bw on" id="itog-icing"  onclick="togIce('icing',this)">결빙취약 ON</button>
        <button class="btn bw on" id="itog-cov"    onclick="togIce('cov',this)">커버원 ON</button>
        <button class="btn bw on" id="itog-boxes"  onclick="togIce('boxes',this)">제설함 ON</button>
        <span style="flex:1"></span>
        <span style="font-size:11px;color:#888780">도심 기반(행정동 − 수역·산림) = {ist['clean_km2']} km²</span>
      </div>
      <div class="sgrid" id="ice-cards"></div>
    </div>
    <div class="r2">
      <div class="card">
        <div class="ct">겨울 결빙 취약 구역 지도</div>
        <div class="map-wrap"><div id="ice-map" class="lmap"></div></div>
        <div class="leg">
          <div class="li"><div class="ld" style="background:#C62828;opacity:.7"></div>결빙 취약 구역 (한강·산지 제외)</div>
          <div class="li"><div class="ld" style="background:#1565C0;opacity:.35;border:1px solid #42A5F5"></div>제설함 커버리지 원</div>
          <div class="li"><div class="ld" style="background:#00E5FF;border-radius:50%"></div>제설함 위치</div>
        </div>
        <div class="src">제설함 {len(jiseol_boxes):,}개 · 100m/200m 버퍼 합집합 · 서울 행정동 − OSM 자연지물 (한강·산지)</div>
      </div>
      <div class="card">
        <div class="ct">결빙 위험 서사</div>
        <div id="ice-narrative" style="line-height:1.9;font-size:13px;padding:4px 0"></div>
        <div class="note">
          <b>낙상 경로:</b> 제설함 없음 → 초동 제설 불가 → 결빙 지속 → 노인 낙상<br>
          서울 연간 낙상 사고 37%가 12–2월 집중. 보행보조 노인의 낙상 치사율은 일반 노인 대비 2.3배.
        </div>
        <div class="note-b">
          <b>분석:</b> 서울 행정동 426개 합집합(605.8 km²) → OSM 수역 411개·산림 1,384개 차감 →
          도심 기반 431.9 km² → 제설함 버퍼 차감
        </div>
      </div>
    </div>
  </div>

</div><!-- /wrap -->

<div id="tip-box" class="tip-box"></div>

<script>
// ─── 데이터 상수 ────────────────────────────────────────────────────────────
const SPEEDS    = {speeds_js};
const HEAT_LOC  = {heat_loc_js};
const COLD_LOC  = {cold_loc_js};
const DONG_GEO  = {dong_geo_js};
const GU_GEO    = {gu_geo_js};
const REACH_D   = {reach_d_js};
const REACH_G   = {reach_g_js};
const HULLS_D   = {hulls_d_js};
const HULLS_G   = {hulls_g_js};
const DONG_META = {dong_meta_js};
const GU_META   = {gu_meta_js};
const GU_POP    = {gu_pop_js};
const SEOUL_OUTLINE = {seoul_ol_js};
const ICING_S   = {icing_s_js};
const JISEOL    = {jiseol_js};
const N_DONG    = {N_DONG};

// ─── 상태 ──────────────────────────────────────────────────────────────────
let cW    = 0;        // 보행자 인덱스 (0–3)
let cT    = 30;       // 보행 시간 (분)
let cTab  = 'heat';   // 현재 탭
let cUnit = 'gu';     // 'gu' | 'dong'
let cSel  = null;     // 선택된 코드
let map, gcChart, wcChart, iceMap;
let shelterLayer = null, choroLayer = null, hullLayer = null;
let iceLayer = null;
let mapInit = false, iceMapInit = false;

// ─── 탭 전환 ────────────────────────────────────────────────────────────────
function setTab(tab, btn) {{
  if (cTab === tab) return;
  document.querySelectorAll('.mtab').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  cTab = tab;
  if (tab === 'ice') {{
    document.getElementById('sec-shelter').style.display = 'none';
    document.getElementById('sec-ice').style.display = '';
    if (!iceMapInit) {{ initIceMap(); iceMapInit = true; }}
    else iceMap && iceMap.invalidateSize();
    updateIceCards(100);
    updateIceNarrative(100);
  }} else {{
    document.getElementById('sec-ice').style.display = 'none';
    document.getElementById('sec-shelter').style.display = '';
    updateAll();
    map && map.invalidateSize();
  }}
}}

// ─── 컨트롤 핸들러 ──────────────────────────────────────────────────────────
function setW(i, btn) {{
  cW = i;
  document.querySelectorAll('.bw').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  updateAll();
}}
function setT(t, btn) {{
  cT = t;
  ['15','30','45'].forEach(v => document.getElementById('tb'+v).classList.toggle('on', t==v));
  updateAll();
}}
function setUnit(u, btn) {{
  cUnit = u;
  document.getElementById('unit-gu').classList.toggle('on', u==='gu');
  document.getElementById('unit-dong').classList.toggle('on', u==='dong');
  buildSelector();
  updateAll();
}}
function setSel(code) {{
  cSel = code;
  updateAll();
}}

// ─── 지역 selector 구성 ──────────────────────────────────────────────────────
function buildSelector() {{
  const sel = document.getElementById('sel-area');
  sel.innerHTML = '';
  if (cUnit === 'gu') {{
    GU_META.forEach(g => {{
      const opt = document.createElement('option');
      opt.value = g.cd; opt.textContent = g.nm;
      sel.appendChild(opt);
    }});
    cSel = cSel && GU_META.find(g => g.cd === cSel) ? cSel : GU_META[0]?.cd;
  }} else {{
    DONG_META.forEach(d => {{
      const opt = document.createElement('option');
      opt.value = d.cd; opt.textContent = d.gnm + ' ' + d.nm;
      sel.appendChild(opt);
    }});
    cSel = cSel && DONG_META.find(d => d.cd === cSel) ? cSel : DONG_META[0]?.cd;
  }}
  sel.value = cSel;
}}

// ─── reach 데이터 룩업 ───────────────────────────────────────────────────────
function getReach(code, sid, t) {{
  const r = cUnit === 'gu' ? REACH_G : REACH_D;
  return (r[code]?.[sid]?.[String(t)]) || {{heat:0,cold:0,heat_m:null,cold_m:null}};
}}
function getSelMeta() {{
  if (cUnit === 'gu') return GU_META.find(g => g.cd === cSel) || GU_META[0];
  return DONG_META.find(d => d.cd === cSel) || DONG_META[0];
}}
function getSelPop() {{
  if (cUnit === 'gu') return (GU_POP[cSel] || {{p65:0}}).p65;
  return DONG_META.find(d => d.cd === cSel)?.p65 || 0;
}}

// ─── updateAll ───────────────────────────────────────────────────────────────
function updateAll() {{
  updateMap();
  updateStats();
  drawCurrentViz();
  updateGC();
  updateWC();
  updateTable();
}}

// ─── 지도 ────────────────────────────────────────────────────────────────────
function initMap() {{
  map = L.map('map', {{center:[37.5665,126.9780], zoom:11}});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{attribution:'© OSM · © CartoDB', maxZoom:19, subdomains:'abcd'}}).addTo(map);
  mapInit = true;
  updateMap();
}}

function updateMap() {{
  if (!mapInit) return;
  const sid    = SPEEDS[cW].id;
  const thresh = SPEEDS[cW].mps * cT * 60;
  const geoSrc = cUnit === 'gu' ? GU_GEO : DONG_GEO;
  const key    = cTab === 'cold' ? 'cold' : 'heat';
  const rKey   = cUnit === 'gu' ? REACH_G : REACH_D;

  if (choroLayer) map.removeLayer(choroLayer);
  if (shelterLayer) map.removeLayer(shelterLayer);
  if (hullLayer) map.removeLayer(hullLayer);

  // 코로플레스 레이어
  choroLayer = L.geoJSON(geoSrc, {{
    style: f => {{
      const cd   = f.properties.cd;
      const d    = rKey[cd]?.[sid]?.[String(cT)];
      const cnt  = d ? d[key] : 0;
      const ok   = cnt > 0;
      return {{
        fillColor:   ok ? '#1D9E75' : '#E74C3C',
        fillOpacity: ok ? 0.50 : 0.65,
        color: '#c0bcb4', weight: 0.8, opacity: 0.8, smoothFactor: 0,
      }};
    }},
    onEachFeature: (f, layer) => {{
      layer.on('mouseover', e => {{
        const p  = f.properties;
        const cd = p.cd;
        const rs = SPEEDS.map(s => {{
          const rd  = rKey[cd]?.[s.id]?.[String(cT)];
          const cnt = rd ? rd[key] : 0;
          return `<tr><td style="color:#888780;padding-right:8px">${{s.label}}</td>
                      <td style="font-weight:500">${{cnt}}개 도달</td></tr>`;
        }}).join('');
        showTip(e.originalEvent, `<b style="font-size:13px">${{p.nm}}</b>
          <table style="margin-top:6px;border-collapse:collapse">${{rs}}</table>`);
      }});
      layer.on('mouseout', hideTip);
      layer.on('click', () => {{
        cSel = f.properties.cd;
        document.getElementById('sel-area').value = cSel;
        updateAll();
      }});
    }},
  }}).addTo(map);

  // 쉼터 점 레이어
  const locs   = cTab === 'cold' ? COLD_LOC : HEAT_LOC;
  const dotCol = cTab === 'cold' ? '#4A90D9' : '#FF8C00';
  document.getElementById('leg-heat').style.display = cTab==='cold' ? 'none' : '';
  document.getElementById('leg-cold').style.display = cTab==='cold' ? '' : 'none';

  shelterLayer = L.layerGroup();
  locs.forEach(s => {{
    L.circleMarker([s.lat, s.lng], {{
      radius: 3, fillColor: dotCol, color: '#fff', weight: 0.5, fillOpacity: 0.85,
    }}).bindTooltip(`<b>${{s.name}}</b><br><span style="color:#888780">${{s.type}}</span>`,
      {{direction:'top', offset:[0,-4]}}).addTo(shelterLayer);
  }});
  shelterLayer.addTo(map);

  // 선택 지역 강조 + centroid 핀
  highlightSel();
}}

let selPinLayer = null;

function highlightSel() {{
  if (!mapInit || !cSel) return;
  if (hullLayer) map.removeLayer(hullLayer);
  if (selPinLayer) map.removeLayer(selPinLayer);
  const geoSrc = cUnit === 'gu' ? GU_GEO : DONG_GEO;
  const feat   = geoSrc.features.find(f => f.properties.cd === cSel);
  if (feat) {{
    hullLayer = L.geoJSON(feat, {{
      style: {{ fillColor: 'transparent', color: '#2060c0', weight: 2.5, opacity: 0.9, smoothFactor: 0 }},
    }}).addTo(map);
    map.fitBounds(hullLayer.getBounds(), {{padding: [30,30], maxZoom: 14}});
  }}
  // centroid 핀 — 모식도 기준점 표시
  const meta = getSelMeta();
  if (meta && meta.lat) {{
    const pinIcon = L.divIcon({{
      html: `<div style="width:14px;height:14px;border-radius:50%;background:#2c2c2a;border:3px solid #fff;box-shadow:0 0 0 2px #2c2c2a"></div>`,
      className: '', iconSize:[14,14], iconAnchor:[7,7]
    }});
    selPinLayer = L.marker([meta.lat, meta.lng], {{icon:pinIcon, zIndexOffset:1000}})
      .bindTooltip(`<b>${{meta.nm}}</b><br>보행권 시각화 기준점`, {{direction:'top', permanent:false}})
      .addTo(map);
  }}
  // ── Convex Hull 오버레이 (지도 위에 직접) ──
  const hulls = cUnit === 'gu' ? HULLS_G : HULLS_D;
  const hdata = hulls[cSel];
  const meta2 = getSelMeta();
  if (hdata && meta2 && meta2.lat) {{
    const tKey = String(cT);
    const th = hdata[tKey];
    if (th) {{
      const R = 111111, cosLat = Math.cos(meta2.lat * Math.PI / 180);
      SPEEDS.slice().reverse().forEach((s, ri) => {{
        const i = 3 - ri;
        const hull = th[s.id];
        if (!hull || hull.length < 3) return;
        const latlngs = hull.map(([dx, dy]) => [
          meta2.lat + dy / R,
          meta2.lng + dx / (R * cosLat)
        ]);
        L.polygon(latlngs, {{
          fillColor: s.color,
          fillOpacity: i === cW ? 0.18 : 0.07,
          color: s.color,
          weight: i === cW ? 2.2 : 0.7,
          opacity: i === cW ? 0.9 : 0.35,
          dashArray: i === cW ? null : '4,3',
        }}).addTo(hullLayer);
      }});
    }}
  }}
}}

// ─── 통계 카드 ───────────────────────────────────────────────────────────────
function updateStats() {{
  const sid  = SPEEDS[cW].id;
  const d    = getReach(cSel, sid, cT);
  const d0   = getReach(cSel, 'g0', cT);
  const p65  = getSelPop();
  const g0h  = d0.heat || 1;
  const loss = d.heat != null ? Math.max(0, (1 - d.heat / g0h) * 100) : 0;
  const aff  = Math.round(loss * p65 / 100);
  const meta = getSelMeta();
  const lbl  = cTab === 'cold' ? '한파쉼터' : '더위쉼터';
  const cnt  = cTab === 'cold' ? d.cold : d.heat;
  const cnt0 = cTab === 'cold' ? d0.cold : d0.heat;
  const lossKey = cTab === 'cold'
    ? Math.max(0, (1 - (d.cold||0) / (d0.cold||1)) * 100) : loss;
  const fmt = v => cUnit==='gu' ? (typeof v==='number'?Math.round(v):v) : v;
  const avgNote = cUnit==='gu' ? ' (구 내 동 평균)' : '';
  document.getElementById('stat-cards').innerHTML = `
    <div class="sc">
      <div class="sl">${{lbl}} 도달 (${{SPEEDS[cW].label}})</div>
      <div class="sv green">${{fmt(cnt)}}</div>
      <div class="ss">${{cT}}분 내 · ${{SPEEDS[cW].mps}} m/s · ${{meta.nm}}${{avgNote}}</div>
    </div>
    <div class="sc">
      <div class="sl">${{lbl}} 도달 (일반인 기준)</div>
      <div class="sv">${{fmt(cnt0)}}</div>
      <div class="ss">${{cT}}분 내 · 1.28 m/s 기준${{avgNote}}</div>
    </div>
    <div class="sc">
      <div class="sl">보행 격차 (손실률)</div>
      <div class="sv red">${{lossKey.toFixed(1)}}%</div>
      <div class="ss">일반인 대비 도달 감소율</div>
    </div>
    <div class="sc">
      <div class="sl">${{cTab==='cold'?'더위':'한파'}}쉼터 도달 (${{SPEEDS[cW].label}})</div>
      <div class="sv blue">${{fmt(cTab==='cold'?d.heat:d.cold)}}</div>
      <div class="ss">${{cT}}분 내 · ${{SPEEDS[cW].mps}} m/s · ${{meta.nm}}${{avgNote}}</div>
    </div>`;
}}

// ─── 창의 시각화 ─────────────────────────────────────────────────────────────
let vizTab = 0;

function haversineM(lat1, lng1, lat2, lng2) {{
  const R=6371000, r=Math.PI/180;
  const dLat=(lat2-lat1)*r, dLng=(lng2-lng1)*r;
  const a=Math.sin(dLat/2)**2+Math.cos(lat1*r)*Math.cos(lat2*r)*Math.sin(dLng/2)**2;
  return 2*R*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

function setVizTab(t, btn) {{
  vizTab = t;
  document.querySelectorAll('.vtab').forEach((b,i)=>b.classList.toggle('on',i===t));
  document.querySelectorAll('.viz-panel').forEach((p,i)=>p.classList.toggle('active',i===t));
  drawCurrentViz();
}}

function drawCurrentViz() {{
  if (!cSel) return;
  switch(vizTab) {{
    case 0: drawGravityRings(); break;
    case 1: drawNetwork(); break;
  }}
}}

// ── 0. 중력궤도 (고립의 블랙홀) ─────────────────────────────────────────────
function drawGravityRings() {{
  const cv=document.getElementById('cv-gravity'); if(!cv) return;
  const ctx=cv.getContext('2d'), W=cv.width, H=cv.height;
  ctx.clearRect(0,0,W,H);
  const bg=ctx.createRadialGradient(W/2,H/2,0,W/2,H/2,Math.max(W,H)*0.7);
  bg.addColorStop(0,'#0e1e35'); bg.addColorStop(0.5,'#060f1e'); bg.addColorStop(1,'#020810');
  ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);

  const meta=getSelMeta(); if(!meta||!meta.lat) return;
  const cx=W/2, cy=H/2, maxDistM=3456;
  const scale=(Math.min(W,H)/2-32)/maxDistM;

  // 격자 원
  for(let d=500;d<=maxDistM;d+=500){{
    const r=d*scale;
    ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2);
    ctx.strokeStyle='#ffffff0a'; ctx.lineWidth=0.5; ctx.stroke();
    if(d%1000===0){{
      ctx.fillStyle='#ffffff22'; ctx.font='8px system-ui'; ctx.textAlign='center';
      ctx.fillText(`${{d/1000}}km`,cx+2,cy-r+9);
    }}
  }}

  // 속도별 링 (바깥→안)
  const selDistM=SPEEDS[cW].mps*cT*60;
  [...SPEEDS].reverse().forEach((s,ri)=>{{
    const i=3-ri, distM=s.mps*cT*60, r=distM*scale, isSel=i===cW;
    const grad=ctx.createRadialGradient(cx,cy,r*0.5,cx,cy,r);
    grad.addColorStop(0,'transparent');
    grad.addColorStop(1,s.color+(isSel?'18':'08'));
    ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2);
    ctx.fillStyle=grad; ctx.fill();
    ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2);
    ctx.strokeStyle=isSel?s.color:s.color+'55';
    ctx.lineWidth=isSel?2.2:0.8;
    if(isSel){{ctx.shadowColor=s.color; ctx.shadowBlur=20;}}
    ctx.stroke(); ctx.shadowBlur=0;
    const la=-Math.PI*0.32;
    ctx.fillStyle=s.color+(isSel?'ee':'77');
    ctx.font=`${{isSel?10:9}}px system-ui`; ctx.textAlign='left';
    ctx.fillText(`${{s.label.replace(' 노인','')}} · ${{Math.round(distM)}}m`,
      cx+r*Math.cos(la)+4, cy+r*Math.sin(la));
  }});

  // 쉼터 점 — reach 판별은 OSM Dijkstra 실제 count 기준
  // haversine 가까운 순으로 정렬 후 상위 cnt개만 도달 가능으로 표시
  const locs=cTab==='cold'?COLD_LOC:HEAT_LOC;
  const dReach=getReach(cSel,SPEEDS[cW].id,cT);
  const cnt=Math.round((cTab==='cold'?dReach?.cold:dReach?.heat)||0);
  const visible=[];
  locs.forEach(s=>{{
    const distM=haversineM(meta.lat,meta.lng,s.lat,s.lng);
    if(distM<=maxDistM*1.12) visible.push({{s,distM}});
  }});
  visible.sort((a,b)=>a.distM-b.distM);
  visible.forEach(({{s,distM}},idx)=>{{
    const reach=idx<cnt;
    const bearing=Math.atan2((s.lng-meta.lng)*Math.cos(meta.lat*Math.PI/180),s.lat-meta.lat);
    const rPx=Math.min(distM*scale,Math.min(W,H)/2-6);
    const sx=cx+rPx*Math.sin(bearing), sy=cy-rPx*Math.cos(bearing);
    ctx.beginPath(); ctx.arc(sx,sy,reach?3:1.8,0,Math.PI*2);
    ctx.fillStyle=reach?SPEEDS[cW].color+'cc':'#E74C3C66';
    if(reach){{ctx.shadowColor=SPEEDS[cW].color; ctx.shadowBlur=6;}}
    ctx.fill(); ctx.shadowBlur=0;
  }});

  // 중심 별
  const cgr=ctx.createRadialGradient(cx,cy,0,cx,cy,10);
  cgr.addColorStop(0,'#ffffff'); cgr.addColorStop(0.5,'#aaccff66'); cgr.addColorStop(1,'transparent');
  ctx.beginPath(); ctx.arc(cx,cy,8,0,Math.PI*2); ctx.fillStyle=cgr;
  ctx.shadowColor='#aaccff'; ctx.shadowBlur=24; ctx.fill(); ctx.shadowBlur=0;

  ctx.fillStyle='#ffffff88'; ctx.font='10px system-ui'; ctx.textAlign='left';
  ctx.fillText(`${{cTab==='cold'?'한파':'더위'}}쉼터 ${{cnt}}개 도달 (OSM 보행) · 반경 ${{visible.length}}개 감지`,8,H-10);
}}

// ── 1. 단절망 (광섬유 파이프라인) ─────────────────────────────────────────────
function drawNetwork() {{
  const cv=document.getElementById('cv-network'); if(!cv) return;
  const ctx=cv.getContext('2d'), W=cv.width, H=cv.height;
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#06060f'; ctx.fillRect(0,0,W,H);

  const meta=getSelMeta(); if(!meta||!meta.lat) return;
  const cx=W/2, cy=H/2, selDistM=SPEEDS[cW].mps*cT*60, maxDistM=3456;
  const scale=(Math.min(W,H)/2-18)/maxDistM;

  // 격자 원
  for(let d=1000;d<=maxDistM;d+=1000){{
    ctx.beginPath(); ctx.arc(cx,cy,d*scale,0,Math.PI*2);
    ctx.strokeStyle='#ffffff08'; ctx.lineWidth=0.5; ctx.stroke();
  }}

  // 단절망 — reach 판별은 OSM Dijkstra 실제 count 기준 (haversine 가까운 순 상위 cnt개)
  const locs=cTab==='cold'?COLD_LOC:HEAT_LOC;
  const dReach=getReach(cSel,SPEEDS[cW].id,cT);
  const cnt=Math.round((cTab==='cold'?dReach?.cold:dReach?.heat)||0);
  const vis2=[];
  locs.forEach(s=>{{
    const distM=haversineM(meta.lat,meta.lng,s.lat,s.lng);
    if(distM<=maxDistM*1.05) vis2.push({{s,distM}});
  }});
  vis2.sort((a,b)=>a.distM-b.distM);
  vis2.forEach(({{s,distM}},idx)=>{{
    const bearing=Math.atan2((s.lng-meta.lng)*Math.cos(meta.lat*Math.PI/180),s.lat-meta.lat);
    const rPx=Math.min(distM*scale,Math.min(W,H)/2-5);
    const sx=cx+rPx*Math.sin(bearing), sy=cy-rPx*Math.cos(bearing);
    const reach=idx<cnt;
    if(reach){{
      const grad=ctx.createLinearGradient(cx,cy,sx,sy);
      grad.addColorStop(0,SPEEDS[cW].color+'60');
      grad.addColorStop(0.65,SPEEDS[cW].color+'bb');
      grad.addColorStop(1,SPEEDS[cW].color+'30');
      ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(sx,sy);
      ctx.strokeStyle=grad; ctx.lineWidth=1.4;
      ctx.shadowColor=SPEEDS[cW].color; ctx.shadowBlur=5;
      ctx.stroke(); ctx.shadowBlur=0;
      ctx.beginPath(); ctx.arc(sx,sy,3,0,Math.PI*2);
      ctx.fillStyle=SPEEDS[cW].color+'dd';
      ctx.shadowColor=SPEEDS[cW].color; ctx.shadowBlur=8; ctx.fill(); ctx.shadowBlur=0;
    }} else {{
      const segs=3+Math.min(4,Math.floor(distM/800));
      for(let seg=0;seg<segs;seg++){{
        const t0=seg/segs, t1=(seg+0.42)/segs;
        const jx=(Math.random()-.5)*4, jy=(Math.random()-.5)*4;
        ctx.beginPath();
        ctx.moveTo(cx+(sx-cx)*t0+jx,cy+(sy-cy)*t0+jy);
        ctx.lineTo(cx+(sx-cx)*t1+jx,cy+(sy-cy)*t1+jy);
        ctx.strokeStyle='#E74C3C28'; ctx.lineWidth=0.5; ctx.stroke();
      }}
      ctx.beginPath(); ctx.arc(sx,sy,1.5,0,Math.PI*2);
      ctx.fillStyle='#E74C3C44'; ctx.fill();
    }}
  }});

  // 중심 원점
  const cgr=ctx.createRadialGradient(cx,cy,0,cx,cy,14);
  cgr.addColorStop(0,'#ffffff'); cgr.addColorStop(0.45,SPEEDS[cW].color+'88'); cgr.addColorStop(1,'transparent');
  ctx.beginPath(); ctx.arc(cx,cy,12,0,Math.PI*2); ctx.fillStyle=cgr;
  ctx.shadowColor=SPEEDS[cW].color; ctx.shadowBlur=22; ctx.fill(); ctx.shadowBlur=0;

  ctx.fillStyle='#ffffff77'; ctx.font='10px system-ui'; ctx.textAlign='left';
  ctx.fillText(`활성 광섬유 ${{cnt}}개 (OSM 보행) · 단절 ${{vis2.length-cnt}}개`,8,H-10);
}}

// ─── 구별 도달 쉼터 바차트 ─────────────────────────────────────────────────
function updateGC() {{
  const sid  = SPEEDS[cW].id;
  const key  = cTab === 'cold' ? 'cold' : 'heat';
  const rows = GU_META.map(g => {{
    const d = REACH_G[g.cd]?.[sid]?.[String(cT)];
    return {{nm: g.nm, val: d ? d[key] : 0, cd: g.cd}};
  }}).sort((a, b) => b.val - a.val);
  const labels = rows.map(r => r.nm);
  const data   = rows.map(r => r.val);
  const bgs    = rows.map(r => r.cd === cSel ? '#2c2c2a' : SPEEDS[cW].color + 'bb');
  if (!gcChart) {{
    const ctx = document.getElementById('gc-chart').getContext('2d');
    gcChart = new Chart(ctx, {{
      type: 'bar',
      data: {{labels, datasets:[{{data, backgroundColor: bgs, borderRadius:3, borderSkipped:false}}]}},
      options: {{
        indexAxis: 'y', responsive:true, maintainAspectRatio:false,
        plugins: {{legend:{{display:false}}}},
        scales: {{
          x: {{grid:{{color:'#f1efe8'}}, ticks:{{font:{{size:10}}, color:'#888780'}},
               title:{{display:true, text:'도달 가능 쉼터 수', font:{{size:10}}, color:'#888780'}}}},
          y: {{grid:{{display:false}}, ticks:{{font:{{size:10}}, color:'#2c2c2a'}}}},
        }},
      }},
    }});
  }} else {{
    gcChart.data.labels = labels;
    gcChart.data.datasets[0].data = data;
    gcChart.data.datasets[0].backgroundColor = bgs;
    gcChart.update('none');
  }}
}}

// ─── 시간대별 라인차트 ─────────────────────────────────────────────────────
function updateWC() {{
  const code = cSel;
  const key  = cTab === 'cold' ? 'cold' : 'heat';
  const r    = cUnit === 'gu' ? REACH_G : REACH_D;
  const datasets = SPEEDS.map((s, i) => {{
    const data = [15, 30, 45].map(t => r[code]?.[s.id]?.[String(t)]?.[key] ?? 0);
    return {{
      label: s.label,
      data,
      borderColor: s.color,
      backgroundColor: s.color + '22',
      fill: false,
      tension: 0.3,
      borderWidth: i === cW ? 2.5 : 1,
      pointRadius: i === cW ? 4 : 2,
    }};
  }});
  if (!wcChart) {{
    const ctx = document.getElementById('wc-chart').getContext('2d');
    wcChart = new Chart(ctx, {{
      type: 'line',
      data: {{labels:['15분','30분','45분'], datasets}},
      options: {{
        responsive:true, maintainAspectRatio:false,
        plugins: {{legend:{{position:'bottom', labels:{{font:{{size:10}}, boxWidth:12}}}}}},
        scales: {{
          x: {{grid:{{color:'#f1efe8'}}, ticks:{{font:{{size:11}}, color:'#888780'}}}},
          y: {{grid:{{color:'#f1efe8'}}, ticks:{{font:{{size:11}}, color:'#888780'}},
               title:{{display:true, text:'도달 쉼터 수', font:{{size:10}}, color:'#888780'}}}},
        }},
      }},
    }});
  }} else {{
    wcChart.data.datasets = datasets;
    wcChart.update('none');
  }}
}}

// ─── 상세표 ─────────────────────────────────────────────────────────────────
function updateTable() {{
  const sid = SPEEDS[cW].id;
  const rows = GU_META.map(g => {{
    const d  = REACH_G[g.cd]?.[sid]?.[String(cT)];
    const d0 = REACH_G[g.cd]?.g0?.[String(cT)];
    const hCnt  = d  ? d.heat : 0;
    const hCnt0 = d0 ? d0.heat : 0;
    const cCnt  = d  ? d.cold : 0;
    const cCnt0 = d0 ? d0.cold : 0;
    const sel   = g.cd === cSel && cUnit === 'gu';
    return {{...g, hCnt, hCnt0, cCnt, cCnt0, sel}};
  }}).sort((a, b) => (cTab==='cold' ? b.cCnt - a.cCnt : b.hCnt - a.hCnt));
  const maxH = Math.max(...rows.map(r => r.hCnt0)) || 1;
  const maxC = Math.max(...rows.map(r => r.cCnt0)) || 1;
  const mainMax = cTab==='cold' ? maxC : maxH;
  const html = `<table id="tbl">
    <thead><tr>
      <th>자치구</th>
      <th>더위쉼터 수</th><th>한파쉼터 수</th>
      <th>도달 더위쉼터 (일반인 / 선택속도)</th>
      <th>도달 한파쉼터 (일반인 / 선택속도)</th>
      <th>접근성</th>
    </tr></thead>
    <tbody>` +
    rows.map(r => {{
      const mainCnt = cTab==='cold' ? r.cCnt : r.hCnt;
      const grade = mainCnt/mainMax>=.6?'phi':mainCnt/mainMax>=.3?'pmd':'plo';
      const gradeTxt = mainCnt/mainMax>=.6?'양호':mainCnt/mainMax>=.3?'보통':'미흡';
      const fv=v=>Math.round(v);
      return `<tr class="${{r.sel ? 'sel' : ''}}">
        <td>${{r.nm}}</td>
        <td>${{r.heat}}</td><td>${{r.cold}}</td>
        <td>${{fv(r.hCnt0)}} / <b>${{fv(r.hCnt)}}</b></td>
        <td>${{fv(r.cCnt0)}} / <b>${{fv(r.cCnt)}}</b></td>
        <td><span class="pill ${{grade}}">${{gradeTxt}}</span></td>
      </tr>`;
    }}).join('') +
    `</tbody></table>`;
  document.getElementById('tbl-wrap').innerHTML = html;
}}

// ─── 결빙 맵 (11_b3 방식: 제설함 점 + 커버원 + 결빙취약구역) ──────────────
// 결빙 캔버스 레이어: 서울 전체를 붉게 칠한 뒤 제설함 원을 destination-out으로 지움
// → 겹치는 원도 깔끔하게 투명 처리 (evenodd 중복 문제 없음)
const IcingCanvasLayer = L.Layer.extend({{
  initialize: function(buf) {{ this._buf = buf; }},
  onAdd: function(map) {{
    this._map = map;
    const cv = this._cv = document.createElement('canvas');
    cv.style.cssText = 'position:absolute;pointer-events:none;z-index:400';
    map.getPanes().overlayPane.appendChild(cv);
    map.on('moveend zoomend viewreset', this._reset, this);
    this._reset();
  }},
  onRemove: function(map) {{
    this._cv.remove();
    map.off('moveend zoomend viewreset', this._reset, this);
  }},
  setBuf: function(buf) {{ this._buf = buf; if (this._map) this._reset(); }},
  _reset: function() {{
    const map = this._map;
    const tl = map.containerPointToLayerPoint([0, 0]);
    const sz = map.getSize();
    const cv = this._cv;
    cv.style.left = tl.x + 'px';
    cv.style.top = tl.y + 'px';
    cv.width = sz.x; cv.height = sz.y;
    this._draw();
  }},
  _draw: function() {{
    const map = this._map, buf = this._buf;
    const cv = this._cv;
    const sz = map.getSize();
    const tl = map.containerPointToLayerPoint([0, 0]);
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, sz.x, sz.y);

    function proj(lat, lng) {{
      const lp = map.latLngToLayerPoint([lat, lng]);
      return [lp.x - tl.x, lp.y - tl.y];
    }}

    // 1. 서울 외곽 전체를 붉게
    ctx.fillStyle = 'rgba(198,40,40,0.55)';
    ctx.beginPath();
    SEOUL_OUTLINE.forEach(([lng, lat], i) => {{
      const [x, y] = proj(lat, lng);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }});
    ctx.closePath();
    ctx.fill();

    // 2. 제설함 원 영역을 모두 지우기 (destination-out, 겹침도 안전)
    ctx.globalCompositeOperation = 'destination-out';
    const mPerPx = map.distance(
      map.containerPointToLatLng([sz.x/2, sz.y/2]),
      map.containerPointToLatLng([sz.x/2 + 1, sz.y/2])
    );
    const rPx = buf / mPerPx;
    ctx.fillStyle = 'rgba(0,0,0,1)';
    ctx.beginPath();
    for (const b of JISEOL) {{
      const [x, y] = proj(b.lat, b.lng);
      ctx.moveTo(x + rPx, y);
      ctx.arc(x, y, rPx, 0, Math.PI * 2);
    }}
    ctx.fill();
    ctx.globalCompositeOperation = 'source-over';
  }}
}});

let icingLayer = null, covGroup = null, boxesLayer = null, curIceBuf = 100;
const iceOn = {{icing: true, cov: true, boxes: true}};

function initIceMap() {{
  iceMap = L.map('ice-map', {{center:[37.5500,126.9780], zoom:11, zoomAnimation:false}});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{attribution:'© OSM · © CartoDB', maxZoom:19, subdomains:'abcd'}}).addTo(iceMap);

  // 제설함 점 레이어 (툴팁 포함)
  boxesLayer = L.layerGroup();
  JISEOL.forEach(b => {{
    L.circleMarker([b.lat, b.lng], {{
      radius:2, fillColor:'#00E5FF', color:'transparent', fillOpacity:.75
    }}).bindTooltip(`<b>${{b.nm}}</b><br>${{b.addr}}<br><span style="color:#888780">${{b.gu}}</span>`,
      {{direction:'top'}}).addTo(boxesLayer);
  }});

  // 커버원 그룹 (반경에 따라 rebuild)
  covGroup = L.layerGroup();

  buildIcingLayers(100);
  setIceBuf(100, document.getElementById('ibuf100'));
}}

function buildIcingLayers(buf) {{
  // 기존 캔버스 레이어 제거
  if (icingLayer) {{ icingLayer.remove(); icingLayer = null; }}
  icingLayer = new IcingCanvasLayer(buf);
  if (iceOn.icing) icingLayer.addTo(iceMap);

  // 커버원 재구성
  covGroup.clearLayers();
  JISEOL.forEach(b => {{
    L.circle([b.lat, b.lng], {{
      radius: buf, fillColor:'#1565C0', fillOpacity:.12,
      color:'#1E88E5', weight:.25, opacity:.35
    }}).addTo(covGroup);
  }});
  if (iceOn.cov) covGroup.addTo(iceMap);
  if (iceOn.boxes) boxesLayer.addTo(iceMap);
}}

function togIce(key, btn) {{
  iceOn[key] = !iceOn[key];
  btn.classList.toggle('on', iceOn[key]);
  btn.textContent = ({{icing:'결빙취약', cov:'커버원', boxes:'제설함'}})[key] + (iceOn[key]?' ON':' OFF');
  if (!iceMap) return;
  if (key === 'icing') {{
    if (icingLayer) {{ iceOn.icing ? icingLayer.addTo(iceMap) : icingLayer.remove(); }}
  }} else {{
    const lyr = key === 'cov' ? covGroup : boxesLayer;
    if (lyr) iceOn[key] ? lyr.addTo(iceMap) : iceMap.removeLayer(lyr);
  }}
}}

function setIceBuf(buf, btn) {{
  curIceBuf = buf;
  document.getElementById('ibuf100').classList.toggle('on', buf===100);
  document.getElementById('ibuf200').classList.toggle('on', buf===200);
  if (iceMap) buildIcingLayers(buf);
  updateIceCards(buf);
  updateIceNarrative(buf);
}}

function updateIceCards(buf) {{
  const km2  = buf===100 ? ICING_S.icing_100_km2 : ICING_S.icing_200_km2;
  const pct  = buf===100 ? ICING_S.icing_100_pct : ICING_S.icing_200_pct;
  const cov  = +(ICING_S.clean_km2 - km2).toFixed(1);
  const cpct = (100 - pct).toFixed(1);
  document.getElementById('ice-cards').innerHTML = `
    <div class="sc"><div class="sl">도심 기반 면적</div>
      <div class="sv">${{ICING_S.clean_km2}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">행정동 − 한강·산지 제외</div></div>
    <div class="sc"><div class="sl">제설함 커버 구역</div>
      <div class="sv green">${{cov}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">${{cpct}}% · ${{buf}}m 반경</div></div>
    <div class="sc"><div class="sl">결빙 취약 구역</div>
      <div class="sv red">${{km2}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">${{pct}}% · ${{buf}}m 반경</div></div>
    <div class="sc"><div class="sl">제설함 수</div>
      <div class="sv">${{JISEOL.length.toLocaleString()}}</div>
      <div class="ss">서울시 등록 개소</div></div>`;
}}

function updateIceNarrative(buf) {{
  const pct = buf===100 ? ICING_S.icing_100_pct : ICING_S.icing_200_pct;
  const km2 = buf===100 ? ICING_S.icing_100_km2 : ICING_S.icing_200_km2;
  document.getElementById('ice-narrative').innerHTML = `
    <div style="margin-bottom:16px;padding:14px;background:#f5f4f0;border-radius:8px">
      <div style="font-size:32px;font-weight:500;color:#c0392b">${{pct}}%</div>
      <div style="font-size:12px;color:#888780">결빙 취약 비율 (${{buf}}m 제설함 반경 기준)</div>
      <div style="font-size:12px;color:#2c2c2a;margin-top:4px">
        도심 ${{km2}} km²가 제설함 사각지대 — 초동 제설 불가 구역
      </div>
    </div>
    <div style="font-size:12px;color:#5f5e5a;line-height:2">
      겨울 결빙 구역에서 낙상은 보행 속도가 느린 노인에게 치명적입니다.<br>
      보행보조 노인은 낙상 시 골절 위험이 특히 높고 회복 기간도 더 깁니다.<br>
      한파·폭염쉼터와 달리 결빙 위험은 <b>이동 경로 자체</b>의 문제입니다.
    </div>`;
}}

// ─── 툴팁 ───────────────────────────────────────────────────────────────────
const tipEl = document.getElementById('tip-box');
function showTip(e, html) {{
  tipEl.innerHTML = html;
  tipEl.style.display = 'block';
  moveTip(e);
}}
function moveTip(e) {{
  tipEl.style.left = (e.clientX + 14) + 'px';
  tipEl.style.top  = (e.clientY - 10) + 'px';
}}
function hideTip() {{ tipEl.style.display = 'none'; }}
document.addEventListener('mousemove', e => {{ if (tipEl.style.display !== 'none') moveTip(e); }});

// ─── 초기화 ─────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {{
  buildSelector();
  initMap();
  updateAll();
}});
</script>
</body>
</html>"""

out = OUT_DIR / "16_climate_shelter_dashboard.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

log.info(f"✅ 출력 → {out}")
log.info(f"   파일 크기: {out.stat().st_size // 1024} KB")
