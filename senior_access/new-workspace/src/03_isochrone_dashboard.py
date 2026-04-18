"""
03_isochrone_dashboard.py
--------------------------
강동구 길동사거리 기준, 일반인 vs 보행보조장치 노인의
15·30분 도보 도달 영역 비교 시각화 (시각적 충격 + 랜드마크 + 대시보드)

■ 출발 지점
  강동구 길동사거리 (서울 동별 65세+ 인구 1위: 10,386명)

■ 시각화 방법
  방법 A — Folium (Leaflet.js 기반): 02_isochrone_folium.html
  방법 B — Plotly (Scattermapbox):   03_isochrone_plotly.html
  방법 C — 통합 대시보드 HTML:        04_dashboard.html

■ 핵심 시각 요소
  1. 청년 30분 등시선 (파랑/시안)
  2. 보조장치 30분 등시선 (빨강)
  3. "잃어버린 영역" = 청년만 도달 가능한 지대 (주황/황금)
  4. 주요 랜드마크 색상 분류:
     🟢 초록 = 둘 다 30분 내 도달 가능
     🟡 노랑 = 청년만 30분 내 도달 가능 (보조장치 불가)
     ⚫ 회색 = 둘 다 30분 내 도달 불가

■ 보행속도 (한음 외 2020, n=4,857)
  일반인 (65세 미만): 1.28 m/s
  보행보조장치 사용:  0.88 m/s
"""

import logging
import warnings
from pathlib import Path
import json

import numpy as np
import networkx as nx
import osmnx as ox
from shapely.geometry import MultiPoint, Point, Polygon, shape
from shapely.ops import unary_union
import shapely
import pandas as pd
import folium
from folium.plugins import FloatImage
import plotly.graph_objects as go
import plotly.io as pio

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── 경로 ─────────────────────────────────────────────────
WORKSPACE  = Path(__file__).resolve().parents[1]
GRAPH_PATH = WORKSPACE / "cache" / "seoul_walk_full.graphml"
OUTPUT_DIR = WORKSPACE / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 파라미터 ──────────────────────────────────────────────
START_LON  = 127.1435
START_LAT  = 37.5415
START_NAME = "길동사거리"
START_DESC = "강동구 길동 (서울 동별 65세+ 인구 1위 · 10,386명)"

SPEEDS = {
    "일반인 (65세 미만)": 1.28,
    "보행보조장치 사용":   0.88,
}
TIMES = [15, 30]

# 색상
C_YOUNG_FILL   = "rgba(0,210,255,0.30)"
C_YOUNG_LINE   = "rgba(0,180,255,1.0)"
C_AID_FILL     = "rgba(255,60,60,0.30)"
C_AID_LINE     = "rgba(255,40,40,1.0)"
C_LOST_FILL    = "rgba(255,185,0,0.55)"
C_LOST_LINE    = "rgba(255,165,0,0.9)"

# ── 1. 그래프 로드 ────────────────────────────────────────
logger.info("그래프 로드: %s", GRAPH_PATH)
G_dir = ox.load_graphml(str(GRAPH_PATH))
G     = ox.convert.to_undirected(G_dir)
logger.info("undirected — 노드: %d, 엣지: %d", G.number_of_nodes(), G.number_of_edges())

start_node = ox.distance.nearest_nodes(G, START_LON, START_LAT)
slo = G.nodes[start_node]["x"]
sla = G.nodes[start_node]["y"]
logger.info("출발 노드: %d (lon=%.5f, lat=%.5f)", start_node, slo, sla)

# ── 2. 등시선 계산 ────────────────────────────────────────
def compute_iso(G, node, speed, t_min, label=""):
    cutoff = t_min * 60.0

    def wt(u, v, d):
        vals = d.values() if isinstance(d, dict) else [d]
        return min(dd.get("length", 1.0) / speed for dd in vals)

    reachable = nx.single_source_dijkstra_path_length(
        G, node, cutoff=cutoff, weight=wt
    )
    logger.info("  %s %d분: %d 노드", label, t_min, len(reachable))

    pts = [Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in reachable]
    if len(pts) < 3:
        return Point(G.nodes[node]["x"], G.nodes[node]["y"]).buffer(0.001)

    mp = MultiPoint(pts)
    try:
        poly = mp.concave_hull(ratio=0.05, allow_holes=False)
    except Exception:
        poly = mp.convex_hull

    return poly if (poly.is_valid and not poly.is_empty) else mp.convex_hull

logger.info("등시선 계산 시작…")
iso = {}
iso[("young", 15)] = compute_iso(G, start_node, 1.28, 15, "일반인")
iso[("young", 30)] = compute_iso(G, start_node, 1.28, 30, "일반인")
iso[("aid",   15)] = compute_iso(G, start_node, 0.88, 15, "보조장치")
iso[("aid",   30)] = compute_iso(G, start_node, 0.88, 30, "보조장치")

# 잃어버린 영역 (청년 30분 - 보조장치 30분)
lost_zone = iso[("young", 30)].difference(iso[("aid", 30)])
logger.info("잃어버린 영역 계산 완료")

# ── 3. 면적 계산 ─────────────────────────────────────────
import pyproj
from shapely.ops import transform as shp_transform

_to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

def area_km2(poly):
    poly_proj = shp_transform(_to5179.transform, poly)
    return poly_proj.area / 1e6

a = {k: area_km2(v) for k, v in iso.items()}
a_lost = area_km2(lost_zone)
loss_15 = (1 - a[("aid", 15)] / a[("young", 15)]) * 100
loss_30 = (1 - a[("aid", 30)] / a[("young", 30)]) * 100

print(f"\n{'='*60}")
print(f"▶ 면적 비교 (출발점: {START_NAME})")
print(f"{'='*60}")
print(f"  일반인  15분: {a[('young',15)]:.3f} km²")
print(f"  일반인  30분: {a[('young',30)]:.3f} km²")
print(f"  보조장치 15분: {a[('aid',15)]:.3f} km²")
print(f"  보조장치 30분: {a[('aid',30)]:.3f} km²")
print(f"  잃어버린 영역: {a_lost:.3f} km²")
print(f"  15분 손실: {loss_15:.1f}%  |  30분 손실: {loss_30:.1f}%")

# ── 4. 주요 랜드마크 (OSM + 수동 보완) ────────────────────
# 지하철역
STATIONS = [
    ("길동역(5호선)",     127.14020, 37.53837),
    ("강동역(5호선)",     127.13260, 37.53580),
    ("천호역(5/8호선)",   127.12340, 37.53852),
    ("굽은다리역(5호선)", 127.14296, 37.54564),
    ("명일역(5호선)",     127.14408, 37.55195),
    ("강동구청역(8호선)", 127.12062, 37.53069),
    ("암사역(8호선)",     127.12754, 37.55011),
    ("둔촌동역(5호선)",   127.13624, 37.52780),
    ("올림픽공원역(5호선)",127.13093, 37.51615),
    ("잠실나루역(2호선)", 127.10383, 37.52069),
]

# 주요 시설
FACILITIES = [
    ("강동경희대병원", 127.1527, 37.5557, "hospital"),
    ("한양대학교병원", 127.0469, 37.5624, "hospital"),
    ("강동성심병원",   127.1494, 37.5310, "hospital"),
    ("강동구청",       127.1237, 37.5521, "gov"),
    ("강동구 보건소",  127.1377, 37.5525, "health"),
    ("롯데마트 천호점",127.1265, 37.5374, "market"),
    ("이마트 성내점",  127.1262, 37.5253, "market"),
    ("길동생태공원",   127.1499, 37.5361, "park"),
]

# 분류: 둘 다 접근 가능 / 청년만 / 불가
def classify(lon, lat):
    p = Point(lon, lat)
    in_young = iso[("young", 30)].contains(p)
    in_aid   = iso[("aid",   30)].contains(p)
    if in_young and in_aid:
        return "both"
    elif in_young:
        return "young_only"
    else:
        return "neither"

stations_classified = [(n, lo, la, classify(lo, la)) for n, lo, la in STATIONS]
facilities_classified = [(n, lo, la, cat, classify(lo, la)) for n, lo, la, cat in FACILITIES]

# 분류별 색상 (다크맵 기준)
STATUS_COLOR = {
    "both":       "#00FF88",   # 밝은 초록
    "young_only": "#FFD700",   # 황금
    "neither":    "#AAAAAA",   # 회색
}
STATUS_LABEL = {
    "both":       "✅ 둘 다 30분 내 도달",
    "young_only": "⚠️ 일반인만 30분 내 도달",
    "neither":    "❌ 30분 내 도달 불가",
}

# ── 폴리곤 → 좌표 리스트 ─────────────────────────────────
def poly_to_lonlat(poly):
    """shapely Polygon/MultiPolygon → (lons, lats) 닫힌 리스트"""
    if poly.geom_type == "MultiPolygon":
        largest = max(poly.geoms, key=lambda g: g.area)
        poly = largest
    lons, lats = poly.exterior.xy
    lons, lats = list(lons), list(lats)
    if lons[0] != lons[-1]:
        lons.append(lons[0]); lats.append(lats[0])
    return lons, lats

def poly_to_latlng(poly):
    """Folium 형식: [[lat, lon], ...]"""
    lons, lats = poly_to_lonlat(poly)
    return [[la, lo] for lo, la in zip(lons, lats)]

# ── 잃어버린 영역: 멀티폴리곤 처리 ─────────────────────────
def lost_parts(lost):
    """잃어버린 영역을 여러 폴리곤 파트로 분리"""
    if lost.geom_type == "Polygon":
        return [lost]
    elif lost.geom_type == "MultiPolygon":
        return list(lost.geoms)
    return []


# ═══════════════════════════════════════════════════════════
#  방법 A: Folium (Leaflet.js)
# ═══════════════════════════════════════════════════════════
logger.info("방법 A: Folium 지도 생성 중…")

m = folium.Map(
    location=[START_LAT, START_LON],
    zoom_start=13,
    tiles="CartoDB dark_matter",
    prefer_canvas=True,
)

# 청년 30분 (아래 레이어)
fg_young30 = folium.FeatureGroup(name="🔵 일반인 — 30분", show=True)
folium.Polygon(
    locations=poly_to_latlng(iso[("young", 30)]),
    color="#00C8FF", weight=2, opacity=0.8,
    fill=True, fill_color="#00C8FF", fill_opacity=0.18,
    tooltip="일반인 30분 도달 범위 (1.28 m/s)",
).add_to(fg_young30)
fg_young30.add_to(m)

# 청년 15분
fg_young15 = folium.FeatureGroup(name="🔵 일반인 — 15분", show=True)
folium.Polygon(
    locations=poly_to_latlng(iso[("young", 15)]),
    color="#00C8FF", weight=2.5, opacity=1.0,
    fill=True, fill_color="#00C8FF", fill_opacity=0.35,
    tooltip="일반인 15분 도달 범위 (1.28 m/s)",
).add_to(fg_young15)
fg_young15.add_to(m)

# 보조장치 30분
fg_aid30 = folium.FeatureGroup(name="🔴 보행보조장치 — 30분", show=True)
folium.Polygon(
    locations=poly_to_latlng(iso[("aid", 30)]),
    color="#FF3C3C", weight=2, opacity=0.8,
    fill=True, fill_color="#FF3C3C", fill_opacity=0.25,
    tooltip="보행보조장치 30분 도달 범위 (0.88 m/s)",
).add_to(fg_aid30)
fg_aid30.add_to(m)

# 보조장치 15분
fg_aid15 = folium.FeatureGroup(name="🔴 보행보조장치 — 15분", show=True)
folium.Polygon(
    locations=poly_to_latlng(iso[("aid", 15)]),
    color="#FF3C3C", weight=2.5, opacity=1.0,
    fill=True, fill_color="#FF3C3C", fill_opacity=0.45,
    tooltip="보행보조장치 15분 도달 범위 (0.88 m/s)",
).add_to(fg_aid15)
fg_aid15.add_to(m)

# 잃어버린 영역 (가장 위 레이어 — 시선 집중)
fg_lost = folium.FeatureGroup(name="🟡 잃어버린 영역 (일반인만 접근 가능)", show=True)
for part in lost_parts(lost_zone):
    if part.area < 1e-8:
        continue
    folium.Polygon(
        locations=poly_to_latlng(part),
        color="#FFB800", weight=2, opacity=0.9,
        fill=True, fill_color="#FFB800", fill_opacity=0.50,
        tooltip=(
            f"⚠️ 잃어버린 영역<br>"
            f"일반인은 도달 가능, 보행보조장치 노인은 불가<br>"
            f"전체 면적: {a_lost:.2f} km²"
        ),
    ).add_to(fg_lost)
fg_lost.add_to(m)

# 지하철역 마커
fg_subway = folium.FeatureGroup(name="🚇 지하철역 (접근성 분류)", show=True)
for name, lo, la, status in stations_classified:
    color  = STATUS_COLOR[status]
    label  = STATUS_LABEL[status]
    radius = 10
    folium.CircleMarker(
        location=[la, lo],
        radius=radius,
        color="#000000",
        weight=1.2,
        fill=True,
        fill_color=color,
        fill_opacity=0.95,
        tooltip=folium.Tooltip(
            f"<b>{name}</b><br>{label}",
            sticky=True,
        ),
        popup=folium.Popup(
            f"<b>{name}</b><br>{label}<br>"
            f"<span style='font-size:11px;color:#555'>"
            f"경도: {lo:.5f}<br>위도: {la:.5f}</span>",
            max_width=200,
        ),
    ).add_to(fg_subway)
    # 역 이름 라벨
    folium.map.Marker(
        location=[la, lo],
        icon=folium.DivIcon(
            html=f'<div style="font-size:10px;color:{color};font-weight:bold;'
                 f'text-shadow:1px 1px 2px #000;white-space:nowrap;'
                 f'margin-top:-20px;margin-left:12px;">{name}</div>',
            icon_size=(120, 20),
        )
    ).add_to(fg_subway)
fg_subway.add_to(m)

# 주요 시설 마커
ICON_MAP = {
    "hospital": ("➕", "#FF6B6B"),
    "health":   ("🏥", "#FF9999"),
    "gov":      ("🏛️", "#AAAAFF"),
    "market":   ("🛒", "#FFD700"),
    "park":     ("🌿", "#88FF88"),
}
fg_fac = folium.FeatureGroup(name="🏢 주요 시설 (접근성 분류)", show=True)
for name, lo, la, cat, status in facilities_classified:
    icon_sym, _ = ICON_MAP.get(cat, ("📍", "white"))
    status_color = STATUS_COLOR[status]
    folium.CircleMarker(
        location=[la, lo],
        radius=9,
        color="#000", weight=1,
        fill=True, fill_color=status_color, fill_opacity=0.9,
        tooltip=folium.Tooltip(
            f"<b>{icon_sym} {name}</b><br>{STATUS_LABEL[status]}",
            sticky=True,
        ),
    ).add_to(fg_fac)
    folium.map.Marker(
        location=[la, lo],
        icon=folium.DivIcon(
            html=f'<div style="font-size:9px;color:{status_color};font-weight:bold;'
                 f'text-shadow:1px 1px 2px #000;white-space:nowrap;'
                 f'margin-top:-18px;margin-left:10px;">{name}</div>',
            icon_size=(120, 18),
        )
    ).add_to(fg_fac)
fg_fac.add_to(m)

# 출발점
folium.Marker(
    location=[START_LAT, START_LON],
    tooltip=f"<b>출발점: {START_NAME}</b><br>{START_DESC}",
    popup=folium.Popup(
        f"<b>{START_NAME}</b><br><small>{START_DESC}</small>",
        max_width=260,
    ),
    icon=folium.Icon(color="white", icon="star", prefix="fa"),
).add_to(m)

folium.LayerControl(collapsed=False, position="topright").add_to(m)

# 범례 + 설명
young_only_count = sum(1 for _, _, _, s in stations_classified if s == "young_only")
both_count       = sum(1 for _, _, _, s in stations_classified if s == "both")
neither_count    = sum(1 for _, _, _, s in stations_classified if s == "neither")

legend_html = f"""
<div style="
    position:fixed; bottom:20px; left:16px; z-index:9999;
    background:rgba(15,15,25,0.93); border:1px solid #333;
    border-radius:10px; padding:16px 20px;
    font-family:'AppleGothic','Malgun Gothic',sans-serif;
    color:#eee; min-width:280px; max-width:320px;
    box-shadow:0 4px 16px rgba(0,0,0,0.6);">
  <div style="font-size:17px;font-weight:bold;color:#fff;margin-bottom:4px;">
    같은 30분, 다른 서울
  </div>
  <div style="font-size:11px;color:#aaa;margin-bottom:12px;">
    출발점: <b style="color:#fff">{START_NAME}</b>
    &nbsp;|&nbsp; 강동구 길동 (동별 65세+ 1위)
  </div>

  <table style="width:100%;border-collapse:collapse;font-size:12px;">
    <tr>
      <td style="padding:4px 0;">
        <span style="color:#00C8FF;font-size:15px;">■</span>
        일반인 (1.28 m/s)
      </td>
      <td style="text-align:right;color:#ccc;">
        15분 {a[('young',15)]:.2f} km² / 30분 {a[('young',30)]:.2f} km²
      </td>
    </tr>
    <tr>
      <td style="padding:4px 0;">
        <span style="color:#FF3C3C;font-size:15px;">■</span>
        보행보조장치 (0.88 m/s)
      </td>
      <td style="text-align:right;color:#ccc;">
        15분 {a[('aid',15)]:.2f} km² / 30분 {a[('aid',30)]:.2f} km²
      </td>
    </tr>
    <tr style="border-top:1px solid #333;margin-top:6px;">
      <td style="padding:8px 0 4px;color:#FFB800;font-weight:bold;">
        🟡 잃어버린 영역
      </td>
      <td style="text-align:right;color:#FFB800;font-weight:bold;">
        {a_lost:.2f} km²
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding:2px 0 10px;font-size:13px;color:#FF6060;font-weight:bold;">
        ▼ 면적 손실률: 15분 {loss_15:.1f}% · 30분 {loss_30:.1f}%
      </td>
    </tr>
  </table>

  <div style="border-top:1px solid #333;padding-top:10px;font-size:11px;">
    <div style="margin-bottom:4px;color:#bbb;">🚇 반경 내 지하철역 접근성</div>
    <span style="color:#00FF88;">●</span> 둘 다 가능: <b>{both_count}개역</b>&nbsp;&nbsp;
    <span style="color:#FFD700;">●</span> 일반인만: <b>{young_only_count}개역</b>&nbsp;&nbsp;
    <span style="color:#888;">●</span> 둘 다 불가: <b>{neither_count}개역</b>
  </div>

  <div style="border-top:1px solid #333;padding-top:8px;margin-top:8px;
              font-size:10px;color:#666;">
    출처: 한음 외 (2020). 한국ITS학회 19(4). n=4,857<br>
    보행 그래프: © OpenStreetMap contributors (osmnx 2.1.0)
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

title_html = f"""
<div style="
    position:fixed; top:10px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(10,10,20,0.92);
    border:1px solid #444; border-radius:8px;
    padding:10px 24px; text-align:center;
    font-family:'AppleGothic','Malgun Gothic',sans-serif;
    box-shadow:0 2px 12px rgba(0,0,0,0.5);">
  <div style="font-size:18px;font-weight:bold;color:#fff;">
    같은 30분, 다른 서울
  </div>
  <div style="font-size:11px;color:#aaa;margin-top:3px;">
    시각화 방법 A — Folium (Leaflet.js) &nbsp;|&nbsp;
    출발점: {START_NAME} · 강동구 길동 &nbsp;|&nbsp;
    일반인 <span style="color:#00C8FF">■</span> 1.28 m/s
    vs 보행보조장치 <span style="color:#FF3C3C">■</span> 0.88 m/s
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

out_a = OUTPUT_DIR / "02_isochrone_folium.html"
m.save(str(out_a))
logger.info("방법 A 저장: %s", out_a)


# ═══════════════════════════════════════════════════════════
#  방법 B: Plotly (Scattermapbox)
# ═══════════════════════════════════════════════════════════
logger.info("방법 B: Plotly 지도 생성 중…")

fig = go.Figure()

def add_poly_trace(fig, poly, name, fill_color, line_color, line_width=2,
                   legendgroup=None, showlegend=True, hovertext=""):
    if poly.geom_type == "MultiPolygon":
        parts = list(poly.geoms)
    else:
        parts = [poly]
    for i, part in enumerate(parts):
        lons, lats = poly_to_lonlat(part)
        fig.add_trace(go.Scattermapbox(
            lon=lons, lat=lats,
            mode="lines",
            fill="toself",
            fillcolor=fill_color,
            line=dict(color=line_color, width=line_width),
            name=name if i == 0 else None,
            legendgroup=legendgroup or name,
            showlegend=(showlegend and i == 0),
            hovertemplate=hovertext + "<extra></extra>",
        ))

# 청년 30분 (맨 아래)
add_poly_trace(fig, iso[("young", 30)],
    name="일반인 — 30분",
    fill_color="rgba(0,200,255,0.18)", line_color="rgba(0,200,255,0.7)", line_width=1.5,
    hovertext=f"일반인 30분 도달 범위<br>{a[('young',30)]:.3f} km²<br>보행속도 1.28 m/s")

# 보조장치 30분
add_poly_trace(fig, iso[("aid", 30)],
    name="보행보조장치 — 30분",
    fill_color="rgba(255,60,60,0.18)", line_color="rgba(255,60,60,0.7)", line_width=1.5,
    hovertext=f"보행보조장치 30분 도달 범위<br>{a[('aid',30)]:.3f} km²<br>보행속도 0.88 m/s")

# 잃어버린 영역
add_poly_trace(fig, lost_zone,
    name=f"잃어버린 영역 ({a_lost:.2f} km²)",
    fill_color="rgba(255,185,0,0.55)", line_color="rgba(255,165,0,0.9)", line_width=2,
    hovertext=f"⚠️ 잃어버린 영역<br>일반인은 도달 · 보행보조장치는 불가<br>{a_lost:.2f} km²")

# 청년 15분 (위에)
add_poly_trace(fig, iso[("young", 15)],
    name="일반인 — 15분",
    fill_color="rgba(0,200,255,0.40)", line_color="rgba(0,200,255,1.0)", line_width=2.5,
    hovertext=f"일반인 15분 도달 범위<br>{a[('young',15)]:.3f} km²")

# 보조장치 15분
add_poly_trace(fig, iso[("aid", 15)],
    name="보행보조장치 — 15분",
    fill_color="rgba(255,60,60,0.45)", line_color="rgba(255,60,60,1.0)", line_width=2.5,
    hovertext=f"보행보조장치 15분 도달 범위<br>{a[('aid',15)]:.3f} km²")

# 지하철역 마커 (상태별)
for status in ["both", "young_only", "neither"]:
    subset = [(n, lo, la) for n, lo, la, s in stations_classified if s == status]
    if not subset:
        continue
    names = [x[0] for x in subset]
    lons  = [x[1] for x in subset]
    lats  = [x[2] for x in subset]
    color = STATUS_COLOR[status]
    fig.add_trace(go.Scattermapbox(
        lon=lons, lat=lats,
        mode="markers+text",
        marker=dict(size=14, color=color,
                    symbol="circle"),
        text=names,
        textposition="top right",
        textfont=dict(size=10, color=color),
        name=STATUS_LABEL[status].replace("✅", "🟢").replace("⚠️", "🟡").replace("❌", "⚫"),
        hovertemplate="<b>%{text}</b><br>" + STATUS_LABEL[status] + "<extra></extra>",
    ))

# 주요 시설 마커
for status in ["both", "young_only", "neither"]:
    subset = [(n, lo, la, cat) for n, lo, la, cat, s in facilities_classified if s == status]
    if not subset:
        continue
    fig.add_trace(go.Scattermapbox(
        lon=[x[1] for x in subset],
        lat=[x[2] for x in subset],
        mode="markers+text",
        marker=dict(size=11, color=STATUS_COLOR[status], symbol="square"),
        text=[x[0] for x in subset],
        textposition="bottom right",
        textfont=dict(size=9, color=STATUS_COLOR[status]),
        name=f"시설·{STATUS_LABEL[status][:5]}",
        hovertemplate="<b>%{text}</b><br>" + STATUS_LABEL[status] + "<extra></extra>",
        showlegend=False,
    ))

# 출발점
fig.add_trace(go.Scattermapbox(
    lon=[START_LON], lat=[START_LAT],
    mode="markers+text",
    marker=dict(size=18, color="white", symbol="star"),
    text=[f"★ {START_NAME}"],
    textposition="top right",
    textfont=dict(size=13, color="white"),
    name=f"출발점: {START_NAME}",
    hovertemplate=f"<b>{START_NAME}</b><br>{START_DESC}<extra></extra>",
))

# 손실률 어노테이션
fig.add_annotation(
    x=0.01, y=0.25, xref="paper", yref="paper",
    xanchor="left", yanchor="top",
    text=(
        f"<b>📊 면적 손실률</b><br>"
        f"15분: <b><span style='color:#FF8C00'>{loss_15:.1f}%</span></b><br>"
        f"30분: <b><span style='color:#FF8C00'>{loss_30:.1f}%</span></b><br>"
        f"<br><span style='font-size:11px;color:#aaa'>"
        f"일반인 30분 {a[('young',30)]:.1f}km²<br>"
        f"보조장치 30분 {a[('aid',30)]:.1f}km²<br>"
        f"잃어버린 영역 {a_lost:.1f}km²</span>"
    ),
    bgcolor="rgba(15,15,25,0.88)",
    bordercolor="#555",
    borderwidth=1,
    font=dict(size=13, color="white",
              family="AppleGothic, Malgun Gothic, sans-serif"),
    align="left",
    showarrow=False,
)

fig.update_layout(
    mapbox=dict(
        style="carto-darkmatter",
        center=dict(lat=START_LAT, lon=START_LON),
        zoom=12.5,
    ),
    title=dict(
        text=(
            "<b style='font-size:18px'>같은 30분, 다른 서울</b>"
            f"<br><span style='font-size:11px;color:#aaa'>"
            f"시각화 방법 B — Plotly Scattermapbox (carto-darkmatter)  |  "
            f"출발점: {START_NAME} · {START_DESC}<br>"
            f"🔵 일반인 1.28 m/s &nbsp; 🔴 보행보조장치 0.88 m/s &nbsp; "
            f"🟡 잃어버린 영역  |  진한 = 15분, 연한 = 30분</span>"
        ),
        x=0.5,
        font=dict(family="AppleGothic, Malgun Gothic, sans-serif", color="white"),
    ),
    paper_bgcolor="#0a0a14",
    plot_bgcolor="#0a0a14",
    legend=dict(
        x=0.01, y=0.99, xanchor="left", yanchor="top",
        bgcolor="rgba(15,15,25,0.88)",
        bordercolor="#555",
        borderwidth=1,
        font=dict(size=11, color="white",
                  family="AppleGothic, Malgun Gothic, sans-serif"),
    ),
    font=dict(family="AppleGothic, Malgun Gothic, sans-serif", color="white"),
    height=750,
    margin=dict(l=0, r=0, t=100, b=0),
)

out_b = OUTPUT_DIR / "03_isochrone_plotly.html"
fig.write_html(str(out_b), include_plotlyjs=True)
logger.info("방법 B 저장: %s", out_b)


# ═══════════════════════════════════════════════════════════
#  방법 C: 통합 대시보드 HTML (04_dashboard.html)
#  - Tableau 임베드 / 단일 HTML 대시보드 모두 호환
#  - Plotly 지도 + 면적 비교 바 차트 + 통계 패널
# ═══════════════════════════════════════════════════════════
logger.info("방법 C: 통합 대시보드 HTML 생성 중…")

# C-1. 지도 figure (방법 B와 동일한 fig, full_html=False 로 div만 추출)
map_div = fig.to_html(
    full_html=False,
    include_plotlyjs=False,  # 대시보드 헤더에서 한 번만 로드
    div_id="map-chart",
    config={"responsive": True, "displayModeBar": True},
)

# C-2. 바 차트 (면적 비교)
bar_fig = go.Figure()
categories  = ["일반인 15분", "일반인 30분", "보조장치 15분", "보조장치 30분"]
bar_areas   = [a[("young",15)], a[("young",30)], a[("aid",15)], a[("aid",30)]]
bar_colors  = ["#00C8FF", "#0080AA", "#FF3C3C", "#AA1010"]

bar_fig.add_trace(go.Bar(
    x=categories,
    y=bar_areas,
    marker_color=bar_colors,
    marker_line_color="#333",
    marker_line_width=1,
    text=[f"{v:.2f} km²" for v in bar_areas],
    textposition="outside",
    textfont=dict(size=12, color="white"),
    hovertemplate="<b>%{x}</b><br>면적: %{y:.3f} km²<extra></extra>",
))

# 손실률 어노테이션
bar_fig.add_annotation(
    x=1.5, y=max(bar_areas) * 0.92,
    text=f"<b>30분 손실률<br>{loss_30:.1f}%</b>",
    font=dict(size=14, color="#FFB800"),
    showarrow=False,
    bgcolor="rgba(30,30,40,0.8)",
    bordercolor="#FFB800",
    borderwidth=1,
)

# 손실 화살표 (일반인 30min → 보조 30min)
bar_fig.add_annotation(
    x=1, y=a[("young",30)],
    ax=3, ay=a[("aid",30)],
    axref="x", ayref="y",
    xref="x", yref="y",
    arrowhead=3, arrowcolor="#FFB800", arrowwidth=2,
    text="", showarrow=True,
)

bar_fig.update_layout(
    title=dict(
        text="<b>도보 도달 가능 면적 비교</b><br><sup>일반인 vs 보행보조장치 사용 노인</sup>",
        font=dict(size=14, color="white"),
    ),
    paper_bgcolor="#0a0a14",
    plot_bgcolor="#111120",
    xaxis=dict(
        tickfont=dict(color="white", size=11),
        gridcolor="#222",
    ),
    yaxis=dict(
        title=dict(text="면적 (km²)", font=dict(color="#aaa")),
        tickfont=dict(color="#aaa"),
        gridcolor="#222",
    ),
    font=dict(family="AppleGothic, Malgun Gothic, sans-serif", color="white"),
    height=320,
    margin=dict(l=40, r=20, t=70, b=40),
)

bar_div = bar_fig.to_html(
    full_html=False,
    include_plotlyjs=False,
    div_id="bar-chart",
    config={"responsive": True, "displayModeBar": False},
)

# C-3. 랜드마크 테이블 (역 접근성)
rows_html = ""
for name, lo, la, status in sorted(stations_classified, key=lambda x: x[3]):
    color = STATUS_COLOR[status]
    label = STATUS_LABEL[status]
    rows_html += f"""
    <tr>
      <td style="padding:6px 10px;color:#eee;">{name}</td>
      <td style="padding:6px 10px;color:{color};font-weight:bold;">{label}</td>
    </tr>"""

# C-4. 통합 HTML 조립
dashboard_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>같은 30분, 다른 서울 — 대시보드</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #05050f;
      font-family: 'AppleGothic', 'Malgun Gothic', 'Noto Sans KR', sans-serif;
      color: #eee;
    }}

    /* ── 헤더 ── */
    .header {{
      background: linear-gradient(135deg, #0a0a20 0%, #1a1a35 100%);
      border-bottom: 1px solid #333;
      padding: 16px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .header-title h1 {{
      font-size: 22px;
      color: #fff;
      letter-spacing: -0.5px;
    }}
    .header-title p {{
      font-size: 12px;
      color: #888;
      margin-top: 3px;
    }}
    .header-kpi {{
      display: flex;
      gap: 20px;
    }}
    .kpi-box {{
      text-align: center;
      background: rgba(255,255,255,0.04);
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px 18px;
    }}
    .kpi-value {{
      font-size: 26px;
      font-weight: bold;
      color: #FF8C00;
    }}
    .kpi-label {{
      font-size: 11px;
      color: #888;
      margin-top: 2px;
    }}

    /* ── 메인 레이아웃 ── */
    .main {{
      display: grid;
      grid-template-columns: 1fr 360px;
      grid-template-rows: auto auto;
      gap: 0;
      height: calc(100vh - 80px);
    }}

    /* 지도 */
    .map-panel {{
      grid-row: 1 / 3;
      grid-column: 1;
      position: relative;
      overflow: hidden;
    }}
    .map-panel #map-chart {{
      width: 100%;
      height: 100%;
    }}
    .map-panel .plotly-graph-div {{
      height: 100% !important;
    }}

    /* 우측 사이드바 */
    .sidebar {{
      grid-column: 2;
      background: #080814;
      border-left: 1px solid #222;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
    }}

    .sidebar-section {{
      padding: 14px 16px;
      border-bottom: 1px solid #1e1e2e;
    }}
    .sidebar-section h3 {{
      font-size: 12px;
      color: #666;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 10px;
    }}

    /* 바 차트 */
    .bar-panel {{
      grid-column: 2;
    }}

    /* 속도 칩 */
    .speed-chips {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    .chip {{
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: bold;
    }}
    .chip-blue {{ background: rgba(0,200,255,0.15); border: 1px solid #00C8FF; color: #00C8FF; }}
    .chip-red  {{ background: rgba(255,60,60,0.15);  border: 1px solid #FF3C3C; color: #FF3C3C; }}

    /* 역 테이블 */
    .station-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .station-table tr:hover {{
      background: rgba(255,255,255,0.04);
    }}

    /* 푸터 */
    .footer {{
      padding: 10px 20px;
      font-size: 10px;
      color: #444;
      border-top: 1px solid #1a1a2a;
    }}
  </style>
</head>
<body>

<!-- ── 헤더 ── -->
<div class="header">
  <div class="header-title">
    <h1>같은 30분, 다른 서울</h1>
    <p>출발점: <strong style="color:#fff">{START_NAME}</strong>
       (강동구 길동 · 서울 동별 65세+ 인구 1위 · 10,386명)
       &nbsp;|&nbsp;
       보행 그래프: OSM © OpenStreetMap (osmnx 2.1.0, 노드 {G.number_of_nodes():,}개)
    </p>
  </div>
  <div class="header-kpi">
    <div class="kpi-box">
      <div class="kpi-value">{loss_15:.0f}%</div>
      <div class="kpi-label">15분 면적 손실</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value">{loss_30:.0f}%</div>
      <div class="kpi-label">30분 면적 손실</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value" style="color:#FFB800">{a_lost:.1f}</div>
      <div class="kpi-label">잃어버린 영역 (km²)</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value" style="color:#FFD700">{young_only_count}</div>
      <div class="kpi-label">청년만 접근 가능 역</div>
    </div>
  </div>
</div>

<!-- ── 메인 그리드 ── -->
<div class="main">

  <!-- 지도 -->
  <div class="map-panel">
    {map_div}
  </div>

  <!-- 우측 사이드바 -->
  <div class="sidebar">

    <!-- 보행속도 설명 -->
    <div class="sidebar-section">
      <h3>보행속도 기준</h3>
      <div class="speed-chips">
        <div class="chip chip-blue">일반인 1.28 m/s</div>
        <div class="chip chip-red">보행보조장치 0.88 m/s</div>
      </div>
      <p style="font-size:11px;color:#666;line-height:1.5;">
        출처: 한음 외 (2020). 노인보호구역 보행자녹색시간<br>
        산정을 위한 보행속도 기준 개선.<br>
        한국ITS학회 논문지 19(4). n=4,857명
      </p>
    </div>

    <!-- 바 차트 -->
    <div class="sidebar-section" style="padding:0;">
      {bar_div}
    </div>

    <!-- 지하철역 접근성 테이블 -->
    <div class="sidebar-section">
      <h3>🚇 반경 내 지하철역 접근성</h3>
      <table class="station-table">
        {rows_html}
      </table>
    </div>

    <!-- 색상 범례 -->
    <div class="sidebar-section">
      <h3>색상 범례</h3>
      <div style="font-size:12px;line-height:2.0;">
        <span style="color:#00C8FF;">■</span> 일반인 도달 범위<br>
        <span style="color:#FF3C3C;">■</span> 보행보조장치 도달 범위<br>
        <span style="color:#FFB800;">■</span> 잃어버린 영역 (일반인○ / 보조장치✗)<br>
        <span style="color:#00FF88;">●</span> 둘 다 30분 내 도달 가능 역<br>
        <span style="color:#FFD700;">●</span> 일반인만 30분 내 도달 가능 역<br>
        <span style="color:#888;">●</span> 둘 다 30분 내 도달 불가 역
      </div>
    </div>

  </div><!-- /sidebar -->
</div><!-- /main -->

<div class="footer">
  데이터: 서울시 주민등록인구 동별집계 (2025년 4분기) &nbsp;|&nbsp;
  보행 그래프: © OpenStreetMap contributors &nbsp;|&nbsp;
  분석: 한음 외 (2020) 한국ITS학회 논문지 &nbsp;|&nbsp;
  제작: 2026-04-18
</div>

<script>
  // 지도 패널 높이 동적 조정
  window.addEventListener('resize', function() {{
    var mapDiv = document.getElementById('map-chart');
    if (mapDiv) Plotly.relayout('map-chart', {{height: mapDiv.offsetHeight}});
  }});
</script>

</body>
</html>
"""

out_c = OUTPUT_DIR / "04_dashboard.html"
with open(out_c, "w", encoding="utf-8") as f:
    f.write(dashboard_html)
logger.info("방법 C 저장: %s", out_c)

print(f"\n{'='*60}")
print("▶ 모든 출력 완료")
print(f"{'='*60}")
print(f"  02_isochrone_folium.html   방법 A: Folium (Leaflet.js)")
print(f"  03_isochrone_plotly.html   방법 B: Plotly Scattermapbox")
print(f"  04_dashboard.html          방법 C: 통합 대시보드")
print(f"\n  면적 손실: 15분 {loss_15:.1f}%  |  30분 {loss_30:.1f}%")
print(f"  잃어버린 영역: {a_lost:.2f} km²")
print(f"  청년만 접근 가능 역: {young_only_count}개")
