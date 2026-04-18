"""
01_isochrone_map.py  (v2 — undirected graph + 2가지 시각화)
------------------------------------------------------------
노원구 상계1동(상계역)에서 일반인 vs 보행보조장치 사용 노인의
15분·30분 도달 영역을 두 가지 방법으로 시각화합니다.

■ 대상 지역 선정 근거
  - 동별 주민등록인구 기준 65세+ 인구 상위 동 분석
  - 1위 강동구 길동(10,386명): 기존 보행 그래프 미포함 구역
  - 그래프 내 최고 순위: 노원구 상계1동(rank 6, 9,013명)
  - 출발점: 상계역(지하철 4호선) — 노원구 대표 교통 허브

■ 시각화 방법 1: Folium (Leaflet.js 기반)
  - Python folium 라이브러리 사용
  - OpenStreetMap 타일 + 레이어 토글 체크박스
  - 장점: 경량 HTML, 인터넷 없이도 동작 가능
  - 단점: 복잡한 드롭다운/슬라이더 구현 어려움

■ 시각화 방법 2: Plotly (Scattermapbox 기반)
  - Plotly graph_objects 사용, carto-positron 스타일
  - Mapbox 토큰 불필요 (Plotly 내장 무료 타일)
  - 장점: 드롭다운·슬라이더 등 Rich Interactive 가능
  - 단점: 파일 크기가 Folium보다 크고 렌더링 속도 약간 느림

■ 보행속도 기준 (한음 외 2020, n=4,857)
  일반인 (65세 미만): 1.28 m/s  ← 기준선
  보행보조장치 사용:  0.88 m/s  ← 비교 대상 (가장 극단적 차이)

출력:
  ../outputs/isochrone_folium.html    — 방법 1
  ../outputs/isochrone_plotly.html    — 방법 2
"""

import sys
import pickle
import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import networkx as nx
import pyproj
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import unary_union, transform as shp_transform
import folium
import plotly.graph_objects as go

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── 경로 ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR   = Path(__file__).resolve().parents[1] / "outputs"
CACHE_DIR    = PROJECT_ROOT / "cache"
ISO_CACHE    = CACHE_DIR / "isochrones_v2"   # v2: undirected 전용 캐시
ISO_CACHE.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 파라미터 ──────────────────────────────────────────────
START_LON  = 127.0655   # 상계역 (지하철 4호선)
START_LAT  = 37.6561
START_NAME = "상계역"
START_DESC = "노원구 상계1동 (서울 동별 65세+ 인구 6위 — 9,013명)"

GROUPS = {
    "일반인 (65세 미만)":  {"speed": 1.28, "color": "#1D4ED8", "short": "일반인"},
    "보행보조장치 사용":    {"speed": 0.88, "color": "#DC2626", "short": "보조장치"},
}
TIMES = [15, 30]

# ── 좌표 변환기 ───────────────────────────────────────────
_to5179  = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_to4326  = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

# ── 그래프 로드 (undirected) ──────────────────────────────
def load_undirected() -> nx.Graph:
    path = CACHE_DIR / "walk_graph.pkl"
    if not path.exists():
        raise FileNotFoundError(str(path))
    logger.info("그래프 로드 중…")
    with open(path, "rb") as f:
        G = pickle.load(f)
    G_u = G.to_undirected()
    logger.info("undirected 변환 완료 — 노드: %d, 엣지: %d",
                G_u.number_of_nodes(), G_u.number_of_edges())
    return G_u

_KD: Optional[tuple] = None

def nearest_node(G: nx.Graph, lon: float, lat: float) -> int:
    global _KD
    x0, y0 = _to5179.transform(lon, lat)
    if _KD is None:
        node_ids = np.array(list(G.nodes()))
        coords   = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in node_ids])
        _KD = (cKDTree(coords), node_ids)
    tree, ids = _KD
    _, idx = tree.query([x0, y0])
    return int(ids[idx])

def node_lonlat(G: nx.Graph, n: int) -> tuple[float, float]:
    return _to4326.transform(G.nodes[n]["x"], G.nodes[n]["y"])

# ── 등시선 계산 (undirected, 캐시) ───────────────────────
def _cache_key(node: int, speed: float, t: float) -> str:
    return hashlib.md5(f"u_{node}_{speed:.4f}_{t:.1f}".encode()).hexdigest()

def compute_iso(G: nx.Graph, node: int, speed: float, t_min: float) -> Polygon:
    key   = _cache_key(node, speed, t_min)
    cpath = ISO_CACHE / f"{key}.pkl"
    if cpath.exists():
        with open(cpath, "rb") as f:
            return pickle.load(f)

    cutoff = t_min * 60.0

    def wt(u, v, d):
        vals = d.values() if isinstance(d, dict) else [d]
        return min(dd.get("length", 1.0) / speed for dd in vals)

    reachable = nx.single_source_dijkstra_path_length(
        G, node, cutoff=cutoff, weight=wt
    )
    logger.info("  도달 노드 %d개 (%.2f m/s, %d분)", len(reachable), speed, t_min)

    if len(reachable) < 3:
        cx, cy = node_lonlat(G, node)
        return Point(cx, cy).buffer(0.001)

    pts = [Point(*node_lonlat(G, n)) for n in reachable]
    mp  = MultiPoint(pts)
    try:
        poly = mp.concave_hull(ratio=0.05, allow_holes=False)
    except Exception:
        poly = mp.convex_hull

    if poly.is_empty or not poly.is_valid:
        poly = mp.convex_hull

    with open(cpath, "wb") as f:
        pickle.dump(poly, f)
    return poly

def area_km2(poly: Polygon) -> float:
    proj = _to5179.transform
    poly_proj = shp_transform(proj, poly)
    return poly_proj.area / 1e6

def poly_coords(poly: Polygon) -> tuple[list, list]:
    """WGS84 폴리곤 → (lons, lats) 리스트"""
    if poly.geom_type == "Polygon":
        lons, lats = poly.exterior.xy
        return list(lons), list(lats)
    # MultiPolygon fallback
    largest = max(poly.geoms, key=lambda g: g.area)
    lons, lats = largest.exterior.xy
    return list(lons), list(lats)

def poly_folium(poly: Polygon) -> list[list[float]]:
    """Folium 형식: [[lat, lon], ...]"""
    lons, lats = poly_coords(poly)
    return [[la, lo] for lo, la in zip(lons, lats)]

# ── 메인 계산 ─────────────────────────────────────────────
def main():
    G     = load_undirected()
    snode = nearest_node(G, START_LON, START_LAT)
    slo, sla = node_lonlat(G, snode)
    logger.info("출발 노드: %d  (lon=%.5f, lat=%.5f)", snode, slo, sla)

    isos: dict[tuple, Polygon] = {}
    for label, cfg in GROUPS.items():
        for t in TIMES:
            logger.info("계산: %s / %d분", label, t)
            isos[(label, t)] = compute_iso(G, snode, cfg["speed"], t)

    # 면적 계산
    areas = {k: area_km2(v) for k, v in isos.items()}
    a_young_15 = areas[("일반인 (65세 미만)", 15)]
    a_young_30 = areas[("일반인 (65세 미만)", 30)]
    a_aid_15   = areas[("보행보조장치 사용",   15)]
    a_aid_30   = areas[("보행보조장치 사용",   30)]
    loss_15    = (1 - a_aid_15 / a_young_15) * 100
    loss_30    = (1 - a_aid_30 / a_young_30) * 100

    print(f"\n{'='*60}")
    print(f"▶ 면적 비교 ({START_NAME} 기준)")
    print(f"{'='*60}")
    print(f"  일반인 15분: {a_young_15:.3f} km²  |  보조장치 15분: {a_aid_15:.3f} km²  → 손실 {loss_15:.1f}%")
    print(f"  일반인 30분: {a_young_30:.3f} km²  |  보조장치 30분: {a_aid_30:.3f} km²  → 손실 {loss_30:.1f}%")

    # ── [ 방법 1 ] Folium ─────────────────────────────────
    build_folium(isos, areas, loss_15, loss_30)

    # ── [ 방법 2 ] Plotly ────────────────────────────────
    build_plotly(isos, areas, loss_15, loss_30)


# ═══════════════════════════════════════════════════════════
#  방법 1: Folium (Leaflet.js)
# ═══════════════════════════════════════════════════════════
def build_folium(isos, areas, loss_15, loss_30):
    logger.info("Folium 지도 생성 중…")
    m = folium.Map(
        location=[START_LAT, START_LON],
        zoom_start=14,
        tiles="CartoDB positron",
        prefer_canvas=True,
    )

    # 색상: 그룹별, 시간별 투명도 조정
    FILL_OP = {15: 0.45, 30: 0.20}
    LINE_OP = {15: 0.90, 30: 0.60}
    LINE_W  = {15: 2.5,  30: 1.5}

    # 30분 먼저(아래 레이어), 15분 나중(위 레이어)
    for t in [30, 15]:
        for label, cfg in GROUPS.items():
            poly    = isos[(label, t)]
            latlng  = poly_folium(poly)
            color   = cfg["color"]
            a_km2   = areas[(label, t)]
            loss    = (1 - a_km2 / areas[("일반인 (65세 미만)", t)]) * 100 if label != "일반인 (65세 미만)" else 0

            fg = folium.FeatureGroup(
                name=f"{'■' if t == 15 else '□'} {cfg['short']} — {t}분",
                show=True,
            )
            tip = (
                f"<b>{label}</b><br>"
                f"보행속도: <b>{cfg['speed']:.2f} m/s</b><br>"
                f"도보 <b>{t}분</b> 도달 범위<br>"
                f"면적: <b>{a_km2:.3f} km²</b>"
                + (f"<br>일반인 대비 손실: <b style='color:#DC2626'>{loss:.1f}%</b>" if loss > 0 else "")
            )
            folium.Polygon(
                locations=latlng,
                color=color,
                weight=LINE_W[t],
                opacity=LINE_OP[t],
                fill=True,
                fill_color=color,
                fill_opacity=FILL_OP[t],
                tooltip=folium.Tooltip(tip),
            ).add_to(fg)
            fg.add_to(m)

    # 출발점 마커
    folium.Marker(
        location=[START_LAT, START_LON],
        popup=folium.Popup(
            f"<b>{START_NAME}</b><br><span style='font-size:11px'>{START_DESC}</span>",
            max_width=260,
        ),
        tooltip=f"출발점: {START_NAME}",
        icon=folium.Icon(color="black", icon="star", prefix="fa"),
    ).add_to(m)

    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # 범례
    a_y15 = areas[("일반인 (65세 미만)", 15)]
    a_y30 = areas[("일반인 (65세 미만)", 30)]
    a_a15 = areas[("보행보조장치 사용",   15)]
    a_a30 = areas[("보행보조장치 사용",   30)]
    legend = f"""
    <div style="
        position:fixed; bottom:28px; left:18px; z-index:1000;
        background:rgba(255,255,255,0.96); border:1px solid #ccc;
        border-radius:10px; padding:14px 18px;
        font-family:'AppleGothic','Malgun Gothic',sans-serif;
        font-size:13px; box-shadow:2px 2px 10px rgba(0,0,0,0.15);
        min-width:260px; max-width:300px;">
      <div style="font-size:16px;font-weight:bold;color:#111;margin-bottom:6px;">
        같은 시간, 다른 서울
      </div>
      <div style="font-size:11px;color:#555;margin-bottom:10px;">
        출발점: <b>{START_NAME}</b><br>
        {START_DESC}
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="color:#666;font-size:11px;">
            <td style="padding:3px 0;"></td>
            <td style="text-align:center;padding:3px 6px;">15분</td>
            <td style="text-align:center;padding:3px 6px;">30분</td>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding:5px 0;color:#1D4ED8;font-weight:bold;">
              🔵 일반인 (1.28 m/s)
            </td>
            <td style="text-align:center;color:#333;">{a_y15:.2f} km²</td>
            <td style="text-align:center;color:#333;">{a_y30:.2f} km²</td>
          </tr>
          <tr>
            <td style="padding:5px 0;color:#DC2626;font-weight:bold;">
              🔴 보행보조장치 (0.88 m/s)
            </td>
            <td style="text-align:center;color:#333;">{a_a15:.2f} km²</td>
            <td style="text-align:center;color:#333;">{a_a30:.2f} km²</td>
          </tr>
          <tr style="border-top:1px solid #eee;">
            <td style="padding:6px 0;color:#DC2626;font-weight:bold;font-size:13px;">
              ▼ 면적 손실률
            </td>
            <td style="text-align:center;color:#DC2626;font-weight:bold;font-size:14px;">
              {loss_15:.1f}%
            </td>
            <td style="text-align:center;color:#DC2626;font-weight:bold;font-size:14px;">
              {loss_30:.1f}%
            </td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top:10px;font-size:10px;color:#999;border-top:1px solid #eee;padding-top:8px;">
        ■ 진한 색 = 15분 도달 범위 &nbsp; □ 연한 색 = 30분 도달 범위<br>
        출처: 한음 외 (2020). 한국ITS학회 논문지 19(4). n=4,857
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))

    # 타이틀
    title = f"""
    <div style="
        position:fixed; top:12px; left:50%; transform:translateX(-50%);
        z-index:1000; background:rgba(255,255,255,0.96);
        border:1px solid #ddd; border-radius:8px;
        padding:10px 22px; text-align:center;
        font-family:'AppleGothic','Malgun Gothic',sans-serif;
        box-shadow:2px 2px 8px rgba(0,0,0,0.12);">
      <div style="font-size:17px;font-weight:bold;color:#111;">
        같은 15·30분, 다른 서울
      </div>
      <div style="font-size:11px;color:#666;margin-top:3px;">
        시각화 방법 1 — Folium (Leaflet.js) &nbsp;|&nbsp;
        출발점: {START_NAME} &nbsp;|&nbsp;
        일반인 1.28 m/s vs 보행보조장치 0.88 m/s
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title))

    out = OUTPUT_DIR / "isochrone_folium.html"
    m.save(str(out))
    logger.info("Folium 저장 → %s", out)


# ═══════════════════════════════════════════════════════════
#  방법 2: Plotly (Scattermapbox)
# ═══════════════════════════════════════════════════════════
def build_plotly(isos, areas, loss_15, loss_30):
    logger.info("Plotly 지도 생성 중…")

    # 색상 정의 (rgba 형식)
    STYLE = {
        ("일반인 (65세 미만)", 15): {"fill": "rgba(29,78,216,0.45)",  "line": "rgba(29,78,216,0.9)",  "lw": 2.5, "name": "일반인 — 15분"},
        ("일반인 (65세 미만)", 30): {"fill": "rgba(29,78,216,0.18)",  "line": "rgba(29,78,216,0.55)", "lw": 1.5, "name": "일반인 — 30분"},
        ("보행보조장치 사용",   15): {"fill": "rgba(220,38,38,0.50)",  "line": "rgba(220,38,38,0.95)", "lw": 2.5, "name": "보조장치 — 15분"},
        ("보행보조장치 사용",   30): {"fill": "rgba(220,38,38,0.20)",  "line": "rgba(220,38,38,0.60)", "lw": 1.5, "name": "보조장치 — 30분"},
    }

    fig = go.Figure()

    # 30분 먼저(아래 레이어), 15분 나중
    for t in [30, 15]:
        for label, cfg in GROUPS.items():
            poly  = isos[(label, t)]
            lons, lats = poly_coords(poly)
            # 닫힌 폴리곤: 첫 점 = 마지막 점
            if lons[0] != lons[-1]:
                lons = list(lons) + [lons[0]]
                lats = list(lats) + [lats[0]]
            sty   = STYLE[(label, t)]
            a_km2 = areas[(label, t)]
            loss  = (1 - a_km2 / areas[("일반인 (65세 미만)", t)]) * 100 if label != "일반인 (65세 미만)" else 0

            ht = (
                f"<b>{label}</b><br>"
                f"보행속도: {cfg['speed']:.2f} m/s<br>"
                f"도보 {t}분 도달 범위<br>"
                f"면적: {a_km2:.3f} km²"
                + (f"<br><b style='color:#DC2626'>일반인 대비 손실 {loss:.1f}%</b>" if loss > 0 else "")
            )

            fig.add_trace(go.Scattermapbox(
                lon=lons, lat=lats,
                mode="lines",
                fill="toself",
                fillcolor=sty["fill"],
                line=dict(color=sty["line"], width=sty["lw"]),
                name=sty["name"],
                hovertemplate=ht + "<extra></extra>",
                showlegend=True,
            ))

    # 출발점 마커
    fig.add_trace(go.Scattermapbox(
        lon=[START_LON], lat=[START_LAT],
        mode="markers+text",
        marker=dict(size=16, color="black", symbol="star"),
        text=[START_NAME],
        textposition="top right",
        textfont=dict(size=12, color="black"),
        name=f"출발점: {START_NAME}",
        hovertemplate=f"<b>{START_NAME}</b><br>{START_DESC}<extra></extra>",
        showlegend=True,
    ))

    # 면적 손실 주석 (annotation)
    fig.add_annotation(
        x=0.01, y=0.20, xref="paper", yref="paper",
        xanchor="left", yanchor="top",
        text=(
            f"<b>📊 면적 손실률 (일반인 대비)</b><br>"
            f"15분: <b><span style='color:#DC2626'>{loss_15:.1f}%</span></b> 감소<br>"
            f"30분: <b><span style='color:#DC2626'>{loss_30:.1f}%</span></b> 감소<br>"
            f"<br><b>면적 (km²)</b><br>"
            f"일반인 15분: {areas[('일반인 (65세 미만)',15)]:.2f}<br>"
            f"일반인 30분: {areas[('일반인 (65세 미만)',30)]:.2f}<br>"
            f"보조장치 15분: {areas[('보행보조장치 사용',15)]:.2f}<br>"
            f"보조장치 30분: {areas[('보행보조장치 사용',30)]:.2f}"
        ),
        bgcolor="rgba(255,255,255,0.92)",
        bordercolor="#ccc",
        borderwidth=1,
        font=dict(size=12, family="AppleGothic, Malgun Gothic, sans-serif"),
        align="left",
        showarrow=False,
    )

    fig.update_layout(
        mapbox=dict(
            style="carto-positron",
            center=dict(lat=START_LAT, lon=START_LON),
            zoom=13.5,
        ),
        title=dict(
            text=(
                "<b>같은 15·30분, 다른 서울</b>"
                f"<br><sub>시각화 방법 2 — Plotly Scattermapbox &nbsp;|&nbsp;"
                f"출발점: {START_NAME} ({START_DESC})"
                f"<br>일반인 1.28 m/s (파랑) vs 보행보조장치 0.88 m/s (빨강) &nbsp;|&nbsp;"
                f"진한 색 = 15분, 연한 색 = 30분</sub>"
            ),
            x=0.5,
            font=dict(size=15, family="AppleGothic, Malgun Gothic, sans-serif"),
        ),
        legend=dict(
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor="#ccc",
            borderwidth=1,
            font=dict(size=12, family="AppleGothic, Malgun Gothic, sans-serif"),
        ),
        font=dict(family="AppleGothic, Malgun Gothic, sans-serif"),
        height=720,
        margin=dict(l=0, r=0, t=100, b=0),
    )

    out = OUTPUT_DIR / "isochrone_plotly.html"
    fig.write_html(str(out))
    logger.info("Plotly 저장 → %s", out)


if __name__ == "__main__":
    main()
