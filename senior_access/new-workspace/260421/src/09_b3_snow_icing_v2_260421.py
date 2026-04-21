"""
09_b3_snow_icing_v2_260421.py
겨울 결빙 취약지점 v3 — 260420 + 260421 개선 통합

260420 대비:
  - 결빙취약 폴리곤: OSM 보행도로망 영역으로 마스킹 (한강·산지·건물 내부 제외)
  - 열선: 구별 버블 제거, 도로 선(line) 시각화만 유지
  - 제설함 커버원: L.circle 렌더링 유지 (파일 경량화)

260421 v1 대비:
  - 결빙취약 구역을 빨간 폴리곤으로 명시적 표시 (커버원만으로는 미흡)
  - 구별 열선 버블 제거

출력: 09_b3_snow_icing_v2_260421.html
"""

import json, os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.ops import unary_union
import osmnx as ox
import pyproj
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

BASE    = "/Users/mtsaurus/Projects/seoul-2026-bigdata"
GRAPH   = f"{BASE}/senior_access/new-workspace/cache/seoul_walk_full.graphml"
SNOW    = f"{BASE}/노인친화아이디어/data/20_서울시 제설함 위치정보.json"
HEAT_L  = f"{BASE}/노인친화아이디어/data/22_자치구별 도로열선 설치현황_2026.csv"
DONG_SHP= f"{BASE}/senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
OUT_DIR = f"{BASE}/senior_access/new-workspace/260421/outputs"
CACHE   = f"{BASE}/senior_access/new-workspace/260421/cache"

# 260421 v1 캐시 재활용
WALKABLE_CACHE  = f"{CACHE}/walkable_area.json"
HEAT_LINE_CACHE = f"{CACHE}/heat_lines.json"
ICING_CACHE     = f"{CACHE}/icing_v2.json"

os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. 제설함 로드 ─────────────────────────────────────────────────────────────
log.info("제설함 데이터 로드")
with open(SNOW, encoding="utf-8") as f:
    raw = json.load(f)["DATA"]
t = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
boxes = []
for s in raw:
    try:
        lon, lat = t.transform(s["g2_xmin"] / 1000.0, s["g2_ymin"] / 1000.0)
        if 37.3 <= lat <= 37.8 and 126.6 <= lon <= 127.3:
            boxes.append({"lon": lon, "lat": lat,
                          "num": s.get("sbox_num",""), "addr": s.get("detl_cn",""),
                          "gu": s.get("mgc_nm","")})
    except:
        pass
log.info(f"  제설함: {len(boxes):,}개")
boxes_json = json.dumps(boxes, ensure_ascii=False)

# ── 2. walkable area 로드 ─────────────────────────────────────────────────────
log.info("walkable area 로드 (v1 캐시)")
with open(WALKABLE_CACHE) as f:
    w = json.load(f)
walkable_5186 = shape(json.loads(w["walkable"]))
log.info(f"  보행 가능 도로망: {walkable_5186.area/1e6:.1f} km²")

# ── 3. 결빙취약 폴리곤 계산 (캐시) ───────────────────────────────────────────
if os.path.exists(ICING_CACHE):
    log.info("결빙취약 폴리곤 캐시 로드")
    with open(ICING_CACHE) as f:
        ic = json.load(f)
    icing_100_geojson = ic["i100"]
    icing_200_geojson = ic["i200"]
    area_stats = ic["stats"]
else:
    log.info("결빙취약 폴리곤 계산 중...")
    gdf_boxes = gpd.GeoDataFrame(
        boxes,
        geometry=[Point(b["lon"], b["lat"]) for b in boxes],
        crs="EPSG:4326"
    ).to_crs("EPSG:5186")

    log.info("  100m 버퍼 union...")
    covered_100 = unary_union(gdf_boxes.geometry.buffer(100))
    log.info("  200m 버퍼 union...")
    covered_200 = unary_union(gdf_boxes.geometry.buffer(200))

    log.info("  결빙취약 = walkable - covered...")
    icing_100 = walkable_5186.difference(covered_100)
    icing_200 = walkable_5186.difference(covered_200)

    def to_geojson(geom):
        gs = gpd.GeoSeries([geom], crs="EPSG:5186").to_crs("EPSG:4326")
        return json.dumps(
            gs.simplify(0.001).iloc[0].__geo_interface__,
            separators=(',',':')
        )

    log.info("  GeoJSON 직렬화 (simplify 0.001)...")
    icing_100_geojson = to_geojson(icing_100)
    icing_200_geojson = to_geojson(icing_200)

    walk_area = walkable_5186.area / 1e6
    area_stats = {
        "walkable_km2":  round(walk_area, 1),
        "icing_100_km2": round(icing_100.area / 1e6, 1),
        "icing_200_km2": round(icing_200.area / 1e6, 1),
        "icing_100_pct": round(icing_100.area / walkable_5186.area * 100, 1),
        "icing_200_pct": round(icing_200.area / walkable_5186.area * 100, 1),
    }
    log.info(f"  결빙취약 100m: {area_stats['icing_100_pct']}% ({area_stats['icing_100_km2']} km²)")
    log.info(f"  결빙취약 200m: {area_stats['icing_200_pct']}% ({area_stats['icing_200_km2']} km²)")

    with open(ICING_CACHE, "w") as f:
        json.dump({"i100": icing_100_geojson, "i200": icing_200_geojson,
                   "stats": area_stats}, f)
    log.info("  캐시 저장")

# ── 4. 열선 라인 로드 (v1 캐시) ───────────────────────────────────────────────
log.info("열선 라인 로드 (v1 캐시)")
with open(HEAT_LINE_CACHE) as f:
    hl = json.load(f)
heat_lines_geojson = hl["lines"]
heat_stats = hl["stats"]

# 총 열선 연장
df_h = pd.read_csv(HEAT_L, encoding="utf-8-sig")
df_h.columns = [c.strip() for c in df_h.columns]
len_col = next((c for c in df_h.columns if "연장" in c), None)
df_h[len_col] = pd.to_numeric(df_h[len_col], errors="coerce").fillna(0)
total_heat_m = int(df_h[len_col].sum())
total_snow = len(boxes)

# ── 5. 행정동 배경 ─────────────────────────────────────────────────────────────
gdf_d = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf_d.columns = [c.lower() for c in gdf_d.columns]
gdf_d = gdf_d[gdf_d["adm_cd"].astype(str).str.startswith("11")].copy()
gdf_d["geometry"] = gdf_d.geometry.simplify(0.002)
dong_features = []
for _, row in gdf_d.iterrows():
    g = row.geometry
    if g is None or g.is_empty: continue
    dong_features.append({"type":"Feature","geometry":g.__geo_interface__,
                           "properties":{"name":str(row.get("adm_nm",""))}})
dong_geojson = json.dumps({"type":"FeatureCollection","features":dong_features},
                           ensure_ascii=False)

# ── 6. HTML 생성 ───────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>겨울 결빙 취약지점 v3 — 서울 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#0d1b2a;color:#eee;height:100vh;display:flex;flex-direction:column}}
#hdr{{background:#0a1628;padding:10px 18px;display:flex;align-items:center;gap:12px;
      flex-wrap:wrap;border-bottom:2px solid #b71c1c}}
h1{{font-size:1rem;font-weight:700;color:#fff;white-space:nowrap}}
.sub{{font-size:.7rem;color:#EF9A9A;margin-left:4px}}
.ctrl{{display:flex;gap:5px;align-items:center}}
.ctrl label{{font-size:.7rem;color:#aaa;white-space:nowrap}}
.btn{{padding:4px 11px;border:1px solid #333;background:#0d1b2a;color:#ccc;
      border-radius:4px;cursor:pointer;font-size:.75rem;transition:.15s}}
.btn.active{{background:#B71C1C;border-color:#EF5350;color:#fff}}
.btn.blue.active{{background:#0d47a1;border-color:#1565C0}}
.btn.orange.active{{background:#E65100;border-color:#FF8F00}}
.btn:hover:not(.active){{background:#1a2a3a}}
#map{{flex:1}}
#panel{{position:absolute;top:62px;right:12px;z-index:1000;background:rgba(10,22,40,.96);
        border:1px solid #b71c1c;border-radius:8px;padding:12px;width:235px;
        box-shadow:0 4px 24px rgba(0,0,0,.7)}}
#panel h3{{font-size:.8rem;margin-bottom:8px;color:#EF9A9A;border-bottom:1px solid #b71c1c;padding-bottom:5px}}
.leg{{display:flex;align-items:center;gap:7px;margin-bottom:5px;font-size:.72rem;line-height:1.3}}
.dot{{width:13px;height:13px;border-radius:2px;flex-shrink:0}}
.ldot{{width:22px;height:4px;border-radius:2px;flex-shrink:0}}
.stat{{margin-top:9px;padding-top:7px;border-top:1px solid #b71c1c;
       font-size:.7rem;color:#bbb;line-height:2}}
.stat strong{{color:#fff}}
#ibox{{position:absolute;bottom:28px;left:12px;z-index:1000;background:rgba(10,22,40,.93);
       border:1px solid #b71c1c;border-radius:6px;padding:9px 13px;min-width:200px;
       font-size:.76rem;display:none}}
#ibox .nm{{font-weight:700;font-size:.85rem;color:#fff;margin-bottom:3px}}
#ibox .r{{color:#ccc;margin-bottom:2px}}
</style>
</head>
<body>
<div id="hdr">
  <h1>🧂 겨울 결빙 취약지점
    <span class="sub">비보행 지역(한강·산지) 제외 | 도로열선 설치 구간 표시</span>
  </h1>
  <div class="ctrl">
    <label>제설함 반경</label>
    <button class="btn active" id="btn100" onclick="setR(100)">100m</button>
    <button class="btn" id="btn200" onclick="setR(200)">200m</button>
  </div>
  <div class="ctrl">
    <label>레이어</label>
    <button class="btn active" id="b-icing" onclick="tog('icing',this)">결빙취약 ON</button>
    <button class="btn blue active" id="b-cov" onclick="tog('cov',this)">커버원 ON</button>
    <button class="btn blue active" id="b-boxes" onclick="tog('boxes',this)">제설함 ON</button>
    <button class="btn orange active" id="b-heat" onclick="tog('heat',this)">열선 ON</button>
  </div>
  <div class="ctrl">
    <label>지도</label>
    <button class="btn active" id="tile-osm" onclick="setTile('osm',this)">일반</button>
    <button class="btn" id="tile-esri" onclick="setTile('esri',this)">위성</button>
    <button class="btn" id="tile-dark" onclick="setTile('dark',this)">Dark</button>
  </div>
</div>
<div id="map"></div>

<div id="panel">
  <h3>🗺️ 범례</h3>
  <div class="leg"><div class="dot" style="background:#C62828;opacity:.7"></div>결빙 취약 도로 구역</div>
  <div class="leg"><div class="dot" style="background:#1565C0;opacity:.35;border:1px solid #42A5F5"></div>제설함 커버리지 원</div>
  <div class="leg"><div class="dot" style="background:#00E5FF;border-radius:50%"></div>제설함 위치</div>
  <div class="leg"><div class="ldot" style="background:#FF8F00"></div>도로열선 설치 구간</div>
  <div class="stat">
    제설함 <strong>{total_snow:,}</strong>개<br>
    열선 구간 <strong>{heat_stats['matched_records']}</strong>/{heat_stats['total_records']} 매칭
    ({heat_stats['matched_edges']:,}엣지)<br>
    보행 도로 <strong>{area_stats['walkable_km2']}</strong> km²<br>
    결빙취약 &nbsp;<span id="pct" style="color:#EF9A9A;font-weight:700">—</span>
  </div>
</div>

<div id="ibox">
  <div class="nm" id="ib-road">—</div>
  <div class="r"  id="ib-gu">—</div>
  <div class="r"  id="ib-len">—</div>
</div>

<script>
const BOXES      = {boxes_json};
const DONG_DATA  = {dong_geojson};
const ICING_100  = {icing_100_geojson};
const ICING_200  = {icing_200_geojson};
const HEAT_LINES = {heat_lines_geojson};
const STATS      = {json.dumps(area_stats)};

// ─── 지도 ──────────────────────────────────────────────────────────────────────
const map = L.map('map', {{center:[37.5500,126.9780], zoom:11}});
const TILES = {{
  osm:  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          {{attribution:'© OpenStreetMap',maxZoom:19}}),
  esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
          {{attribution:'© Esri',maxZoom:19}}),
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
          {{attribution:'© CartoDB',maxZoom:19}}),
}};
let curTile='osm'; TILES.osm.addTo(map);
function setTile(k,b){{
  map.removeLayer(TILES[curTile]); TILES[k].addTo(map); curTile=k;
  document.querySelectorAll('[id^=tile-]').forEach(x=>x.classList.remove('active'));
  document.getElementById('tile-'+k).classList.add('active');
}}

// 행정동 배경
L.geoJSON(DONG_DATA,{{style:{{fillColor:'transparent',color:'#37474F',weight:.4,opacity:.5}}}}).addTo(map);

// ─── 결빙취약 폴리곤 ──────────────────────────────────────────────────────────
let icingLayer;
let curR = 100;
const on = {{icing:true, cov:true, boxes:true, heat:true}};

function buildIcing(r){{
  if(icingLayer) map.removeLayer(icingLayer);
  icingLayer = L.geoJSON(r===100?ICING_100:ICING_200, {{
    style:{{fillColor:'#C62828',fillOpacity:.62,color:'#EF5350',weight:.4,opacity:.5}}
  }});
  if(on.icing) icingLayer.addTo(map);
  const pct = r===100 ? STATS.icing_100_pct : STATS.icing_200_pct;
  const km  = r===100 ? STATS.icing_100_km2 : STATS.icing_200_km2;
  document.getElementById('pct').textContent = pct+'% ('+km+' km²)';
}}

// ─── 제설함 커버리지 원 ──────────────────────────────────────────────────────
let covGroup = L.layerGroup();
function buildCircles(r){{
  covGroup.clearLayers();
  BOXES.forEach(b=>L.circle([b.lat,b.lon],{{
    radius:r, fillColor:'#1565C0', fillOpacity:.12,
    color:'#1E88E5', weight:.25, opacity:.35
  }}).addTo(covGroup));
}}
buildCircles(100);

// ─── 제설함 포인트 ────────────────────────────────────────────────────────────
const boxesLayer = L.layerGroup();
BOXES.forEach(b=>{{
  L.circleMarker([b.lat,b.lon],{{
    radius:2, fillColor:'#00E5FF', color:'transparent', fillOpacity:.7
  }}).bindTooltip(`${{b.num}}<br>${{b.addr}}<br>${{b.gu}}`,{{direction:'top'}}).addTo(boxesLayer);
}});

// ─── 열선 라인 ────────────────────────────────────────────────────────────────
const heatLayer = L.geoJSON(HEAT_LINES, {{
  style:{{color:'#FF8F00', weight:3.5, opacity:.92}},
  onEachFeature:(f,l)=>{{
    l.bindTooltip(
      `<b>${{f.properties.road}}</b><br>${{f.properties.gu}}<br>연장 약 ${{f.properties.len_m}}m`,
      {{sticky:true, direction:'top'}}
    );
    l.on('click',()=>{{
      document.getElementById('ib-road').textContent=f.properties.road;
      document.getElementById('ib-gu').textContent=f.properties.gu;
      document.getElementById('ib-len').textContent='설치 연장: '+f.properties.len_m+'m';
      document.getElementById('ibox').style.display='block';
    }});
  }}
}});

// ─── 레이어 순서: icing → cov → boxes → heat (위로 갈수록 나중 렌더) ──────────
buildIcing(100);
if(on.cov)   covGroup.addTo(map);
if(on.boxes) boxesLayer.addTo(map);
if(on.heat)  heatLayer.addTo(map);

// ─── 토글 ──────────────────────────────────────────────────────────────────────
const LAYERS = {{
  icing: ()=>on.icing?icingLayer.addTo(map):map.removeLayer(icingLayer),
  cov:   ()=>on.cov  ?covGroup.addTo(map) :map.removeLayer(covGroup),
  boxes: ()=>on.boxes?boxesLayer.addTo(map):map.removeLayer(boxesLayer),
  heat:  ()=>on.heat ?heatLayer.addTo(map) :map.removeLayer(heatLayer),
}};
const LABELS = {{icing:'결빙취약',cov:'커버원',boxes:'제설함',heat:'열선'}};

function tog(key, btn){{
  on[key]=!on[key];
  LAYERS[key]();
  btn.classList.toggle('active',on[key]);
  btn.textContent=LABELS[key]+' '+(on[key]?'ON':'OFF');
}}

function setR(r){{
  curR=r;
  buildIcing(r);
  buildCircles(r);
  document.getElementById('btn100').classList.toggle('active',r===100);
  document.getElementById('btn200').classList.toggle('active',r===200);
}}

// map 클릭으로 info 닫기
map.on('click',()=>document.getElementById('ibox').style.display='none');
</script>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, "09_b3_snow_icing_v2_260421.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {os.path.getsize(out_path)//1024} KB")
