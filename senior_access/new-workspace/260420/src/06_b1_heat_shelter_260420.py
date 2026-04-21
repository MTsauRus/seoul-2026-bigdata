"""
06_b1_heat_shelter_260420.py
폭염쉼터 — 노인 보행 접근성 분석
일반인(1.28 m/s) vs 보행보조장치 노인(0.88 m/s) × 15분/30분

출력: 06_b1_heat_shelter_260420.html
"""

import json, os, sys
import numpy as np
import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.ops import unary_union
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE    = "/Users/mtsaurus/Projects/seoul-2026-bigdata"
GRAPH   = f"{BASE}/senior_access/new-workspace/cache/seoul_walk_full.graphml"
SHELTER = f"{BASE}/노인친화아이디어/data/7_서울시 무더위쉼터.json"
DONG_SHP= f"{BASE}/senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
OUT_DIR = f"{BASE}/senior_access/new-workspace/260420/outputs"
CACHE   = f"{BASE}/senior_access/new-workspace/260420/cache/b1_heat_dist.json"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CACHE), exist_ok=True)

# ── 속도·거리 상수 ──────────────────────────────────────────────────────────────
V_YOUNG  = 1.28   # m/s 일반인
V_SENIOR = 0.88   # m/s 보행보조장치 노인

D_Y15  = V_YOUNG  * 15 * 60   # 1152 m
D_Y30  = V_YOUNG  * 30 * 60   # 2304 m
D_S15  = V_SENIOR * 15 * 60   #  792 m
D_S30  = V_SENIOR * 30 * 60   # 1584 m

def classify(dist):
    """행정동→쉼터 최단 도보 거리(m) → 5단계 분류"""
    if dist <= D_S15:   return "both_15"     # 둘 다 15분 이내
    if dist <= D_Y15:   return "young_15"    # 일반인만 15분 이내
    if dist <= D_S30:   return "both_30"     # 둘 다 30분 이내
    if dist <= D_Y30:   return "young_30"    # 일반인만 30분 이내
    return "neither"                          # 둘 다 30분 초과

# ── 1. 쉼터 로드 ───────────────────────────────────────────────────────────────
log.info("쉼터 데이터 로드")
with open(SHELTER, encoding="utf-8") as f:
    raw = json.load(f)["DATA"]
shelters = [s for s in raw if s.get("lat") and s.get("lon")]
log.info(f"  유효 폭염쉼터: {len(shelters):,}개")

# ── 2. 그래프 로드 ─────────────────────────────────────────────────────────────
log.info("그래프 로드 중... (첫 실행 시 수십 초 소요)")
G = ox.load_graphml(GRAPH)
G = ox.convert.to_undirected(G)
log.info(f"  노드 {G.number_of_nodes():,} / 엣지 {G.number_of_edges():,}")

# ── 3. 쉼터 노드 스냅 ──────────────────────────────────────────────────────────
log.info("쉼터 → 그래프 노드 스냅")
s_lons = [s["lon"] for s in shelters]
s_lats = [s["lat"] for s in shelters]
s_nodes = ox.nearest_nodes(G, s_lons, s_lats)
s_nodes_unique = list(set(s_nodes))
log.info(f"  고유 쉼터 노드: {len(s_nodes_unique):,}개")

# ── 4. 멀티소스 다익스트라 (쉼터 → 전체 그래프) ─────────────────────────────────
if os.path.exists(CACHE):
    log.info("캐시 로드")
    with open(CACHE) as f:
        dist_map = {int(k): v for k, v in json.load(f).items()}
else:
    log.info(f"멀티소스 Dijkstra ({len(s_nodes_unique):,} 출발점, 최대 {D_Y30:.0f}m)...")
    dist_map = nx.multi_source_dijkstra_path_length(
        G, s_nodes_unique, cutoff=D_Y30 * 1.05, weight="length"
    )
    dist_map = dict(dist_map)
    with open(CACHE, "w") as f:
        json.dump({str(k): v for k, v in dist_map.items()}, f)
    log.info("  캐시 저장 완료")

# ── 5. 행정동 shapefile 로드 & 분류 ───────────────────────────────────────────
log.info("행정동 shapefile 로드")
gdf = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
# 컬럼명 표준화 (소문자)
gdf.columns = [c.lower() for c in gdf.columns]
# 서울(코드 '11' 시작)만 필터링
code_col = next((c for c in gdf.columns if "cd" in c or "code" in c), None)
if code_col:
    gdf = gdf[gdf[code_col].astype(str).str.startswith("11")].copy()
# 동 이름 컬럼 탐색
name_col = next((c for c in gdf.columns if "nm" in c or "name" in c), gdf.columns[1])
log.info(f"  서울 행정동 수: {len(gdf)}, 이름 컬럼: {name_col}")

# 중심점 → 그래프 노드 스냅
centroids = gdf.geometry.centroid
c_lons = centroids.x.tolist()
c_lats = centroids.y.tolist()
log.info("행정동 중심점 → 그래프 노드 스냅")
c_nodes = ox.nearest_nodes(G, c_lons, c_lats)

# 거리 조회 & 분류
dists = [dist_map.get(n, 99999) for n in c_nodes]
gdf["dist_m"] = dists
gdf["category"] = [classify(d) for d in dists]

# 통계 출력
cat_counts = gdf["category"].value_counts()
log.info("분류 결과:")
for cat, cnt in cat_counts.items():
    log.info(f"  {cat}: {cnt}개 동")

# ── 6. GeoJSON 직렬화 ──────────────────────────────────────────────────────────
log.info("GeoJSON 생성 중...")
gdf_simple = gdf.copy()
gdf_simple["geometry"] = gdf_simple.geometry.simplify(0.002)

features = []
for _, row in gdf_simple.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    features.append({
        "type": "Feature",
        "geometry": geom.__geo_interface__,
        "properties": {
            "name": str(row.get(name_col, "")),
            "dist_m": round(row["dist_m"], 0),
            "category": row["category"],
        }
    })
dong_geojson = json.dumps({"type": "FeatureCollection", "features": features},
                           ensure_ascii=False)

# 쉼터 마커용 (전체)
shelter_pts = [{"lat": s["lat"], "lon": s["lon"],
                "name": s.get("r_area_nm", ""),
                "type2": s.get("facility_type2", ""),
                "cap": s.get("use_prnb", "")}
               for s in shelters]
shelter_json = json.dumps(shelter_pts, ensure_ascii=False)

# ── 7. 통계 계산 ───────────────────────────────────────────────────────────────
total = len(gdf)
n_both15   = (gdf["category"] == "both_15").sum()
n_young15  = (gdf["category"] == "young_15").sum()
n_both30   = (gdf["category"] == "both_30").sum()
n_young30  = (gdf["category"] == "young_30").sum()
n_neither  = (gdf["category"] == "neither").sum()

# 노인 사각지대 = young_15 (15분 내 일반인만) + young_30 (30분 내 일반인만) + neither
n_senior_gap = n_young15 + n_young30 + n_neither

stat_json = json.dumps({
    "total": int(total),
    "both_15": int(n_both15),
    "young_15": int(n_young15),
    "both_30": int(n_both30),
    "young_30": int(n_young30),
    "neither": int(n_neither),
    "senior_gap_pct": round(n_senior_gap / total * 100, 1),
    "shelter_count": len(shelters),
}, ensure_ascii=False)

# ── 8. HTML 생성 ───────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

COLOR = {
    "both_15":  "#00C853",   # 진초록 — 둘 다 15분 OK
    "young_15": "#FFD600",   # 노랑   — 일반인만 15분
    "both_30":  "#29B6F6",   # 하늘   — 둘 다 30분 OK
    "young_30": "#FF6D00",   # 주황   — 일반인만 30분
    "neither":  "#B71C1C",   # 진빨   — 둘 다 30분 초과
}

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>폭염쉼터 노인 보행 접근성 — 서울 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#1a1a2e;color:#eee;height:100vh;display:flex;flex-direction:column}}
#header{{background:#16213e;padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;border-bottom:1px solid #0f3460}}
#header h1{{font-size:1.1rem;font-weight:700;color:#fff}}
#header .sub{{font-size:.75rem;color:#90caf9;margin-left:4px}}
.ctrl-group{{display:flex;gap:6px;align-items:center}}
.ctrl-group label{{font-size:.75rem;color:#aaa}}
.btn{{padding:5px 12px;border:1px solid #444;background:#2a2a4a;color:#ddd;border-radius:4px;cursor:pointer;font-size:.78rem;transition:.15s}}
.btn.active{{background:#1565C0;border-color:#42A5F5;color:#fff}}
.btn:hover:not(.active){{background:#333}}
#map{{flex:1}}
#panel{{position:absolute;top:70px;right:12px;z-index:1000;background:rgba(22,33,62,.95);
        border:1px solid #0f3460;border-radius:8px;padding:14px;width:220px;
        box-shadow:0 4px 20px rgba(0,0,0,.5)}}
#panel h3{{font-size:.82rem;margin-bottom:10px;color:#90caf9;border-bottom:1px solid #0f3460;padding-bottom:6px}}
.legend-item{{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:.75rem}}
.legend-dot{{width:14px;height:14px;border-radius:3px;flex-shrink:0}}
.stat-box{{margin-top:12px;padding-top:10px;border-top:1px solid #0f3460;font-size:.73rem;color:#bbb;line-height:1.7}}
.stat-box strong{{color:#fff}}
#info-box{{position:absolute;bottom:30px;left:12px;z-index:1000;background:rgba(22,33,62,.93);
           border:1px solid #0f3460;border-radius:6px;padding:10px 14px;min-width:200px;
           font-size:.76rem;display:none}}
#info-box .ib-name{{font-weight:700;font-size:.85rem;margin-bottom:4px;color:#fff}}
#info-box .ib-row{{color:#ccc;margin-bottom:2px}}
</style>
</head>
<body>
<div id="header">
  <h1>🌡️ 폭염쉼터 노인 보행 접근성 <span class="sub">일반인(1.28 m/s) vs 보행보조장치 노인(0.88 m/s)</span></h1>
  <div class="ctrl-group">
    <label>시간 기준</label>
    <button class="btn active" id="btn15" onclick="setTime(15)">15분</button>
    <button class="btn" id="btn30" onclick="setTime(30)">30분</button>
  </div>
  <div class="ctrl-group">
    <label>지도</label>
    <button class="btn active" id="tile-osm" onclick="setTile('osm',this)">일반</button>
    <button class="btn" id="tile-esri" onclick="setTile('esri',this)">위성</button>
    <button class="btn" id="tile-dark" onclick="setTile('dark',this)">Dark</button>
  </div>
  <div class="ctrl-group">
    <label>쉼터</label>
    <button class="btn active" id="btn-shelter" onclick="toggleShelter(this)">표시 ON</button>
  </div>
</div>
<div id="map"></div>

<div id="panel">
  <h3>📊 범례 &amp; 통계</h3>
  <div id="legend-items"></div>
  <div class="stat-box" id="stat-box"></div>
</div>
<div id="info-box">
  <div class="ib-name" id="ib-name">-</div>
  <div class="ib-row" id="ib-dist">-</div>
  <div class="ib-row" id="ib-cat">-</div>
</div>

<script>
const DONG_DATA = {dong_geojson};
const SHELTERS  = {shelter_json};
const STATS     = {stat_json};
const COLORS = {{
  both_15:  "{COLOR['both_15']}",
  young_15: "{COLOR['young_15']}",
  both_30:  "{COLOR['both_30']}",
  young_30: "{COLOR['young_30']}",
  neither:  "{COLOR['neither']}",
}};

// 15분 / 30분 범례 정의
const LEGENDS = {{
  15: [
    {{key:"both_15",  label:"둘 다 15분 이내 도달 가능", color:COLORS.both_15}},
    {{key:"young_15", label:"일반인만 15분 이내 (노인 불가)", color:COLORS.young_15}},
    {{key:"neither15",label:"둘 다 15분 초과 (30분은 가능)", color:"#546E7A"}},
    {{key:"gap",      label:"일반인도 30분 초과", color:COLORS.neither}},
  ],
  30: [
    {{key:"both_30a", label:"둘 다 15분 이내", color:COLORS.both_15}},
    {{key:"both_30b", label:"둘 다 30분 이내 (노인 15분 초과)", color:COLORS.both_30}},
    {{key:"young_30", label:"일반인만 30분 이내 (노인 불가)", color:COLORS.young_30}},
    {{key:"neither",  label:"둘 다 30분 초과", color:COLORS.neither}},
  ]
}};

// ─── 지도 초기화 ───────────────────────────────────────────────────────────────
const map = L.map('map', {{center:[37.5665,126.9780], zoom:11, zoomControl:true}});

const TILES = {{
  osm:  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          {{attribution:'© OpenStreetMap', maxZoom:19}}),
  esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
          {{attribution:'© Esri', maxZoom:19}}),
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
          {{attribution:'© CartoDB', maxZoom:19}}),
}};
let curTile = 'osm';
TILES.osm.addTo(map);

function setTile(key, btn){{
  map.removeLayer(TILES[curTile]);
  TILES[key].addTo(map);
  curTile = key;
  document.querySelectorAll('[id^=tile-]').forEach(b=>b.classList.remove('active'));
  document.getElementById('tile-'+key).classList.add('active');
}}

// ─── 행정동 레이어 ─────────────────────────────────────────────────────────────
let curTime = 15;
let dongLayer;
const CAT_MAP = {{
  both_15:'both_15', young_15:'young_15', both_30:'both_30', young_30:'young_30', neither:'neither'
}};

function catColor(cat, time){{
  if(time===15){{
    if(cat==='both_15') return COLORS.both_15;
    if(cat==='young_15') return COLORS.young_15;
    if(cat==='both_30') return '#546E7A';   // 15분 초과지만 30분은 가능
    if(cat==='young_30') return '#546E7A';
    return COLORS.neither;
  }} else {{
    if(cat==='both_15') return COLORS.both_15;
    if(cat==='young_15') return COLORS.young_30;  // 30분 뷰에서는 주황
    if(cat==='both_30') return COLORS.both_30;
    if(cat==='young_30') return COLORS.young_30;
    return COLORS.neither;
  }}
}}

function catLabel(cat){{
  const M={{both_15:'둘 다 15분 이내',young_15:'일반인만 15분',
            both_30:'둘 다 30분 이내',young_30:'일반인만 30분',neither:'둘 다 30분 초과'}};
  return M[cat]||cat;
}}

function buildDong(time){{
  if(dongLayer) map.removeLayer(dongLayer);
  dongLayer = L.geoJSON(DONG_DATA, {{
    style: f=>{{
      const c = catColor(f.properties.category, time);
      return {{fillColor:c, fillOpacity:.65, color:'#fff', weight:.4, opacity:.5}};
    }},
    onEachFeature:(f,layer)=>{{
      layer.on('click', ()=>{{
        const p = f.properties;
        document.getElementById('ib-name').textContent = p.name;
        document.getElementById('ib-dist').textContent =
          '쉼터까지 최단 거리: ' + (p.dist_m>=99000?'측정불가':p.dist_m+'m');
        const timeY15 = p.dist_m<99000?(p.dist_m/1.28/60).toFixed(1)+'분':'—';
        const timeS15 = p.dist_m<99000?(p.dist_m/0.88/60).toFixed(1)+'분':'—';
        document.getElementById('ib-cat').innerHTML =
          '일반인: <strong>'+timeY15+'</strong> / 노인: <strong>'+timeS15+'</strong>';
        document.getElementById('info-box').style.display='block';
      }});
    }}
  }}).addTo(map);
}}
buildDong(15);

function setTime(t){{
  curTime = t;
  buildDong(t);
  document.getElementById('btn15').classList.toggle('active', t===15);
  document.getElementById('btn30').classList.toggle('active', t===30);
  updateLegend(t);
}}

// ─── 쉼터 마커 ────────────────────────────────────────────────────────────────
const shelterGroup = L.layerGroup();
SHELTERS.forEach(s=>{{
  L.circleMarker([s.lat, s.lon], {{
    radius:4, fillColor:'#FF5722', color:'#fff',
    weight:1, fillOpacity:.85
  }}).bindTooltip(`<b>${{s.name||'폭염쉼터'}}</b><br>${{s.type2||''}}<br>수용인원: ${{s.cap||'?'}}명`,
    {{direction:'top', className:'shelter-tip'}}).addTo(shelterGroup);
}});
shelterGroup.addTo(map);

let shelterOn = true;
function toggleShelter(btn){{
  shelterOn = !shelterOn;
  shelterOn ? shelterGroup.addTo(map) : map.removeLayer(shelterGroup);
  btn.textContent = shelterOn ? '표시 ON' : '표시 OFF';
  btn.classList.toggle('active', shelterOn);
}}

// ─── 범례 ──────────────────────────────────────────────────────────────────────
function updateLegend(t){{
  const el = document.getElementById('legend-items');
  const items = t===15 ? [
    {{color:COLORS.both_15,  label:'둘 다 15분 이내'}},
    {{color:COLORS.young_15, label:'일반인만 15분 (노인 불가)'}},
    {{color:'#546E7A',        label:'둘 다 15분 초과 (30분 가능)'}},
    {{color:COLORS.neither,  label:'둘 다 30분 초과'}},
  ] : [
    {{color:COLORS.both_15,  label:'둘 다 15분 이내'}},
    {{color:COLORS.both_30,  label:'둘 다 30분 이내'}},
    {{color:COLORS.young_30, label:'일반인만 30분 (노인 불가)'}},
    {{color:COLORS.neither,  label:'둘 다 30분 초과'}},
  ];
  el.innerHTML = items.map(i=>
    `<div class="legend-item"><div class="legend-dot" style="background:${{i.color}}"></div>${{i.label}}</div>`
  ).join('');
}}
updateLegend(15);

// 통계
const sb = document.getElementById('stat-box');
sb.innerHTML = `
  <strong>서울 폭염쉼터</strong> ${{STATS.shelter_count.toLocaleString()}}개<br>
  행정동 ${{STATS.total}}개 분석<br><br>
  <span style="color:#00C853">■</span> 노인 15분 OK: <strong>${{STATS.both_15}}</strong>개 동<br>
  <span style="color:#FFD600">■</span> 일반인만 15분: <strong>${{STATS.young_15}}</strong>개 동<br>
  <span style="color:#29B6F6">■</span> 노인 30분 OK: <strong>${{STATS.both_30}}</strong>개 동<br>
  <span style="color:#FF6D00">■</span> 일반인만 30분: <strong>${{STATS.young_30}}</strong>개 동<br>
  <span style="color:#B71C1C">■</span> 둘 다 불가: <strong>${{STATS.neither}}</strong>개 동<br><br>
  <span style="color:#ff8a80">노인 사각지대 동: <strong>${{STATS.senior_gap_pct}}%</strong></span>
`;

// 지도 클릭으로 info-box 닫기
map.on('click', ()=>{{
  // 빈 곳 클릭 시 닫지 않음 (feature 클릭으로만 열림)
}});
</script>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, "06_b1_heat_shelter_260420.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {os.path.getsize(out_path)//1024} KB")
