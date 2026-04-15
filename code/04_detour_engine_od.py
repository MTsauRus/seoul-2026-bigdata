"""
04_detour_engine_od.py
======================
끊어진 서울 — OD쌍 기반 우회비율 분석 엔진

[기존 수직샘플링 방식의 문제]
  - 철도 수직 250m 테스트 포인트가 강·산·공원에 떨어짐
  - 실제 사람이 이동하는 경로가 아님

[이 방식: OD쌍 (Origin-Destination Pair)]
  - Origin(출발지): 집계구 중심점 (실제 주거지역)
  - Destination(도착지): 반대편 집계구 중심점
  - "직선이 철도를 교차하는 쌍"만 유효 → 강/산 자동 제외
  - 인구 가중 평균으로 구간별 단절 강도 집계

[처리 흐름]
  1. 집계구 폴리곤 (SHP) + 생활인구 (CSV) → 인구가중 중심점
  2. 지상철도 (캐시) + 보행망 (캐시) 로드
  3. 철도 2km 이내 집계구만 필터 + 보행 노드에 snap
  4. 보행망 서브그래프 추출 (계산 속도 최적화)
  5. 철도 구간별로 양쪽 집계구 K개씩 선정 → OD쌍 생성
  6. 각 쌍: 직선이 철도 교차 확인 → 보행 최단거리 계산
  7. 구간별 인구가중 우회비율 집계
  8. 색상 지도 출력

결과:
  output/detour_od_map.png
  output/detour_od_interactive.html
  cache/detour_od_results.pkl

[성령 학습 포인트]
- STRtree: 수만 개 도형 중 겹치는 것을 O(log N)으로 찾는 공간 인덱스
- 서브그래프: 전체 보행망 대신 철도 주변 2km만 잘라서 계산 → 10배 빠름
- 인구가중 평균: 각 측정값에 인구수를 곱해 합산 / 총 인구
  → 사람이 많은 지역의 불편함을 더 크게 반영
"""

import json
import pickle
import platform
import warnings
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import networkx as nx
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from pyproj import Transformer
from scipy.spatial import KDTree
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")

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

_to_wgs84 = Transformer.from_crs(5179, 4326, always_xy=True)
def _xy_to_latlon(x, y):
    lon, lat = _to_wgs84.transform(x, y)
    return [lat, lon]

# 서울 25개 자치구 코드 → 이름 (ADM_CD 앞 5자리, 통계청 행정동 코드 체계)
# 11 + 010~250 (10 단위, 총 25개)
SEOUL_GU = {
    "11010": "종로구",   "11020": "중구",     "11030": "용산구",
    "11040": "성동구",   "11050": "광진구",   "11060": "동대문구",
    "11070": "중랑구",   "11080": "성북구",   "11090": "강북구",
    "11100": "도봉구",   "11110": "노원구",   "11120": "은평구",
    "11130": "서대문구", "11140": "마포구",   "11150": "양천구",
    "11160": "강서구",   "11170": "구로구",   "11180": "금천구",
    "11190": "영등포구", "11200": "동작구",   "11210": "관악구",
    "11220": "서초구",   "11230": "강남구",   "11240": "송파구",
    "11250": "강동구",
}
def _gu_name(adm_cd: str) -> str:
    """행정동코드(8자리) 앞 5자리로 자치구명 반환"""
    return SEOUL_GU.get(str(adm_cd)[:5], "서울시")

# ─────────────────────────────────────────────────────────────
# 0. 경로 설정
# ─────────────────────────────────────────────────────────────
DATA_DIR  = Path("data")
OUT_DIR   = Path("output")
CACHE_DIR = Path("cache")
OUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

SHP_PATH = DATA_DIR / "bnd_oa_11_2025_2Q" / "bnd_oa_11_2025_2Q.shp"
CSV_PATH = DATA_DIR / "LOCAL_PEOPLE_20260409.csv"

# 분석 파라미터
RAIL_BUFFER_M = 2000  # 철도 양쪽 2km 내 집계구만 고려
MAX_OD_DIST_M = 2000  # OD쌍 최대 직선거리 (도보 25분 기준)
MAX_SNAP_M    = 150   # 집계구 중심 → 보행 노드 최대 스냅 거리 (초과 시 산/강)
K_NEAREST     = 5     # 구간당 반대편 최근접 집계구 수
TIME_BAND     = 0     # 생활인구 시간대 (0 = 일평균)
RAIL_SAMPLE_M = 200   # 철도 따라 구간 샘플 간격
RATIO_CAP     = 8.0

# ─────────────────────────────────────────────────────────────
# 1. 집계구 + 생활인구 로드
# ─────────────────────────────────────────────────────────────
def load_census_blocks():
    """
    집계구 폴리곤 + 생활인구 조인 → 인구가중 중심점 GeoDataFrame
    반환: GeoDataFrame with columns [oa_cd, population, geometry(=centroid), EPSG:5179]
    """
    cache_f = CACHE_DIR / "census_blocks_v2.gpkg"
    if cache_f.exists():
        print("[CACHE] census_blocks_v2.gpkg 로드")
        return gpd.read_file(cache_f)

    print("[1/5] 집계구 데이터 로드 중...")

    # ── 집계구 경계 (SHP, EPSG:5179) ────────────────────────────
    oa = gpd.read_file(SHP_PATH, encoding="euc-kr")
    # 컬럼 정리
    oa = oa.rename(columns={"TOT_OA_CD": "oa_cd", "ADM_CD": "adm_cd"})
    oa["oa_cd"] = oa["oa_cd"].astype(str).str.strip()
    print(f"  집계구 폴리곤: {len(oa)}개")

    # ── 생활인구 CSV (시간대=0 만 사용) ─────────────────────────
    # 458,091행 → 19,030행으로 필터 (시간대=0)
    pop = pd.read_csv(
        CSV_PATH,
        encoding="euc-kr",
        usecols=["시간대구분", "집계구코드", "총생활인구수"],
        dtype={"집계구코드": str},
    )
    pop = pop[pop["시간대구분"] == TIME_BAND].copy()
    pop = pop.rename(columns={"집계구코드": "oa_cd", "총생활인구수": "population"})
    pop["oa_cd"] = pop["oa_cd"].astype(str).str.strip()
    # '*' (비밀보호) 처리: 0으로 대체
    pop["population"] = pd.to_numeric(pop["population"], errors="coerce").fillna(0)
    print(f"  생활인구 집계구: {len(pop)}개")

    # ── 조인 ────────────────────────────────────────────────────
    merged = oa.merge(pop[["oa_cd", "population"]], on="oa_cd", how="left")
    merged["population"] = merged["population"].fillna(0)

    # ── 자치구명 디코딩 (adm_cd 앞 5자리 → 구 이름) ─────────────
    merged["gu_name"] = merged["adm_cd"].astype(str).apply(_gu_name)

    # ── 중심점으로 변환 ──────────────────────────────────────────
    # centroid = 폴리곤 무게중심 (그 집계구 대표 좌표)
    merged["geometry"] = merged.geometry.centroid
    result = merged[["oa_cd", "adm_cd", "gu_name", "population", "geometry"]].copy()
    result = gpd.GeoDataFrame(result, crs=5179)

    print(f"  최종 집계구 중심점: {len(result)}개, 총인구: {result['population'].sum():,.0f}")
    result.to_file(cache_f, driver="GPKG")
    return result


# ─────────────────────────────────────────────────────────────
# 2. 지상철도 + 보행망 로드 (기존 캐시 재사용)
# ─────────────────────────────────────────────────────────────
def load_rail():
    p = CACHE_DIR / "surface_rail.gpkg"
    if not p.exists():
        raise FileNotFoundError("cache/surface_rail.gpkg 없음 → make_detour_map_ver2.py 먼저 실행")
    print("[CACHE] surface_rail.gpkg 로드")
    return gpd.read_file(p)

def load_walk_graph():
    p = CACHE_DIR / "walk_graph.pkl"
    if not p.exists():
        raise FileNotFoundError("cache/walk_graph.pkl 없음 → make_detour_map_ver2.py 먼저 실행")
    print("[CACHE] walk_graph.pkl 로드")
    with open(p, "rb") as f:
        return pickle.load(f)


# ─────────────────────────────────────────────────────────────
# 3. 분석 준비: 필터링 + 서브그래프
# ─────────────────────────────────────────────────────────────
def prepare(oa_gdf, rail_gdf, G):
    print("[2/5] 분석 준비 (필터링 + 서브그래프)...")

    # ── 철도 2km 버퍼 내 집계구만 ───────────────────────────────
    rail_union  = unary_union(rail_gdf.geometry)
    rail_buffer = rail_union.buffer(RAIL_BUFFER_M)
    oa_near = oa_gdf[oa_gdf.geometry.within(rail_buffer)].copy()
    print(f"  철도 {RAIL_BUFFER_M//1000}km 이내 집계구: {len(oa_near)}개")

    # ── 각 집계구 중심을 보행 노드에 snap ───────────────────────
    # KDTree: N개 노드 좌표를 트리로 만들어 O(log N) 최근접 검색
    node_ids    = list(G.nodes())
    node_coords = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in node_ids])
    tree        = KDTree(node_coords)

    snapped = []
    for _, row in oa_near.iterrows():
        dist, idx = tree.query([row.geometry.x, row.geometry.y])
        if dist > MAX_SNAP_M:
            continue  # 산/강/공원 → 근처에 도로 없음 → 제외
        snapped.append({
            "oa_cd":      row["oa_cd"],
            "gu_name":    row.get("gu_name", "서울시"),
            "population": row["population"],
            "x":          row.geometry.x,
            "y":          row.geometry.y,
            "node":       node_ids[idx],
            "snap_dist":  dist,
        })

    print(f"  보행망 snap 성공: {len(snapped)}개 (제외: {len(oa_near)-len(snapped)}개)")

    # ── 서브그래프: 철도 2km 내 노드만 ─────────────────────────
    # 전체 그래프 대신 관련 구역만 사용 → Dijkstra 10배 빠름
    nodes_in_buffer = [
        n for n in G.nodes()
        if Point(G.nodes[n]["x"], G.nodes[n]["y"]).within(rail_buffer)
    ]
    G_sub = G.subgraph(nodes_in_buffer).copy()
    print(f"  서브그래프: {G_sub.number_of_nodes():,} 노드 (전체: {G.number_of_nodes():,})")

    return snapped, G_sub, rail_union


# ─────────────────────────────────────────────────────────────
# 4. OD쌍 생성 + 우회비율 계산
# ─────────────────────────────────────────────────────────────
def compute_od_detour(snapped, G_sub, rail_gdf):
    """
    OD쌍 기반 우회비율 계산.

    각 철도 구간(200m 샘플)마다:
      - 구간 중심에서 가장 가까운 집계구 K개를 양쪽에서 선정
      - 좌측 집계구 × 우측 집계구 = K² 쌍 생성
      - 직선 A→B가 철도를 교차하는 쌍만 유효
      - 유효 쌍의 보행 최단거리 계산 → 우회비율
    """
    print(f"[3/5] OD쌍 우회비율 계산 중 (구간 {RAIL_SAMPLE_M}m마다, K={K_NEAREST})...")

    # STRtree: 철도 도형들로 공간 인덱스 구축 (교차 판정 빠르게)
    rail_geoms  = list(rail_gdf.geometry)
    rail_strtree = STRtree(rail_geoms)

    # 집계구 중심점 좌표 배열 (OD 최근접 탐색용)
    oa_arr  = np.array([[s["x"], s["y"]] for s in snapped])
    oa_tree = KDTree(oa_arr)

    results = []  # {rail_pt_x, rail_pt_y, ratio, pop_weight, od_pairs}

    total_lines = sum(
        1 if g.geom_type == "LineString" else len(list(g.geoms))
        for g in rail_gdf.geometry
    )
    processed = 0
    skipped_nopath = 0
    skipped_nocross = 0

    for _, row in rail_gdf.iterrows():
        geom  = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]

        for line in lines:
            processed += 1
            total_len = line.length
            sample_dists = np.arange(RAIL_SAMPLE_M / 2, total_len, RAIL_SAMPLE_M)

            for d in sample_dists:
                pt = line.interpolate(d)

                # 접선 방향 → 수직 단위벡터 (좌/우 구분)
                p1 = line.interpolate(max(0.0, d - 20))
                p2 = line.interpolate(min(total_len, d + 20))
                tx, ty = p2.x - p1.x, p2.y - p1.y
                tlen = (tx**2 + ty**2) ** 0.5
                if tlen < 1.0:
                    continue
                nx_, ny_ = -ty / tlen, tx / tlen

                # 양쪽 K개 최근접 집계구 탐색 (방향별 편향점에서 검색)
                search_dist = MAX_OD_DIST_M + 500  # 약간 여유
                left_anchor  = np.array([pt.x + nx_ * 500, pt.y + ny_ * 500])
                right_anchor = np.array([pt.x - nx_ * 500, pt.y - ny_ * 500])

                _, left_idxs  = oa_tree.query(left_anchor,  k=K_NEAREST * 3)
                _, right_idxs = oa_tree.query(right_anchor, k=K_NEAREST * 3)

                # 실제 거리로 재필터
                left_cands  = [i for i in left_idxs
                               if np.linalg.norm(oa_arr[i] - [pt.x, pt.y]) <= MAX_OD_DIST_M][:K_NEAREST]
                right_cands = [i for i in right_idxs
                               if np.linalg.norm(oa_arr[i] - [pt.x, pt.y]) <= MAX_OD_DIST_M][:K_NEAREST]

                if not left_cands or not right_cands:
                    continue

                seg_ratios = []
                seg_weights = []
                seg_od_pairs = []

                for li in left_cands:
                    for ri in right_cands:
                        if li == ri:
                            continue
                        oa_l = snapped[li]
                        oa_r = snapped[ri]

                        # OD 직선거리 필터
                        straight = np.linalg.norm(
                            [oa_l["x"] - oa_r["x"], oa_l["y"] - oa_r["y"]]
                        )
                        if straight < 50 or straight > MAX_OD_DIST_M:
                            continue

                        # 직선 A→B 가 철도를 실제로 교차하는지 확인
                        line_ab = LineString(
                            [(oa_l["x"], oa_l["y"]), (oa_r["x"], oa_r["y"])]
                        )
                        candidates = rail_strtree.query(line_ab)
                        crosses = any(
                            line_ab.crosses(rail_geoms[c]) or line_ab.intersects(rail_geoms[c])
                            for c in candidates
                        )
                        if not crosses:
                            skipped_nocross += 1
                            continue

                        # 보행 최단경로 (경로 노드 목록 + 거리 동시 반환)
                        # single_source_dijkstra: 거리와 경로를 한 번에 계산
                        try:
                            walk_len, path_nodes = nx.single_source_dijkstra(
                                G_sub, oa_l["node"], oa_r["node"], weight="length"
                            )
                        except (nx.NetworkXNoPath, nx.NodeNotFound):
                            skipped_nopath += 1
                            continue

                        ratio = min(walk_len / straight, RATIO_CAP)
                        pop_w = max(oa_l["population"] + oa_r["population"], 1.0)

                        # 경로 노드 → WGS84 좌표 (경유지 많으면 50개로 축약)
                        step = max(1, len(path_nodes) // 50)
                        path_wgs84 = [
                            _xy_to_latlon(G_sub.nodes[n]["x"], G_sub.nodes[n]["y"])
                            for n in path_nodes[::step]
                        ]
                        # 마지막 점 누락 방지
                        if path_nodes:
                            last = path_nodes[-1]
                            path_wgs84.append(
                                _xy_to_latlon(G_sub.nodes[last]["x"], G_sub.nodes[last]["y"])
                            )

                        seg_ratios.append(ratio)
                        seg_weights.append(pop_w)
                        seg_od_pairs.append({
                            "left_wgs84":  _xy_to_latlon(oa_l["x"], oa_l["y"]),
                            "right_wgs84": _xy_to_latlon(oa_r["x"], oa_r["y"]),
                            "left_gu":     oa_l["gu_name"],
                            "right_gu":    oa_r["gu_name"],
                            "straight_m":  int(straight),
                            "walk_m":      int(walk_len),
                            "ratio":       round(ratio, 3),
                            "path_wgs84":  path_wgs84,
                        })

                if not seg_ratios:
                    continue

                # 인구가중 평균 우회비율
                total_w   = sum(seg_weights)
                w_ratio   = sum(r * w for r, w in zip(seg_ratios, seg_weights)) / total_w
                extra_pop = sum(
                    (r - 1.0) * (p["straight_m"]) * w
                    for r, w, p in zip(seg_ratios, seg_weights, seg_od_pairs)
                ) / total_w  # 인구 × 여분 거리 (단절 심각도)

                results.append({
                    "x":         pt.x,
                    "y":         pt.y,
                    "ratio":     round(w_ratio, 3),
                    "extra_pop": round(extra_pop, 1),
                    "n_pairs":   len(seg_ratios),
                    "od_pairs":  seg_od_pairs,
                    "name":      row.get("name", "미상"),
                })

    print(f"  완료: {len(results)}개 유효 구간 포인트")
    print(f"  (교차 미통과: {skipped_nocross}, 경로 없음: {skipped_nopath})")
    if results:
        ratios = [r["ratio"] for r in results]
        print(f"  우회비율 — 중앙: {np.median(ratios):.2f}, 최대: {max(ratios):.2f}")
    return results


# ─────────────────────────────────────────────────────────────
# 5. 시각화 (PNG + Folium HTML)
# ─────────────────────────────────────────────────────────────
def make_maps(results, rail_gdf):
    print("[4/5] 지도 렌더링...")
    if not results:
        print("  ⚠️ 결과 없음 — 지도 생성 건너뜀")
        return

    cmap = LinearSegmentedColormap.from_list(
        "detour", ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026", "#6b0011"]
    )
    norm = mcolors.Normalize(vmin=1.0, vmax=RATIO_CAP)

    # ── PNG ──────────────────────────────────────────────────────
    BG, BORDER = "#0d1117", "#30363d"
    fig, ax = plt.subplots(figsize=(14, 14), facecolor=BG)
    ax.set_facecolor(BG)

    rail_gdf.plot(ax=ax, color="#21262d", linewidth=4, alpha=0.8, zorder=2)

    xs      = np.array([r["x"] for r in results])
    ys      = np.array([r["y"] for r in results])
    ratios  = np.array([r["ratio"] for r in results])
    names   = [r["name"] for r in results]

    # LineCollection: 구간마다 색 다르게
    for uname in dict.fromkeys(names):
        idxs = [i for i, n in enumerate(names) if n == uname]
        if len(idxs) < 2:
            continue
        sx, sy, sr = xs[idxs], ys[idxs], ratios[idxs]
        segs = [[[sx[i], sy[i]], [sx[i+1], sy[i+1]]] for i in range(len(sx)-1)]
        sc_r = (sr[:-1] + sr[1:]) / 2.0
        lc = LineCollection(segs, cmap=cmap, norm=norm, linewidth=6, zorder=3, alpha=0.92)
        lc.set_array(sc_r)
        ax.add_collection(lc)

    sc = ax.scatter(xs, ys, c=ratios, cmap=cmap, norm=norm, s=25, alpha=0.5, zorder=4, linewidths=0)
    cbar = plt.colorbar(sc, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label(f"우회비율 (1.0=단절없음, {RATIO_CAP:.0f}.0={RATIO_CAP:.0f}배 우회)",
                   color="white", fontsize=10)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=9)
    cbar.outline.set_edgecolor(BORDER)

    ax.set_title("끊어진 서울 — 지상철도 보행 단절 지도 (OD쌍 기반)",
                 color="white", fontsize=17, fontweight="bold", pad=15, loc="left")
    ax.text(0.01, 0.97,
            f"집계구 중심점 쌍 ({MAX_OD_DIST_M//1000}km 이내, 직선이 철도 교차하는 쌍만)\n"
            "인구가중 우회비율 | 진한 빨강 = 단절이 심한 구간",
            transform=ax.transAxes, color="#8b949e", fontsize=9, va="top")
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout(pad=0.5)
    png_path = OUT_DIR / "detour_od_map.png"
    plt.savefig(png_path, dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  PNG: {png_path}")

    # ── Folium HTML ───────────────────────────────────────────────
    html_path = _make_folium(results, rail_gdf, cmap, norm)
    print(f"  HTML: {html_path}")
    print(f"\n✅ 완료")


def _make_folium(results, rail_gdf, cmap, norm):
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
        # 클릭 시 보여줄 OD쌍은 최악의 쌍 1개 (ratio 최대)
        worst = max(r["od_pairs"], key=lambda p: p["ratio"]) if r["od_pairs"] else None
        marker_data.append({
            "latlng":   latlng,
            "ratio":    r["ratio"],
            "name":     r["name"],
            "n_pairs":  r["n_pairs"],
            "worst":    worst,  # path_wgs84, left_gu, right_gu 포함
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
        우회비율 필터 (OD쌍 기반)
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
  if (!map) {{ console.error('map not found'); return; }}

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

    /* ② 실제 보행 경로 (컬러 실선, 경유지 전부 표시) */
    if (w.path_wgs84 && w.path_wgs84.length > 1) {{
      L.polyline(w.path_wgs84, {{
        color: col, weight: 5, opacity: 0.92
      }}).bindTooltip('실제 보행 ' + w.walk_m + 'm').addTo(routeLayer);
    }}

    /* ③ 출발지 마커 (초록) */
    L.circleMarker(w.left_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#00e676', fillOpacity:1.0
    }}).bindTooltip('출발: ' + (w.left_gu || '?')).addTo(routeLayer);

    /* ④ 도착지 마커 (빨강) */
    L.circleMarker(w.right_wgs84, {{
      radius:10, color:'#fff', weight:2, fillColor:'#ff5252', fillOpacity:1.0
    }}).bindTooltip('도착: ' + (w.right_gu || '?')).addTo(routeLayer);

    /* ⑤ 정보 팝업 */
    var leftGu  = w.left_gu  || '서울시';
    var rightGu = w.right_gu || '서울시';
    var sameGu  = (leftGu === rightGu) ? leftGu : leftGu + ' ↔ ' + rightGu;
    L.popup({{ maxWidth:280 }})
      .setLatLng(d.latlng)
      .setContent(
        '<div style="font-family:-apple-system,sans-serif;padding:4px 6px;min-width:220px">' +
        '<div style="font-size:15px;font-weight:700;margin-bottom:4px">' + d.name + '</div>' +
        '<div style="color:#555;font-size:12px;margin-bottom:8px">📍 ' + sameGu + '</div>' +
        '<hr style="margin:6px 0;border-color:#eee">' +
        '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
        '<tr><td style="color:#888;padding:2px 0">분석 OD쌍</td>' +
            '<td style="text-align:right;font-weight:600">' + d.n_pairs + '개</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">📏 직선거리</td>' +
            '<td style="text-align:right;font-weight:600">' + w.straight_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">🚶 실제 보행</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' + w.walk_m + 'm</td></tr>' +
        '<tr><td style="color:#888;padding:2px 0">➕ 추가 거리</td>' +
            '<td style="text-align:right;font-weight:600;color:' + col + '">' +
            (w.walk_m - w.straight_m) + 'm 더</td></tr>' +
        '</table>' +
        '<div style="margin-top:8px;padding:6px;background:#f8f8f8;border-radius:4px;text-align:center">' +
        '<span style="font-size:22px;font-weight:700;color:' + col + '">' + d.ratio.toFixed(2) + '배</span>' +
        '<span style="color:#888;font-size:12px"> 우회비율 (인구가중)</span>' +
        '</div>' +
        '<div style="margin-top:6px;font-size:11px;color:#aaa">' +
        '● 초록=출발지 · 빨강=도착지 · 점선=직선 · 실선=실제경로</div>' +
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

    html_path = OUT_DIR / "detour_od_interactive.html"
    m.save(html_path)
    return html_path


# ─────────────────────────────────────────────────────────────
# 실행 진입점
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. 집계구 + 생활인구
    oa = load_census_blocks()

    # 2. 지상철도 + 보행망 (기존 캐시)
    rail = load_rail()
    G    = load_walk_graph()

    # 3. 분석 준비
    snapped, G_sub, rail_union = prepare(oa, rail, G)

    # 4. OD쌍 우회비율 계산 (캐시)
    results_pkl = CACHE_DIR / "detour_od_results_v2.pkl"
    if results_pkl.exists():
        print("[CACHE] detour_od_results.pkl 로드")
        with open(results_pkl, "rb") as f:
            results = pickle.load(f)
    else:
        print("[5/5] OD쌍 계산 시작...")
        results = compute_od_detour(snapped, G_sub, rail)
        with open(results_pkl, "wb") as f:
            pickle.dump(results, f)

    # 5. 지도
    make_maps(results, rail)
