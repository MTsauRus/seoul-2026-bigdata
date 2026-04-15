"""
make_detour_map.py
==================
끊어진 서울 — 지상철도 우회비율 색상 지도 (오늘의 최종 결과물)

파이프라인:
  1. OSM에서 서울 지상철도 추출 (화이트리스트 + 터널 필터, 캐시)
  2. 철도 주변 2km 버퍼 보행망 구축 (캐시)
  3. 철도 따라 150m마다 샘플 → 수직 양쪽 250m 보행 최단거리 → 우회비율
  4. 우회비율로 철도 라인 색상 코딩 (진할수록 더 많이 우회)

실행: python code/make_detour_map.py
결과: output/detour_map.png
캐시: cache/ 폴더 (두 번째 실행부터 3분 내로 완료)

[성령 학습 포인트]
- 우회비율(Detour Ratio) = 실제 보행거리 / 직선거리
  · 1.0 = 바로 건너갈 수 있음 (단절 없음)
  · 5.0 = 직선 500m인데 2500m를 걸어야 함
- KDTree: 수천 개의 보행 노드 중 가장 가까운 것을 O(log N)으로 찾는 구조
- LineCollection: matplotlib에서 각 선 구간마다 다른 색을 한 번에 그리는 방법

사전 설치:
  pip install osmnx geopandas networkx matplotlib scipy
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
import osmnx as ox
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from pyproj import Transformer
from scipy.spatial import KDTree
from shapely.ops import unary_union

# EPSG:5179 → WGS84 변환기 (모듈 레벨에서 한 번만 생성)
_to_wgs84 = Transformer.from_crs(5179, 4326, always_xy=True)

def _xy_to_latlon(x, y):
    """EPSG:5179 (x, y) → [lat, lon] for Folium"""
    lon, lat = _to_wgs84.transform(x, y)
    return [lat, lon]

warnings.filterwarnings("ignore")

# ── 한글 폰트 설정 (macOS/Windows/Linux 자동 감지) ─────────────
def _setup_korean_font():
    sys = platform.system()
    if sys == "Darwin":
        plt.rcParams["font.family"] = "AppleGothic"
    elif sys == "Windows":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        available = {f.name for f in fm.fontManager.ttflist}
        for candidate in ("NanumGothic", "UnDotum", "DejaVu Sans"):
            if candidate in available:
                plt.rcParams["font.family"] = candidate
                break
    plt.rcParams["axes.unicode_minus"] = False

_setup_korean_font()

# ─────────────────────────────────────────────────────────────
# 0. 설정
# ─────────────────────────────────────────────────────────────
PLACE = "Seoul, South Korea"
OUT_DIR = Path("output")
CACHE_DIR = Path("cache")
OUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

SAMPLE_M = 150       # 철도 따라 150m마다 샘플링
PERP_M = 250         # 수직 방향 250m 떨어진 곳에 테스트 포인트
BUFFER_M = 2000      # 철도 양옆 2km 범위 보행망만 구축 (전체 서울 대비 훨씬 빠름)
RATIO_CAP = 8.0      # 우회비율 최댓값 (이 이상은 모두 같은 진한색)

# ROADMAP 결정 §3-4, §3-8: 지상 노선 화이트리스트 + 지하 노선 블랙리스트
SURFACE_WHITELIST = [
    "경부선", "경원선", "경의선", "경춘선", "중앙선",
    "경인선", "안산선", "수인선", "용산선",
    "경의중앙선", "수색객차출발선", "장항선",
]
# §3-8: "신분당선" 완전일치 (substring 버그 방지)
UNDERGROUND_BLACKLIST_EXACT = ["신분당선"]
UNDERGROUND_BLACKLIST_CONTAINS = [
    "수도권 전철 1호선", "수도권 전철 2호선", "수도권 전철 3호선",
    "수도권 전철 4호선", "수도권 전철 5호선", "수도권 전철 6호선",
    "수도권 전철 7호선", "수도권 전철 8호선", "수도권 전철 9호선",
    "수도권광역급행철도",
]


# ─────────────────────────────────────────────────────────────
# 1. 지상철도 추출
# ─────────────────────────────────────────────────────────────
def load_surface_rails():
    cache_f = CACHE_DIR / "surface_rail.gpkg"
    if cache_f.exists():
        print("[CACHE] surface_rail.gpkg 로드")
        return gpd.read_file(cache_f)

    print("[1/4] OSM에서 서울 철도 다운로드 중 (5~10분)...")
    rail_tags = {"railway": ["rail", "light_rail", "narrow_gauge"]}
    rail_raw = ox.features_from_place(PLACE, tags=rail_tags)
    rail_raw = rail_raw[
        rail_raw.geometry.type.isin(["LineString", "MultiLineString"])
    ].copy()
    print(f"  raw 피처: {len(rail_raw)}개")

    # 서울 행정경계로 strict clip
    seoul = ox.geocode_to_gdf(PLACE)
    rail_raw = gpd.clip(rail_raw, seoul)

    # EPSG:5179 (한국 미터 좌표계)로 변환
    rail_m = rail_raw.to_crs(epsg=5179).copy()

    # ── 터널 태그 필터 (ROADMAP §3-7) ──────────────────────────
    def is_tunnel(row):
        if str(row.get("tunnel", "")).lower() in ("yes", "building_passage", "culvert"):
            return True
        try:
            if int(row.get("layer", 0)) < 0:
                return True
        except (ValueError, TypeError):
            pass
        if str(row.get("covered", "")).lower() == "yes":
            return True
        return False

    tunnel_mask = rail_m.apply(is_tunnel, axis=1)

    # ── 노선명 화이트리스트/블랙리스트 (ROADMAP §3-8) ──────────
    def classify_by_name(name_val):
        n = str(name_val) if name_val is not None and str(name_val) != "nan" else ""
        # 신분당선 완전일치 (substring "분당선" 포함 버그 방지)
        if n in UNDERGROUND_BLACKLIST_EXACT:
            return "underground"
        if any(u in n for u in UNDERGROUND_BLACKLIST_CONTAINS):
            return "underground"
        if any(s in n for s in SURFACE_WHITELIST):
            return "surface"
        return "unknown"

    name_col = rail_m["name"] if "name" in rail_m.columns else None
    if name_col is not None:
        rail_m["_cls"] = name_col.apply(classify_by_name)
    else:
        rail_m["_cls"] = "unknown"

    # 지상 = (터널 태그 없고 블랙리스트 아님) 또는 화이트리스트 명시
    surface_mask = (
        (~tunnel_mask & (rail_m["_cls"] != "underground"))
        | (rail_m["_cls"] == "surface")
    )
    surface = rail_m[surface_mask].copy()

    # name 컬럼 정리
    if "name" in surface.columns:
        surface["name"] = surface["name"].fillna("미상")
    else:
        surface["name"] = "미상"

    result = surface[["name", "geometry"]].copy()
    km = result.geometry.length.sum() / 1000
    print(f"  지상철도: {len(result)}개 피처, 총 {km:.1f} km (공식: 101.2 km)")
    if abs(km - 101.2) / 101.2 > 0.3:
        print(f"  ⚠️  오차 {abs(km-101.2):.1f}km (>30%) → 화이트리스트 조정 필요")

    result.to_file(cache_f, driver="GPKG")
    return result


# ─────────────────────────────────────────────────────────────
# 2. 보행 네트워크 구축
# ─────────────────────────────────────────────────────────────
def load_walk_graph(rail_gdf):
    cache_f = CACHE_DIR / "walk_graph.pkl"
    if cache_f.exists():
        print("[CACHE] walk_graph.pkl 로드")
        with open(cache_f, "rb") as f:
            return pickle.load(f)

    print(f"[2/4] 보행 네트워크 다운로드 중 (철도 ±{BUFFER_M//1000}km 버퍼, 20~40분)...")
    # 철도 양옆 BUFFER_M 버퍼 → 서울 전체 대신 관련 구역만 다운로드
    buffer_union = unary_union(rail_gdf.geometry.buffer(BUFFER_M))
    buffer_wgs = (
        gpd.GeoSeries([buffer_union], crs=5179).to_crs(4326).iloc[0]
    )

    G = ox.graph_from_polygon(buffer_wgs, network_type="walk")
    G = ox.project_graph(G, to_crs="EPSG:5179")

    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    print(f"  보행 그래프: {n_nodes:,} 노드, {n_edges:,} 엣지")

    with open(cache_f, "wb") as f:
        pickle.dump(G, f)
    return G


# ─────────────────────────────────────────────────────────────
# 3. 우회비율 계산
# ─────────────────────────────────────────────────────────────
def compute_detour_ratios(rail_gdf, G):
    """
    각 지상철도를 SAMPLE_M마다 샘플링하여 수직 방향 PERP_M 양쪽 보행 최단거리를 계산.
    반환: list of dict {x, y, ratio, name}  (EPSG:5179 좌표)
    """
    print(f"[3/4] 우회비율 계산 중 (샘플 간격 {SAMPLE_M}m, 수직거리 {PERP_M}m)...")

    # KDTree로 빠른 최근접 노드 조회
    node_ids = list(G.nodes())
    node_coords = np.array(
        [[G.nodes[n]["x"], G.nodes[n]["y"]] for n in node_ids]
    )
    tree = KDTree(node_coords)

    def nearest_node(px, py):
        _, idx = tree.query([px, py])
        return node_ids[idx]

    results = []
    total = len(rail_gdf)

    for fi, (_, row) in enumerate(rail_gdf.iterrows()):
        geom = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        line_results = []

        for line in lines:
            total_len = line.length
            # SAMPLE_M 간격으로 샘플 (라인 중간부터 시작)
            distances = np.arange(SAMPLE_M / 2, total_len, SAMPLE_M)

            for d in distances:
                pt = line.interpolate(d)

                # 접선 방향 추정 (전후 ±20m 점)
                p1 = line.interpolate(max(0.0, d - 20))
                p2 = line.interpolate(min(total_len, d + 20))
                tx, ty = p2.x - p1.x, p2.y - p1.y
                tlen = (tx**2 + ty**2) ** 0.5
                if tlen < 1.0:
                    continue

                # 수직 단위벡터 (좌/우)
                nx_, ny_ = -ty / tlen, tx / tlen

                # 수직 방향 PERP_M 테스트 포인트
                left_pt = (pt.x + nx_ * PERP_M, pt.y + ny_ * PERP_M)
                right_pt = (pt.x - nx_ * PERP_M, pt.y - ny_ * PERP_M)

                left_node = nearest_node(*left_pt)
                right_node = nearest_node(*right_pt)

                if left_node == right_node:
                    continue

                try:
                    # single_source_dijkstra: 경로 길이 + 경로 노드 목록을 한 번에 반환
                    path_len, path_nodes = nx.single_source_dijkstra(
                        G, left_node, right_node, weight="length"
                    )
                    straight = 2.0 * PERP_M
                    ratio = min(path_len / straight, RATIO_CAP)
                    # 보행 경로를 WGS84 좌표 리스트로 변환
                    path_wgs84 = [
                        _xy_to_latlon(G.nodes[n]["x"], G.nodes[n]["y"])
                        for n in path_nodes
                    ]
                except nx.NetworkXNoPath:
                    path_len = RATIO_CAP * straight
                    ratio = RATIO_CAP
                    path_wgs84 = []

                line_results.append({
                    "x": pt.x,
                    "y": pt.y,
                    "ratio": ratio,
                    "name": row.get("name", "미상"),
                    "straight_m": int(2 * PERP_M),
                    "actual_m": int(min(path_len, RATIO_CAP * 2 * PERP_M)),
                    "left_wgs84": _xy_to_latlon(*left_pt),
                    "right_wgs84": _xy_to_latlon(*right_pt),
                    "path_wgs84": path_wgs84,
                })

        results.extend(line_results)
        name = row.get("name", "?")
        med = (
            np.median([r["ratio"] for r in line_results])
            if line_results
            else 0
        )
        print(f"  [{fi+1}/{total}] {name}: {len(line_results)}점, 중앙 우회비율={med:.2f}")

    if results:
        all_ratios = [r["ratio"] for r in results]
        print(
            f"\n  합계 {len(results)} 샘플 포인트"
            f" | 중앙값 {np.median(all_ratios):.2f}"
            f" | 최댓값 {max(all_ratios):.2f}"
        )
    return results


# ─────────────────────────────────────────────────────────────
# 4. 시각화
# ─────────────────────────────────────────────────────────────
def make_map(rail_gdf, results, seoul_gdf):
    print("[4/4] 지도 렌더링...")

    BG = "#0d1117"       # 배경 (다크)
    BORDER = "#30363d"   # 서울 경계
    RAIL_BG = "#21262d"  # 철도 배경 라인

    # 커스텀 컬러맵: 연한 노랑 → 오렌지 → 진한 빨강 (단절 심할수록 진함)
    cmap = LinearSegmentedColormap.from_list(
        "detour",
        ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026", "#6b0011"],
    )
    norm = mcolors.Normalize(vmin=1.0, vmax=RATIO_CAP)

    fig, ax = plt.subplots(figsize=(14, 14), facecolor=BG)
    ax.set_facecolor(BG)

    # 서울 경계
    seoul_gdf.to_crs(5179).boundary.plot(
        ax=ax, color=BORDER, linewidth=1.0, alpha=0.8, zorder=1
    )

    # 철도 기본 라인 (배경)
    rail_gdf.plot(ax=ax, color=RAIL_BG, linewidth=3.5, alpha=0.9, zorder=2)

    if results:
        xs = np.array([r["x"] for r in results])
        ys = np.array([r["y"] for r in results])
        ratios = np.array([r["ratio"] for r in results])

        # ── LineCollection: 철도 라인을 구간별로 다른 색으로 그리기 ──
        # 샘플 포인트들을 노선명으로 그룹핑해서 연속된 선으로 연결
        names = [r["name"] for r in results]
        unique_names = list(dict.fromkeys(names))  # 순서 보존

        for uname in unique_names:
            idxs = [i for i, r in enumerate(results) if r["name"] == uname]
            if len(idxs) < 2:
                continue

            # 연속된 선 세그먼트 구성
            seg_xs = xs[idxs]
            seg_ys = ys[idxs]
            seg_ratios = ratios[idxs]

            # 각 세그먼트 = 연속한 두 점
            segments = [
                [[seg_xs[i], seg_ys[i]], [seg_xs[i + 1], seg_ys[i + 1]]]
                for i in range(len(seg_xs) - 1)
            ]
            seg_colors = (seg_ratios[:-1] + seg_ratios[1:]) / 2.0  # 구간 평균

            lc = LineCollection(
                segments, cmap=cmap, norm=norm, linewidth=5, zorder=3, alpha=0.9
            )
            lc.set_array(seg_colors)
            ax.add_collection(lc)

        # 스캐터도 함께 (점으로도 강조)
        sc = ax.scatter(
            xs, ys,
            c=ratios, cmap=cmap, norm=norm,
            s=30, alpha=0.6, zorder=4, linewidths=0,
        )

        # 컬러바
        cbar = plt.colorbar(sc, ax=ax, fraction=0.025, pad=0.02, orientation="vertical")
        cbar.set_label(
            "우회비율  (1.0 = 단절 없음, "
            f"{RATIO_CAP:.0f}.0 = {RATIO_CAP:.0f}배 우회)",
            color="white", fontsize=10,
        )
        cbar.ax.yaxis.set_tick_params(color="white")
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=9)
        cbar.outline.set_edgecolor(BORDER)

    # 제목 + 주석
    ax.set_title(
        "끊어진 서울 — 지상철도 보행 단절 지도",
        color="white", fontsize=18, fontweight="bold", pad=15, loc="left",
    )
    ax.text(
        0.01, 0.97,
        "색상 = 우회비율 (직선 500m vs 실제 보행거리)\n"
        "진한 빨강 = 철도를 넘으려면 훨씬 멀리 돌아가야 하는 구간",
        transform=ax.transAxes, color="#8b949e",
        fontsize=9, va="top",
    )
    ax.text(
        0.99, 0.01,
        "데이터: OSM | 좌표: EPSG:5179",
        transform=ax.transAxes, color="#444c56",
        fontsize=8, ha="right",
    )

    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout(pad=0.5)

    out_path = OUT_DIR / "detour_map.png"
    plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  PNG 저장: {out_path}")

    # ── Folium 인터랙티브 지도 (실제 지도 위 오버레이, 검증용) ──
    if results:
        html_path = _make_folium_map(results, rail_gdf)
        print(f"  HTML 저장: {html_path}")
        print("  → 브라우저로 열어서 실제 지도와 대조 가능!")

    print(f"\n✅ 완료")
    return out_path


def _make_folium_map(results, rail_gdf):
    """
    Folium 인터랙티브 지도 v2:
    - 우회비율 슬라이더 필터 (오른쪽 상단 패널)
    - 점 클릭 시 직선 경로(흰 점선) + 실제 보행 경로(컬러 실선) 표시
    - OSM / 위성사진 레이어 전환으로 실제 지도 대조 가능
    """
    m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="CartoDB dark_matter")
    folium.TileLayer("OpenStreetMap", name="OSM 지도").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="위성사진 (육안 검증용)",
    ).add_to(m)

    # 철도 라인 (정적 레이어 — Python으로 추가)
    rail_wgs = rail_gdf.to_crs(4326)
    for _, row in rail_wgs.iterrows():
        geom = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            folium.PolyLine(
                [(pt[1], pt[0]) for pt in line.coords],
                color="#ffffff", weight=2, opacity=0.25,
                tooltip=str(row.get("name", "미상")),
            ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    # ── 슬라이더 패널 HTML ───────────────────────────────────────
    slider_html = """
    <div id="slider-panel" style="
        position: fixed; top: 80px; right: 10px; z-index: 9999;
        background: rgba(13,17,23,0.93); border: 1px solid #30363d;
        border-radius: 10px; padding: 14px 16px; color: white;
        font-family: -apple-system, 'Helvetica Neue', sans-serif;
        font-size: 13px; width: 260px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.7);">
      <div style="font-weight:700; font-size:14px; color:#e6edf3; margin-bottom:10px">
        우회비율 필터
      </div>
      <div style="margin-bottom:6px; display:flex; align-items:baseline; gap:6px">
        <span style="color:#8b949e">최소</span>
        <span id="threshold-display"
              style="color:#fd8d3c; font-weight:700; font-size:22px; line-height:1">1.0</span>
        <span style="color:#8b949e">배 이상만 표시</span>
      </div>
      <input type="range" id="ratio-slider"
             min="1.0" max="8.0" step="0.5" value="1.0"
             style="width:100%; accent-color:#fd8d3c; cursor:pointer; margin:4px 0 2px">
      <div style="display:flex; justify-content:space-between;
                  font-size:11px; color:#444c56; margin-bottom:10px">
        <span>1.0배 (전체)</span><span>8.0배</span>
      </div>
      <div style="padding-top:10px; border-top:1px solid #21262d;
                  color:#8b949e; font-size:12px" id="marker-count">로딩 중...</div>
      <div style="margin-top:6px; color:#444c56; font-size:11px">
        ● 점 클릭 → 보행 루트 표시<br>
        지도 빈 곳 클릭 → 루트 숨김
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(slider_html))

    # ── 마커 데이터 직렬화 (JS로 넘길 JSON) ─────────────────────
    has_path = results and "path_wgs84" in results[0]
    marker_data = []
    for r in results:
        latlng = _xy_to_latlon(r["x"], r["y"])
        entry = {
            "latlng": latlng,
            "ratio":  round(r["ratio"], 3),
            "name":   r["name"],
            "straight_m": r.get("straight_m", int(2 * PERP_M)),
            "actual_m":   r.get("actual_m", int(r["ratio"] * 2 * PERP_M)),
            "left":  r.get("left_wgs84",  latlng),
            "right": r.get("right_wgs84", latlng),
            "path":  r.get("path_wgs84",  []) if has_path else [],
        }
        marker_data.append(entry)

    map_var = m.get_name()  # e.g. "map_a1b2c3"

    # ── 동적 마커 + 루트 시각화 JavaScript ──────────────────────
    # window.addEventListener('load') 로 감싸야 Folium 지도 초기화 완료 후 실행됨
    js = f"""
window.addEventListener('load', function() {{
  var map = window['{map_var}'];
  if (!map) {{
    // 혹시 변수명이 달라도 첫 번째 leaflet 맵을 찾음
    var k = Object.keys(window).find(function(k) {{ return k.startsWith('map_'); }});
    map = k ? window[k] : null;
  }}
  if (!map) {{ console.error('Leaflet map not found'); return; }}

  var markerLayer = L.layerGroup().addTo(map);
  var routeLayer  = L.layerGroup().addTo(map);
  var markerData  = {json.dumps(marker_data, ensure_ascii=False)};

  /* ─── 컬러맵: 노랑→오렌지→진빨강 (Python cmap과 동일) ─── */
  var _stops = [
    [255,255,178],[254,204,92],[253,141,60],[240,59,32],[189,0,38],[107,0,17]
  ];
  function getColor(ratio) {{
    var t = Math.min(1.0, Math.max(0.0, (ratio - 1.0) / 7.0));
    var n = _stops.length - 1;
    var i = Math.min(Math.floor(t * n), n - 1);
    var f = t * n - i;
    var r = Math.round(_stops[i][0] + f * (_stops[i+1][0] - _stops[i][0]));
    var g = Math.round(_stops[i][1] + f * (_stops[i+1][1] - _stops[i][1]));
    var b = Math.round(_stops[i][2] + f * (_stops[i+1][2] - _stops[i][2]));
    return 'rgb(' + r + ',' + g + ',' + b + ')';
  }}

  /* ─── 클릭 시 보행 루트 표시 ─── */
  function showRoute(d) {{
    routeLayer.clearLayers();

    /* 직선 거리 (흰 점선) */
    L.polyline([d.left, d.right], {{
      color: '#ffffff', weight: 2, opacity: 0.8, dashArray: '8 5'
    }}).bindTooltip('직선 ' + d.straight_m + 'm').addTo(routeLayer);

    /* 실제 보행 경로 (컬러 실선) */
    if (d.path && d.path.length > 1) {{
      L.polyline(d.path, {{
        color: getColor(d.ratio), weight: 5, opacity: 0.95
      }}).bindTooltip('실제 보행 ' + d.actual_m + 'm').addTo(routeLayer);
    }} else {{
      /* path 데이터 없을 때 안내 */
      L.popup({{ maxWidth: 220 }})
        .setLatLng(d.latlng)
        .setContent('<div style="font-family:sans-serif">⚠️ 경로 데이터 없음<br><small>캐시 삭제 후 재실행하면 표시됩니다</small></div>')
        .openOn(map);
      return;
    }}

    /* 출발 / 도착 마커 */
    [['left','#00e676','출발'], ['right','#ff5252','도착']].forEach(function(cfg) {{
      L.circleMarker(d[cfg[0]], {{
        radius: 9, color: '#fff', weight: 2,
        fillColor: cfg[1], fillOpacity: 1.0
      }}).bindTooltip(cfg[2]).addTo(routeLayer);
    }});

    /* 팝업 */
    L.popup({{ maxWidth: 240 }})
      .setLatLng(d.latlng)
      .setContent(
        '<div style="font-family:-apple-system,sans-serif; padding:2px 4px">' +
        '<b style="font-size:14px">' + d.name + '</b>' +
        '<hr style="margin:6px 0; border-color:#ddd">' +
        '📏 직선거리: <b>' + d.straight_m + 'm</b><br>' +
        '🚶 실제 보행: <b style="color:' + getColor(d.ratio) + '">' + d.actual_m + 'm</b><br>' +
        '🔁 우회비율: <b style="color:' + getColor(d.ratio) + '; font-size:18px">' +
        d.ratio.toFixed(2) + '배</b>' +
        '</div>'
      ).openOn(map);
  }}

  /* ─── 슬라이더 기준으로 마커 재렌더링 ─── */
  function updateMarkers(threshold) {{
    markerLayer.clearLayers();
    var count = 0;
    markerData.forEach(function(d) {{
      if (d.ratio < threshold) return;
      count++;
      var radius = 5 + (d.ratio - 1.0) / 7.0 * 10;
      var color  = getColor(d.ratio);
      var mk = L.circleMarker(d.latlng, {{
        radius: radius, color: color,
        fillColor: color, fillOpacity: 0.85, weight: 0
      }});
      mk.bindTooltip(d.name + ' | ' + d.ratio.toFixed(1) + '배 우회');
      mk.on('click', function(e) {{
        L.DomEvent.stopPropagation(e);
        showRoute(d);
      }});
      markerLayer.addLayer(mk);
    }});
    var el = document.getElementById('marker-count');
    if (el) el.textContent = count + '개 구간 표시 중 (전체 ' + markerData.length + '개)';
  }}

  /* ─── 지도 빈 곳 클릭 → 루트 숨김 ─── */
  map.on('click', function() {{ routeLayer.clearLayers(); }});

  /* ─── 슬라이더 이벤트 ─── */
  var slider = document.getElementById('ratio-slider');
  if (slider) {{
    slider.addEventListener('input', function() {{
      var val = parseFloat(this.value);
      document.getElementById('threshold-display').textContent = val.toFixed(1);
      updateMarkers(val);
    }});
  }}

  /* ─── 초기 렌더링 ─── */
  updateMarkers(1.0);
}});
"""
    m.get_root().script.add_child(folium.Element(js))

    html_path = OUT_DIR / "detour_map_interactive_v2.html"
    m.save(html_path)
    return html_path


# ─────────────────────────────────────────────────────────────
# 실행 진입점
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 서울 경계 (시각화 배경용)
    print("서울 경계 로드...")
    seoul_gdf = ox.geocode_to_gdf(PLACE)

    # 1. 지상철도
    rail = load_surface_rails()

    # 2. 보행망
    G = load_walk_graph(rail)

    # 3. 우회비율 (캐시) — v2 전용 파일: path_wgs84 포함 구조
    results_pkl = CACHE_DIR / "detour_results_v2.pkl"
    if results_pkl.exists():
        print("[CACHE] detour_results.pkl 로드")
        with open(results_pkl, "rb") as f:
            results = pickle.load(f)
    else:
        results = compute_detour_ratios(rail, G)
        with open(results_pkl, "wb") as f:
            pickle.dump(results, f)

    # 4. 지도 (PNG + Folium HTML)
    make_map(rail, results, seoul_gdf)
