"""
08_b3_snow_icing_260420.py
겨울 결빙 취약지점 분석 — 제설함 + 도로열선
- 제설함 10,437개 → 100m/200m 커버리지 → 미커버 지역 = 결빙 취약
- 도로열선 653개 구간 → 구별 총 연장(m) → 구 중심에 버블 표시
- 서울 행정동 배경 코로플레스 (구별 제설함 개수)

출력: 08_b3_snow_icing_260420.html
"""

import json, os, math
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, shape
from shapely.ops import unary_union
import pyproj
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

BASE    = "/Users/mtsaurus/Projects/seoul-2026-bigdata"
SNOW    = f"{BASE}/노인친화아이디어/data/20_서울시 제설함 위치정보.json"
HEAT_L  = f"{BASE}/노인친화아이디어/data/22_자치구별 도로열선 설치현황_2026.csv"
DONG_SHP= f"{BASE}/senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
OUT_DIR = f"{BASE}/senior_access/new-workspace/260420/outputs"
CACHE   = f"{BASE}/senior_access/new-workspace/260420/cache/b3_snow_coverage.json"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CACHE), exist_ok=True)

# ── 1. 제설함 좌표 변환 ────────────────────────────────────────────────────────
# g2_xmin/g2_ymin: TM 좌표계 mm 단위 → ÷1000 → m → EPSG:5179 → WGS84
log.info("제설함 데이터 로드 및 좌표 변환")
with open(SNOW, encoding="utf-8") as f:
    raw = json.load(f)["DATA"]

transformer = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)

boxes = []
for s in raw:
    try:
        x_m = s["g2_xmin"] / 1000.0   # mm → m
        y_m = s["g2_ymin"] / 1000.0
        lon, lat = transformer.transform(x_m, y_m)
        # 서울 범위 필터 (위도 37.4~37.7, 경도 126.7~127.2)
        if 37.3 <= lat <= 37.8 and 126.6 <= lon <= 127.3:
            boxes.append({"lon": lon, "lat": lat,
                          "num": s.get("sbox_num",""),
                          "addr": s.get("detl_cn",""),
                          "gu": s.get("mgc_nm","")})
    except:
        pass

log.info(f"  유효 제설함: {len(boxes):,}개")

# 좌표 검증
sample = boxes[0]
log.info(f"  샘플: {sample['num']} → ({sample['lat']:.5f}, {sample['lon']:.5f}) [{sample['gu']}]")

# ── 2. 제설함 버퍼 커버리지 (100m / 200m) ─────────────────────────────────────
if os.path.exists(CACHE):
    log.info("캐시 로드")
    with open(CACHE) as f:
        cache = json.load(f)
    covered_100_geojson = cache["c100"]
    covered_200_geojson = cache["c200"]
    uncov_100_geojson   = cache["u100"]
    uncov_200_geojson   = cache["u200"]
else:
    log.info("버퍼 커버리지 계산 중... (수십 초 소요)")
    # 서울 전체 행정동 경계 union → Seoul boundary
    gdf_dong = gpd.read_file(DONG_SHP)
    gdf_dong.columns = [c.lower() for c in gdf_dong.columns]
    code_col = next((c for c in gdf_dong.columns if "cd" in c), None)
    gdf_seoul = gdf_dong[gdf_dong[code_col].astype(str).str.startswith("11")].to_crs("EPSG:5186")
    seoul_boundary = unary_union(gdf_seoul.geometry)
    log.info("  서울 경계 생성 완료")

    # 제설함 포인트 → GeoDataFrame (EPSG:4326 → EPSG:5179)
    gdf_boxes = gpd.GeoDataFrame(
        boxes,
        geometry=[Point(b["lon"], b["lat"]) for b in boxes],
        crs="EPSG:4326"
    ).to_crs("EPSG:5186")
    log.info("  포인트 CRS 변환 완료")

    # 100m 버퍼 union
    log.info("  100m 버퍼 계산 중...")
    buf_100 = gdf_boxes.geometry.buffer(100)
    covered_100 = unary_union(buf_100).intersection(seoul_boundary)
    uncov_100   = seoul_boundary.difference(covered_100)

    # 200m 버퍼 union
    log.info("  200m 버퍼 계산 중...")
    buf_200 = gdf_boxes.geometry.buffer(200)
    covered_200 = unary_union(buf_200).intersection(seoul_boundary)
    uncov_200   = seoul_boundary.difference(covered_200)

    # WGS84로 변환 후 GeoJSON
    def to_wgs84_geojson(geom, src_crs="EPSG:5186"):
        gs = gpd.GeoSeries([geom], crs=src_crs).to_crs("EPSG:4326")
        gs_simple = gs.simplify(0.0003)
        return json.dumps(gs_simple.iloc[0].__geo_interface__, ensure_ascii=False)

    log.info("  GeoJSON 직렬화 중...")
    covered_100_geojson = to_wgs84_geojson(covered_100)
    covered_200_geojson = to_wgs84_geojson(covered_200)
    uncov_100_geojson   = to_wgs84_geojson(uncov_100)
    uncov_200_geojson   = to_wgs84_geojson(uncov_200)

    with open(CACHE, "w") as f:
        json.dump({
            "c100": covered_100_geojson,
            "c200": covered_200_geojson,
            "u100": uncov_100_geojson,
            "u200": uncov_200_geojson,
        }, f)
    log.info("  캐시 저장 완료")

    # 커버리지 통계
    area_seoul = seoul_boundary.area / 1e6   # km²
    area_c100  = covered_100.area / 1e6
    area_c200  = covered_200.area / 1e6
    log.info(f"  서울 면적: {area_seoul:.1f} km²")
    log.info(f"  100m 커버: {area_c100:.1f} km² ({area_c100/area_seoul*100:.1f}%)")
    log.info(f"  200m 커버: {area_c200:.1f} km² ({area_c200/area_seoul*100:.1f}%)")

# ── 3. 구별 제설함 수 + 열선 연장 ──────────────────────────────────────────────
log.info("구별 통계 계산")
gu_snow = {}
for b in boxes:
    gu = b["gu"]
    gu_snow[gu] = gu_snow.get(gu, 0) + 1

# 열선 데이터
df_heat = pd.read_csv(HEAT_L, encoding="utf-8-sig")
df_heat.columns = [c.strip() for c in df_heat.columns]
# '연장(m)' 컬럼 숫자 변환
len_col = next((c for c in df_heat.columns if "연장" in c), None)
mgr_col = next((c for c in df_heat.columns if "관리" in c), None)
if len_col and mgr_col:
    df_heat[len_col] = pd.to_numeric(df_heat[len_col], errors="coerce").fillna(0)
    gu_heat = df_heat.groupby(mgr_col)[len_col].sum().to_dict()
else:
    gu_heat = {}

log.info(f"  구별 제설함: {len(gu_snow)}개 구")
log.info(f"  구별 열선: {len(gu_heat)}개 구")

# 서울 25개 구 목록
SEOUL_GU = [
    "종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구",
    "은평구","서대문구","마포구","양천구","강서구","구로구","금천구","영등포구","동작구","관악구",
    "서초구","강남구","송파구","강동구"
]

# 구 중심 좌표 (대략, WGS84)
GU_CENTERS = {
    "종로구":(37.5894,126.9754),"중구":(37.5637,126.9978),"용산구":(37.5322,126.9907),
    "성동구":(37.5636,127.0369),"광진구":(37.5386,127.0834),"동대문구":(37.5744,127.0397),
    "중랑구":(37.6065,127.0928),"성북구":(37.5894,127.0167),"강북구":(37.6396,127.0256),
    "도봉구":(37.6688,127.0468),"노원구":(37.6542,127.0567),"은평구":(37.6017,126.9275),
    "서대문구":(37.5791,126.9367),"마포구":(37.5638,126.9014),"양천구":(37.5168,126.8660),
    "강서구":(37.5509,126.8495),"구로구":(37.4954,126.8874),"금천구":(37.4600,126.9001),
    "영등포구":(37.5263,126.8963),"동작구":(37.5122,126.9395),"관악구":(37.4784,126.9515),
    "서초구":(37.4836,127.0324),"강남구":(37.5172,127.0473),"송파구":(37.5145,127.1059),
    "강동구":(37.5301,127.1237),
}

# 구별 통합 데이터
gu_data = []
for gu in SEOUL_GU:
    snow_cnt = gu_snow.get(gu, 0)
    heat_len = gu_heat.get(gu, 0)
    lat, lon = GU_CENTERS.get(gu, (0, 0))
    gu_data.append({
        "gu": gu, "snow_cnt": snow_cnt, "heat_len": int(heat_len),
        "lat": lat, "lon": lon
    })

# 제설함 포인트 (표시용, 전체는 너무 많으니 구 중심 근처 샘플만 사용)
# 전체 점은 너무 많아서 HTML 무거워지므로 생략, 구별 버블로 대체
# 대신 제설함을 아주 작은 점으로 전체 표시 (10k개는 괜찮음)
boxes_json    = json.dumps(boxes, ensure_ascii=False)
gu_data_json  = json.dumps(gu_data, ensure_ascii=False)

# 최대값 (버블 크기 정규화용)
max_snow = max(d["snow_cnt"] for d in gu_data) if gu_data else 1
max_heat = max(d["heat_len"] for d in gu_data) if gu_data else 1
total_snow = sum(d["snow_cnt"] for d in gu_data)
total_heat = sum(d["heat_len"] for d in gu_data)

# ── 4. 행정동 배경 ──────────────────────────────────────────────────────────────
log.info("행정동 GeoJSON 생성")
gdf_d = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf_d.columns = [c.lower() for c in gdf_d.columns]
code_col2 = next((c for c in gdf_d.columns if "cd" in c), None)
if code_col2:
    gdf_d = gdf_d[gdf_d[code_col2].astype(str).str.startswith("11")].copy()
gdf_d["geometry"] = gdf_d.geometry.simplify(0.002)
name_col = next((c for c in gdf_d.columns if "nm" in c), gdf_d.columns[1])
# 구 코드 추출 (adm_cd 앞 5자리 → 구)
dong_features = []
for _, row in gdf_d.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty: continue
    dong_features.append({
        "type":"Feature",
        "geometry": geom.__geo_interface__,
        "properties": {"name": str(row.get(name_col, ""))}
    })
dong_geojson = json.dumps({"type":"FeatureCollection","features":dong_features},
                           ensure_ascii=False)

# ── 5. HTML 생성 ───────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>겨울 결빙 취약지점 분석 — 서울 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#0d1b2a;color:#eee;height:100vh;display:flex;flex-direction:column}}
#header{{background:#0a1628;padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;border-bottom:2px solid #0d47a1}}
#header h1{{font-size:1.05rem;font-weight:700;color:#fff}}
.sub{{font-size:.72rem;color:#90caf9;margin-left:4px}}
.ctrl-group{{display:flex;gap:6px;align-items:center}}
.ctrl-group label{{font-size:.73rem;color:#aaa}}
.btn{{padding:5px 12px;border:1px solid #333;background:#0d1b2a;color:#ccc;border-radius:4px;cursor:pointer;font-size:.77rem;transition:.15s}}
.btn.active{{background:#0d47a1;border-color:#1565C0;color:#fff}}
.btn:hover:not(.active){{background:#1a2a3a}}
#map{{flex:1}}
#panel{{position:absolute;top:70px;right:12px;z-index:1000;background:rgba(10,22,40,.95);
        border:1px solid #0d47a1;border-radius:8px;padding:14px;width:235px;
        box-shadow:0 4px 24px rgba(0,0,0,.7)}}
#panel h3{{font-size:.82rem;margin-bottom:10px;color:#64B5F6;border-bottom:1px solid #0d47a1;padding-bottom:6px}}
.legend-item{{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:.74rem}}
.legend-dot{{width:14px;height:14px;border-radius:3px;flex-shrink:0}}
.stat-box{{margin-top:10px;padding-top:8px;border-top:1px solid #0d47a1;font-size:.72rem;color:#bbb;line-height:1.8}}
.stat-box strong{{color:#fff}}
#info-box{{position:absolute;bottom:30px;left:12px;z-index:1000;background:rgba(10,22,40,.93);
           border:1px solid #0d47a1;border-radius:6px;padding:10px 14px;min-width:180px;
           font-size:.76rem;display:none}}
#info-box .ib-name{{font-weight:700;font-size:.85rem;color:#fff;margin-bottom:4px}}
#info-box .ib-row{{color:#ccc;margin-bottom:2px}}
</style>
</head>
<body>
<div id="header">
  <h1>🧂 겨울 결빙 취약지점 — 제설함 커버리지 &amp; 도로열선
    <span class="sub">결빙구역 = 노인 보행 고위험 지대</span>
  </h1>
  <div class="ctrl-group">
    <label>커버 반경</label>
    <button class="btn active" id="btn100" onclick="setRadius(100)">100m</button>
    <button class="btn" id="btn200" onclick="setRadius(200)">200m</button>
  </div>
  <div class="ctrl-group">
    <label>레이어</label>
    <button class="btn active" id="btn-uncov" onclick="toggleLayer('uncov',this)">결빙취약 ON</button>
    <button class="btn active" id="btn-boxes" onclick="toggleLayer('boxes',this)">제설함 ON</button>
    <button class="btn active" id="btn-heat" onclick="toggleLayer('heat',this)">열선 ON</button>
  </div>
  <div class="ctrl-group">
    <label>지도</label>
    <button class="btn active" id="tile-osm" onclick="setTile('osm',this)">일반</button>
    <button class="btn" id="tile-esri" onclick="setTile('esri',this)">위성</button>
    <button class="btn" id="tile-dark" onclick="setTile('dark',this)">Dark</button>
  </div>
</div>
<div id="map"></div>

<div id="panel">
  <h3>🗺️ 범례 &amp; 통계</h3>
  <div class="legend-item"><div class="legend-dot" style="background:#B71C1C;opacity:.7"></div>결빙 취약지역 (미커버)</div>
  <div class="legend-item"><div class="legend-dot" style="background:#1565C0;opacity:.5"></div>제설함 커버 구역</div>
  <div class="legend-item"><div class="legend-dot" style="background:#00E5FF;border-radius:50%"></div>제설함 위치</div>
  <div class="legend-item"><div class="legend-dot" style="background:#FF6F00;border-radius:50%"></div>열선 설치 구간 (구별)</div>
  <div class="stat-box">
    <strong>서울 제설함</strong> {total_snow:,}개<br>
    <strong>열선 총 연장</strong> {total_heat:,}m<br>
    <span style="color:#aaa;font-size:.7rem">구별 버블: 열선 연장(m) 비례</span>
  </div>
</div>

<div id="info-box">
  <div class="ib-name" id="ib-name">-</div>
  <div class="ib-row" id="ib-snow">-</div>
  <div class="ib-row" id="ib-heat">-</div>
</div>

<script>
const BOXES     = {boxes_json};
const GU_DATA   = {gu_data_json};
const DONG_DATA = {dong_geojson};
const COV_100   = {covered_100_geojson};
const COV_200   = {covered_200_geojson};
const UNCOV_100 = {uncov_100_geojson};
const UNCOV_200 = {uncov_200_geojson};
const MAX_HEAT  = {max_heat};
const MAX_SNOW  = {max_snow};

// ─── 지도 ─────────────────────────────────────────────────────────────────────
const map = L.map('map', {{center:[37.5665,126.9780], zoom:11}});
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

// ─── 행정동 배경 (회색 테두리) ──────────────────────────────────────────────────
L.geoJSON(DONG_DATA, {{
  style:{{fillColor:'transparent',color:'#37474F',weight:.5,opacity:.5}}
}}).addTo(map);

// ─── 커버리지 레이어 ────────────────────────────────────────────────────────────
let curRadius = 100;
let covLayer, uncovLayer;

function buildCoverage(r){{
  if(covLayer) map.removeLayer(covLayer);
  if(uncovLayer) map.removeLayer(uncovLayer);
  const covGeo  = r===100 ? COV_100  : COV_200;
  const uncovGeo= r===100 ? UNCOV_100: UNCOV_200;

  covLayer = L.geoJSON(covGeo, {{
    style:{{fillColor:'#1565C0',fillOpacity:.25,color:'#1E88E5',weight:.5,opacity:.4}}
  }});
  uncovLayer = L.geoJSON(uncovGeo, {{
    style:{{fillColor:'#B71C1C',fillOpacity:.55,color:'#E53935',weight:.5,opacity:.5}}
  }});
  if(layerOn.uncov) uncovLayer.addTo(map);
  if(layerOn.uncov) covLayer.addTo(map);  // covered behind uncovered
}}

// ─── 제설함 포인트 ────────────────────────────────────────────────────────────
const boxesGroup = L.layerGroup();
BOXES.forEach(b=>{{
  L.circleMarker([b.lat, b.lon],{{
    radius:2.5, fillColor:'#00E5FF', color:'transparent',
    fillOpacity:.7
  }}).bindTooltip(`${{b.num}}<br>${{b.addr}}<br>${{b.gu}}`,
    {{direction:'top',className:'tip'}}).addTo(boxesGroup);
}});

// ─── 열선 구별 버블 ─────────────────────────────────────────────────────────
const heatGroup = L.layerGroup();
GU_DATA.forEach(d=>{{
  if(!d.lat || !d.heat_len) return;
  const r = Math.max(8, Math.sqrt(d.heat_len/MAX_HEAT)*40);
  L.circleMarker([d.lat, d.lon],{{
    radius:r, fillColor:'#FF6F00', color:'#FFB74D',
    weight:1.5, fillOpacity:.7
  }}).bindTooltip(
    `<b>${{d.gu}}</b><br>열선: ${{d.heat_len.toLocaleString()}}m<br>제설함: ${{d.snow_cnt}}개`,
    {{direction:'top',sticky:true}}
  ).on('click',()=>{{
    document.getElementById('ib-name').textContent=d.gu;
    document.getElementById('ib-snow').textContent='제설함: '+d.snow_cnt+'개';
    document.getElementById('ib-heat').textContent='열선: '+d.heat_len.toLocaleString()+'m';
    document.getElementById('info-box').style.display='block';
  }}).addTo(heatGroup);
}});

// ─── 레이어 상태 관리 ──────────────────────────────────────────────────────────
const layerOn = {{uncov:true, boxes:true, heat:true}};
boxesGroup.addTo(map);
heatGroup.addTo(map);
buildCoverage(100);

function toggleLayer(key, btn){{
  layerOn[key] = !layerOn[key];
  if(key==='uncov'){{
    layerOn[key] ? buildCoverage(curRadius) :
                   (covLayer&&map.removeLayer(covLayer), uncovLayer&&map.removeLayer(uncovLayer));
  }} else if(key==='boxes'){{
    layerOn[key] ? boxesGroup.addTo(map) : map.removeLayer(boxesGroup);
  }} else if(key==='heat'){{
    layerOn[key] ? heatGroup.addTo(map) : map.removeLayer(heatGroup);
  }}
  btn.textContent = (layerOn[key]?'':'OFF ') + btn.textContent.replace('ON','').replace('OFF ','').trim() + (layerOn[key]?' ON':'');
  btn.classList.toggle('active', layerOn[key]);
}}

function setRadius(r){{
  curRadius=r;
  buildCoverage(r);
  document.getElementById('btn100').classList.toggle('active',r===100);
  document.getElementById('btn200').classList.toggle('active',r===200);
}}
</script>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, "08_b3_snow_icing_260420.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {os.path.getsize(out_path)//1024} KB")
