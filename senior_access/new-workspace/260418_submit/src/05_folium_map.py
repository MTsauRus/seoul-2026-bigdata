"""
05_folium_map.py
-----------------
강동구 길동사거리 기준, 일반인 vs 보행보조장치 노인의
30분 도보 도달 영역 Folium 인터랙티브 지도.

개선 사항 (v2):
  1. 타일 3종 토글: 일반지도(OSM) / 위성(Esri) / Dark(CartoDB)
  2. 15분 레이어 제거, 30분만 표시
  3. 잃어버린 영역 → GeoJson으로 교체 (도넛 구멍 정상 렌더)
  4. "둘다 불가" 마커 제거

출력: ../outputs/05_folium_map.html
"""

import logging
import warnings
from pathlib import Path

import networkx as nx
import osmnx as ox
from shapely.geometry import MultiPoint, Point
import pyproj
from shapely.ops import transform as shp_transform
import folium

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

SPEED_YOUNG = 1.28   # 일반인 (한음 외 2020)
SPEED_AID   = 0.88   # 보행보조장치 사용 노인

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
iso_young = compute_iso(G, start_node, SPEED_YOUNG, 30, "일반인")
iso_aid   = compute_iso(G, start_node, SPEED_AID,   30, "보조장치")

# 잃어버린 영역 = 일반인 30분 - 보조장치 30분
# shapely difference()는 exterior + interiors(구멍)를 포함한 Polygon 반환
# → GeoJson으로 렌더하면 도넛 모양이 정상 출력됨
lost_zone = iso_young.difference(iso_aid)
logger.info("잃어버린 영역 타입: %s", lost_zone.geom_type)


# ── 3. 면적 계산 ─────────────────────────────────────────
_to5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

def area_km2(poly):
    return shp_transform(_to5179.transform, poly).area / 1e6

a_young = area_km2(iso_young)
a_aid   = area_km2(iso_aid)
a_lost  = area_km2(lost_zone)
loss_30 = (1 - a_aid / a_young) * 100

print(f"\n{'='*55}")
print(f"▶ 면적 비교 (출발점: {START_NAME})")
print(f"{'='*55}")
print(f"  일반인 30분:  {a_young:.3f} km²")
print(f"  보조장치 30분: {a_aid:.3f} km²")
print(f"  잃어버린 영역: {a_lost:.3f} km²  (손실 {loss_30:.1f}%)")


# ── 4. 랜드마크 ───────────────────────────────────────────
STATIONS = [
    ("길동역(5호선)",        127.14020, 37.53837),
    ("강동역(5호선)",        127.13260, 37.53580),
    ("천호역(5/8호선)",      127.12340, 37.53852),
    ("굽은다리역(5호선)",    127.14296, 37.54564),
    ("명일역(5호선)",        127.14408, 37.55195),
    ("강동구청역(8호선)",    127.12062, 37.53069),
    ("암사역(8호선)",        127.12754, 37.55011),
    ("둔촌동역(5호선)",      127.13624, 37.52780),
    ("올림픽공원역(5호선)",  127.13093, 37.51615),
    ("잠실나루역(2호선)",    127.10383, 37.52069),
]

FACILITIES = [
    ("강동경희대병원",  127.1527, 37.5557, "hospital"),
    ("강동성심병원",    127.1494, 37.5310, "hospital"),
    ("강동구청",        127.1237, 37.5521, "gov"),
    ("강동구 보건소",   127.1377, 37.5525, "health"),
    ("롯데마트 천호점", 127.1265, 37.5374, "market"),
    ("이마트 성내점",   127.1262, 37.5253, "market"),
    ("길동생태공원",    127.1499, 37.5361, "park"),
]

ICON_MAP = {
    "hospital": "➕",
    "health":   "🏥",
    "gov":      "🏛️",
    "market":   "🛒",
    "park":     "🌿",
}

def classify(lon, lat):
    p = Point(lon, lat)
    in_young = iso_young.contains(p)
    in_aid   = iso_aid.contains(p)
    if in_young and in_aid:
        return "both"
    elif in_young:
        return "young_only"
    return "neither"

STATUS_COLOR = {
    "both":       "#00FF88",
    "young_only": "#FFD700",
}
STATUS_LABEL = {
    "both":       "✅ 둘 다 30분 내 도달",
    "young_only": "⚠️ 일반인만 30분 내 도달",
}

stations_classified   = [(n, lo, la, classify(lo, la)) for n, lo, la in STATIONS]
facilities_classified = [(n, lo, la, c, classify(lo, la)) for n, lo, la, c in FACILITIES]


# ── 5. Folium 지도 ────────────────────────────────────────
logger.info("Folium 지도 생성 중…")

# tiles=None → 직접 TileLayer 추가
m = folium.Map(
    location=[START_LAT, START_LON],
    zoom_start=13,
    tiles=None,
    prefer_canvas=True,
)

# ── 타일 레이어 3종 ──────────────────────────────────────
folium.TileLayer("OpenStreetMap", name="🗺️ 일반 지도 (OSM)").add_to(m)
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services"
        "/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri World Imagery",
    name="🛰️ 위성지도 (Esri)",
).add_to(m)
folium.TileLayer(
    "CartoDB dark_matter", name="🌑 Dark Map (CartoDB)"
).add_to(m)

# ── 보조장치 30분 (빨강) ─────────────────────────────────
fg_aid = folium.FeatureGroup(name="🔴 보행보조장치 — 30분 도달", show=True)
folium.GeoJson(
    data=iso_aid.__geo_interface__,
    style_function=lambda x: {
        "fillColor": "#FF3C3C",
        "color":     "#FF3C3C",
        "weight":    2,
        "fillOpacity": 0.30,
        "opacity":     0.85,
    },
    tooltip=f"🔴 보행보조장치 30분 ({a_aid:.2f} km²)",
).add_to(fg_aid)
fg_aid.add_to(m)

# ── 일반인 30분 (파랑, 연한 fill) ────────────────────────
fg_young = folium.FeatureGroup(name="🔵 일반인 — 30분 도달", show=True)
folium.GeoJson(
    data=iso_young.__geo_interface__,
    style_function=lambda x: {
        "fillColor": "#00C8FF",
        "color":     "#00C8FF",
        "weight":    2,
        "fillOpacity": 0.15,
        "opacity":     0.85,
    },
    tooltip=f"🔵 일반인 30분 ({a_young:.2f} km²)",
).add_to(fg_young)
fg_young.add_to(m)

# ── 잃어버린 영역 (주황, GeoJson → 도넛 렌더) ────────────
# GeoJSON spec 상 Polygon/MultiPolygon의 interiors(구멍)를 지원하므로
# shapely difference()의 결과를 그대로 넘기면 도넛 모양이 정확히 출력됨
fg_lost = folium.FeatureGroup(
    name="🟡 잃어버린 영역 (일반인만 접근)", show=True
)
folium.GeoJson(
    data=lost_zone.__geo_interface__,
    style_function=lambda x: {
        "fillColor": "#FFB800",
        "color":     "#FFB800",
        "weight":    2.5,
        "fillOpacity": 0.55,
        "opacity":     0.95,
    },
    tooltip=(
        f"⚠️ 잃어버린 영역<br>"
        f"일반인만 도달 가능 · 보행보조장치 불가<br>"
        f"면적: {a_lost:.2f} km² | 손실률: {loss_30:.1f}%"
    ),
).add_to(fg_lost)
fg_lost.add_to(m)

# ── 지하철역 (neither 제외) ──────────────────────────────
fg_subway = folium.FeatureGroup(name="🚇 지하철역", show=True)
for name, lo, la, status in stations_classified:
    if status == "neither":
        continue
    color = STATUS_COLOR[status]
    label = STATUS_LABEL[status]
    folium.CircleMarker(
        location=[la, lo],
        radius=10,
        color="#000",
        weight=1.2,
        fill=True,
        fill_color=color,
        fill_opacity=0.95,
        tooltip=folium.Tooltip(f"<b>{name}</b><br>{label}", sticky=True),
        popup=folium.Popup(
            f"<b>{name}</b><br>{label}<br>"
            f"<span style='font-size:11px;color:#555'>"
            f"경도: {lo:.5f} / 위도: {la:.5f}</span>",
            max_width=200,
        ),
    ).add_to(fg_subway)
    folium.map.Marker(
        location=[la, lo],
        icon=folium.DivIcon(
            html=(
                f'<div style="font-size:10px;color:{color};font-weight:bold;'
                f'text-shadow:1px 1px 2px #000;white-space:nowrap;'
                f'margin-top:-20px;margin-left:12px;">{name}</div>'
            ),
            icon_size=(130, 20),
        ),
    ).add_to(fg_subway)
fg_subway.add_to(m)

# ── 주요 시설 (neither 제외) ─────────────────────────────
fg_fac = folium.FeatureGroup(name="🏢 주요 시설", show=True)
for name, lo, la, cat, status in facilities_classified:
    if status == "neither":
        continue
    icon_sym    = ICON_MAP.get(cat, "📍")
    status_color = STATUS_COLOR[status]
    folium.CircleMarker(
        location=[la, lo],
        radius=9,
        color="#000",
        weight=1,
        fill=True,
        fill_color=status_color,
        fill_opacity=0.9,
        tooltip=folium.Tooltip(
            f"<b>{icon_sym} {name}</b><br>{STATUS_LABEL[status]}", sticky=True
        ),
    ).add_to(fg_fac)
    folium.map.Marker(
        location=[la, lo],
        icon=folium.DivIcon(
            html=(
                f'<div style="font-size:9px;color:{status_color};font-weight:bold;'
                f'text-shadow:1px 1px 2px #000;white-space:nowrap;'
                f'margin-top:-18px;margin-left:10px;">{name}</div>'
            ),
            icon_size=(120, 18),
        ),
    ).add_to(fg_fac)
fg_fac.add_to(m)

# ── 출발점 ────────────────────────────────────────────────
folium.Marker(
    location=[START_LAT, START_LON],
    tooltip=f"<b>출발점: {START_NAME}</b><br>{START_DESC}",
    popup=folium.Popup(
        f"<b>{START_NAME}</b><br><small>{START_DESC}</small>", max_width=260
    ),
    icon=folium.Icon(color="white", icon="star", prefix="fa"),
).add_to(m)

folium.LayerControl(collapsed=False, position="topright").add_to(m)

# ── 범례 ─────────────────────────────────────────────────
both_count       = sum(1 for _, _, _, s in stations_classified if s == "both")
young_only_count = sum(1 for _, _, _, s in stations_classified if s == "young_only")

legend_html = f"""
<div style="
    position:fixed; bottom:20px; left:16px; z-index:9999;
    background:rgba(15,15,25,0.93); border:1px solid #333;
    border-radius:10px; padding:16px 20px;
    font-family:'AppleGothic','Malgun Gothic',sans-serif;
    color:#eee; min-width:285px; max-width:320px;
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
        일반인 (1.28 m/s) — 30분
      </td>
      <td style="text-align:right;color:#ccc;">{a_young:.2f} km²</td>
    </tr>
    <tr>
      <td style="padding:4px 0;">
        <span style="color:#FF3C3C;font-size:15px;">■</span>
        보행보조장치 (0.88 m/s) — 30분
      </td>
      <td style="text-align:right;color:#ccc;">{a_aid:.2f} km²</td>
    </tr>
    <tr style="border-top:1px solid #333;">
      <td style="padding:8px 0 4px;color:#FFB800;font-weight:bold;">
        🟡 잃어버린 영역
      </td>
      <td style="text-align:right;color:#FFB800;font-weight:bold;">
        {a_lost:.2f} km²
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding:2px 0 10px;font-size:13px;
          color:#FF6060;font-weight:bold;">
        ▼ 30분 면적 손실률: {loss_30:.1f}%
      </td>
    </tr>
  </table>

  <div style="border-top:1px solid #333;padding-top:10px;font-size:11px;">
    <div style="margin-bottom:4px;color:#bbb;">🚇 반경 내 지하철역 접근성</div>
    <span style="color:#00FF88;">●</span> 둘 다 가능: <b>{both_count}개역</b>
    &nbsp;&nbsp;
    <span style="color:#FFD700;">●</span> 일반인만: <b>{young_only_count}개역</b>
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
    출발점: {START_NAME} · 강동구 길동 (동별 65세+ 1위)
    &nbsp;|&nbsp;
    일반인 <span style="color:#00C8FF">■</span> 1.28 m/s
    vs 보행보조장치 <span style="color:#FF3C3C">■</span> 0.88 m/s
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

out_path = OUTPUT_DIR / "05_folium_map.html"
m.save(str(out_path))
logger.info("저장 완료: %s", out_path)
print(f"\n✅ 출력 → {out_path}")
