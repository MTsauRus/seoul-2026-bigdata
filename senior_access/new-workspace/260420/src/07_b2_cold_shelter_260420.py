"""
07_b2_cold_shelter_260420.py
한파쉼터 — 노인 보행 접근성 분석
일반인(1.28 m/s) vs 보행보조장치 노인(0.88 m/s) × 15분/30분

출력: 07_b2_cold_shelter_260420.html
"""

import json, os
import geopandas as gpd
import networkx as nx
import osmnx as ox
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE    = "/Users/mtsaurus/Projects/seoul-2026-bigdata"
GRAPH   = f"{BASE}/senior_access/new-workspace/cache/seoul_walk_full.graphml"
SHELTER = f"{BASE}/노인친화아이디어/data/8_서울시 한파쉼터.json"
DONG_SHP= f"{BASE}/senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
OUT_DIR = f"{BASE}/senior_access/new-workspace/260420/outputs"
CACHE   = f"{BASE}/senior_access/new-workspace/260420/cache/b2_cold_dist.json"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CACHE), exist_ok=True)

# ── 속도·거리 상수 ──────────────────────────────────────────────────────────────
V_YOUNG  = 1.28
V_SENIOR = 0.88

D_Y15  = V_YOUNG  * 15 * 60   # 1152 m
D_Y30  = V_YOUNG  * 30 * 60   # 2304 m
D_S15  = V_SENIOR * 15 * 60   #  792 m
D_S30  = V_SENIOR * 30 * 60   # 1584 m

def classify(dist):
    if dist <= D_S15:   return "both_15"
    if dist <= D_Y15:   return "young_15"
    if dist <= D_S30:   return "both_30"
    if dist <= D_Y30:   return "young_30"
    return "neither"

# ── 1. 쉼터 로드 ───────────────────────────────────────────────────────────────
log.info("한파쉼터 데이터 로드")
with open(SHELTER, encoding="utf-8") as f:
    raw = json.load(f)["DATA"]
# 한파쉼터는 lat/lot(lon) 컬럼
shelters = [s for s in raw if s.get("lat") and s.get("lot")]
log.info(f"  유효 한파쉼터: {len(shelters):,}개")

# ── 2. 그래프 로드 ─────────────────────────────────────────────────────────────
log.info("그래프 로드 중...")
G = ox.load_graphml(GRAPH)
G = ox.convert.to_undirected(G)
log.info(f"  노드 {G.number_of_nodes():,} / 엣지 {G.number_of_edges():,}")

# ── 3. 쉼터 노드 스냅 ──────────────────────────────────────────────────────────
log.info("쉼터 → 그래프 노드 스냅")
s_lons = [s["lot"] for s in shelters]
s_lats = [s["lat"] for s in shelters]
s_nodes = ox.nearest_nodes(G, s_lons, s_lats)
s_nodes_unique = list(set(s_nodes))
log.info(f"  고유 쉼터 노드: {len(s_nodes_unique):,}개")

# ── 4. 멀티소스 다익스트라 ─────────────────────────────────────────────────────
if os.path.exists(CACHE):
    log.info("캐시 로드")
    with open(CACHE) as f:
        dist_map = {int(k): v for k, v in json.load(f).items()}
else:
    log.info(f"멀티소스 Dijkstra ({len(s_nodes_unique):,} 출발점, cutoff {D_Y30:.0f}m)...")
    dist_map = dict(nx.multi_source_dijkstra_path_length(
        G, s_nodes_unique, cutoff=D_Y30 * 1.05, weight="length"
    ))
    with open(CACHE, "w") as f:
        json.dump({str(k): v for k, v in dist_map.items()}, f)
    log.info("  캐시 저장 완료")

# ── 5. 행정동 분류 ─────────────────────────────────────────────────────────────
log.info("행정동 shapefile 로드")
gdf = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf.columns = [c.lower() for c in gdf.columns]
code_col = next((c for c in gdf.columns if "cd" in c), None)
if code_col:
    gdf = gdf[gdf[code_col].astype(str).str.startswith("11")].copy()
name_col = next((c for c in gdf.columns if "nm" in c or "name" in c), gdf.columns[1])
log.info(f"  서울 행정동: {len(gdf)}")

gdf_p = gdf.to_crs("EPSG:5179")
centroids = gdf_p.geometry.centroid
gdf_p["cx"] = centroids.x
gdf_p["cy"] = centroids.y
gdf_wgs = gdf_p.to_crs("EPSG:4326")
c_lons = gdf_p.set_crs("EPSG:5179").to_crs("EPSG:4326").geometry.centroid.x.tolist()
c_lats = gdf_p.set_crs("EPSG:5179").to_crs("EPSG:4326").geometry.centroid.y.tolist()

log.info("중심점 → 그래프 노드 스냅")
c_nodes = ox.nearest_nodes(G, c_lons, c_lats)
dists = [dist_map.get(n, 99999) for n in c_nodes]
gdf["dist_m"]   = dists
gdf["category"] = [classify(d) for d in dists]

cat_counts = gdf["category"].value_counts()
log.info("분류 결과:")
for cat, cnt in cat_counts.items():
    log.info(f"  {cat}: {cnt}개 동")

# ── 6. GeoJSON 직렬화 ──────────────────────────────────────────────────────────
log.info("GeoJSON 생성 중...")
gdf_s = gdf.copy()
gdf_s["geometry"] = gdf_s.geometry.simplify(0.002)

features = []
for _, row in gdf_s.iterrows():
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

shelter_pts = [{"lat": s["lat"], "lon": s["lot"],
                "name": s.get("restarea_nm", "한파쉼터"),
                "type2": s.get("facility_type2", ""),
                "cap": s.get("utztn_psblty_nope", "")}
               for s in shelters]
shelter_json = json.dumps(shelter_pts, ensure_ascii=False)

# ── 7. 통계 ───────────────────────────────────────────────────────────────────
total = len(gdf)
n_b15 = (gdf["category"] == "both_15").sum()
n_y15 = (gdf["category"] == "young_15").sum()
n_b30 = (gdf["category"] == "both_30").sum()
n_y30 = (gdf["category"] == "young_30").sum()
n_no  = (gdf["category"] == "neither").sum()
gap_pct = round((n_y15 + n_y30 + n_no) / total * 100, 1)

stat_json = json.dumps({
    "total": int(total),
    "both_15": int(n_b15), "young_15": int(n_y15),
    "both_30": int(n_b30), "young_30": int(n_y30),
    "neither": int(n_no),
    "senior_gap_pct": gap_pct,
    "shelter_count": len(shelters),
}, ensure_ascii=False)

# ── 8. HTML ────────────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>한파쉼터 노인 보행 접근성 — 서울 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#1a1a2e;color:#eee;height:100vh;display:flex;flex-direction:column}}
#header{{background:#0d2137;padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;border-bottom:2px solid #1565C0}}
#header h1{{font-size:1.1rem;font-weight:700;color:#fff}}
#header .sub{{font-size:.75rem;color:#90caf9;margin-left:4px}}
.ctrl-group{{display:flex;gap:6px;align-items:center}}
.ctrl-group label{{font-size:.75rem;color:#aaa}}
.btn{{padding:5px 12px;border:1px solid #444;background:#1a2a4a;color:#ddd;border-radius:4px;cursor:pointer;font-size:.78rem;transition:.15s}}
.btn.active{{background:#0277BD;border-color:#29B6F6;color:#fff}}
.btn:hover:not(.active){{background:#2a3a5a}}
#map{{flex:1}}
#panel{{position:absolute;top:70px;right:12px;z-index:1000;background:rgba(13,33,55,.95);
        border:1px solid #1565C0;border-radius:8px;padding:14px;width:230px;
        box-shadow:0 4px 20px rgba(0,0,0,.6)}}
#panel h3{{font-size:.82rem;margin-bottom:10px;color:#64B5F6;border-bottom:1px solid #1565C0;padding-bottom:6px}}
.legend-item{{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:.75rem}}
.legend-dot{{width:14px;height:14px;border-radius:3px;flex-shrink:0}}
.stat-box{{margin-top:12px;padding-top:10px;border-top:1px solid #1565C0;font-size:.73rem;color:#bbb;line-height:1.8}}
.stat-box strong{{color:#fff}}
#compare-box{{position:absolute;top:70px;left:12px;z-index:1000;background:rgba(13,33,55,.93);
              border:1px solid #1565C0;border-radius:8px;padding:14px;width:200px;font-size:.76rem}}
#compare-box h4{{color:#64B5F6;margin-bottom:8px;font-size:.8rem}}
.cmp-row{{margin-bottom:5px;color:#ccc}}
.cmp-val{{color:#fff;font-weight:700}}
#info-box{{position:absolute;bottom:30px;left:12px;z-index:1000;background:rgba(13,33,55,.93);
           border:1px solid #1565C0;border-radius:6px;padding:10px 14px;min-width:200px;
           font-size:.76rem;display:none}}
#info-box .ib-name{{font-weight:700;font-size:.85rem;margin-bottom:4px;color:#fff}}
#info-box .ib-row{{color:#ccc;margin-bottom:2px}}
</style>
</head>
<body>
<div id="header">
  <h1>❄️ 한파쉼터 노인 보행 접근성 <span class="sub">일반인(1.28 m/s) vs 보행보조장치 노인(0.88 m/s)</span></h1>
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
  both_15:  "#00BCD4",   // 청록   — 둘 다 15분 OK
  young_15: "#FFF176",   // 연노랑 — 일반인만 15분
  both_30:  "#4FC3F7",   // 하늘   — 둘 다 30분 OK
  young_30: "#FF7043",   // 주황   — 일반인만 30분
  neither:  "#B71C1C",   // 진빨   — 둘 다 30분 초과
  neutral:  "#455A64",   // 회청   — 15분 초과 but 30분 가능
}};

const map = L.map('map', {{center:[37.5665,126.9780], zoom:11}});
const TILES = {{
  osm:  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          {{attribution:'© OpenStreetMap', maxZoom:19}}),
  esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
          {{attribution:'© Esri', maxZoom:19}}),
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
          {{attribution:'© CartoDB', maxZoom:19}}),
}};
let curTile='osm'; TILES.osm.addTo(map);
function setTile(k,b){{
  map.removeLayer(TILES[curTile]); TILES[k].addTo(map); curTile=k;
  document.querySelectorAll('[id^=tile-]').forEach(x=>x.classList.remove('active'));
  document.getElementById('tile-'+k).classList.add('active');
}}

function catColor(cat, time){{
  if(time===15){{
    if(cat==='both_15') return COLORS.both_15;
    if(cat==='young_15') return COLORS.young_15;
    if(cat==='both_30'||cat==='young_30') return COLORS.neutral;
    return COLORS.neither;
  }}else{{
    if(cat==='both_15') return COLORS.both_15;
    if(cat==='young_15') return COLORS.young_30;
    if(cat==='both_30') return COLORS.both_30;
    if(cat==='young_30') return COLORS.young_30;
    return COLORS.neither;
  }}
}}

let dongLayer, curTime=15;
function buildDong(time){{
  if(dongLayer) map.removeLayer(dongLayer);
  dongLayer = L.geoJSON(DONG_DATA,{{
    style:f=>{{
      const c=catColor(f.properties.category,time);
      return {{fillColor:c,fillOpacity:.68,color:'#fff',weight:.4,opacity:.5}};
    }},
    onEachFeature:(f,layer)=>{{
      layer.on('click',()=>{{
        const p=f.properties;
        document.getElementById('ib-name').textContent=p.name;
        const dm=p.dist_m;
        document.getElementById('ib-dist').textContent=
          '쉼터까지: '+(dm>=99000?'측정불가':dm+'m');
        const ty=(dm/1.28/60).toFixed(1);
        const ts=(dm/0.88/60).toFixed(1);
        document.getElementById('ib-cat').innerHTML=
          '일반인: <strong>'+ty+'분</strong> / 노인: <strong>'+ts+'분</strong>';
        document.getElementById('info-box').style.display='block';
      }});
    }}
  }}).addTo(map);
}}
buildDong(15);

function setTime(t){{
  curTime=t; buildDong(t);
  document.getElementById('btn15').classList.toggle('active',t===15);
  document.getElementById('btn30').classList.toggle('active',t===30);
  updateLegend(t);
}}

// 쉼터 마커
const shelterGroup = L.layerGroup();
SHELTERS.forEach(s=>{{
  L.circleMarker([s.lat, s.lon],{{
    radius:5, fillColor:'#0288D1', color:'#B3E5FC',
    weight:1.5, fillOpacity:.9
  }}).bindTooltip(`<b>${{s.name}}</b><br>${{s.type2}}<br>수용: ${{s.cap||'?'}}명`,
    {{direction:'top'}}).addTo(shelterGroup);
}});
shelterGroup.addTo(map);

let shelterOn=true;
function toggleShelter(btn){{
  shelterOn=!shelterOn;
  shelterOn?shelterGroup.addTo(map):map.removeLayer(shelterGroup);
  btn.textContent=shelterOn?'표시 ON':'표시 OFF';
  btn.classList.toggle('active',shelterOn);
}}

function updateLegend(t){{
  const el=document.getElementById('legend-items');
  const items=t===15?[
    {{color:COLORS.both_15, label:'둘 다 15분 이내'}},
    {{color:COLORS.young_15,label:'일반인만 15분 이내 (노인 불가)'}},
    {{color:COLORS.neutral, label:'둘 다 15분 초과 (30분 가능)'}},
    {{color:COLORS.neither, label:'둘 다 30분 초과'}},
  ]:[
    {{color:COLORS.both_15, label:'둘 다 15분 이내'}},
    {{color:COLORS.both_30, label:'둘 다 30분 이내'}},
    {{color:COLORS.young_30,label:'일반인만 30분 이내 (노인 불가)'}},
    {{color:COLORS.neither, label:'둘 다 30분 초과'}},
  ];
  el.innerHTML=items.map(i=>
    `<div class="legend-item"><div class="legend-dot" style="background:${{i.color}}"></div>${{i.label}}</div>`
  ).join('');
}}
updateLegend(15);

const sb=document.getElementById('stat-box');
sb.innerHTML=`
  <strong>서울 한파쉼터</strong> ${{STATS.shelter_count.toLocaleString()}}개<br>
  행정동 ${{STATS.total}}개 분석<br><br>
  <span style="color:#00BCD4">■</span> 노인 15분 OK: <strong>${{STATS.both_15}}</strong>개 동<br>
  <span style="color:#FFF176">■</span> 일반인만 15분: <strong>${{STATS.young_15}}</strong>개 동<br>
  <span style="color:#4FC3F7">■</span> 노인 30분 OK: <strong>${{STATS.both_30}}</strong>개 동<br>
  <span style="color:#FF7043">■</span> 일반인만 30분: <strong>${{STATS.young_30}}</strong>개 동<br>
  <span style="color:#EF5350">■</span> 둘 다 불가: <strong>${{STATS.neither}}</strong>개 동<br><br>
  <span style="color:#ff8a80">노인 접근 어려운 동: <strong>${{STATS.senior_gap_pct}}%</strong></span>
`;
</script>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, "07_b2_cold_shelter_260420.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {os.path.getsize(out_path)//1024} KB")
