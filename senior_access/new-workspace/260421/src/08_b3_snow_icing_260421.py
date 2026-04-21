"""
08_b3_snow_icing_260421.py
겨울 결빙 취약지점 분석 v2 — 260420 대비 개선
  개선 1: 열선 → 도로 구간 선(line) 시각화 (CSV 도로명 × OSM 엣지 매칭)
  개선 2: 결빙취약 구역 → 보행 가능한 도로망 영역만 표시 (한강·산지 제외)
           OSM 보행 그래프 엣지 18m 버퍼 union → 실제 걸을 수 있는 곳만 마스킹

출력: 08_b3_snow_icing_260421.html
"""

import json, os, re
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import Point
from shapely.ops import unary_union
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

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

WALKABLE_CACHE  = f"{CACHE}/walkable_area.json"
COVERAGE_CACHE  = f"{CACHE}/snow_coverage.json"
HEAT_LINE_CACHE = f"{CACHE}/heat_lines.json"

# ── 1. 제설함 좌표 변환 (EPSG:5186 mm → WGS84) ────────────────────────────────
log.info("제설함 데이터 로드")
with open(SNOW, encoding="utf-8") as f:
    raw = json.load(f)["DATA"]

t5186_wgs = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
t5186_5186 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:5186", always_xy=True)

boxes = []
for s in raw:
    try:
        x_m = s["g2_xmin"] / 1000.0
        y_m = s["g2_ymin"] / 1000.0
        lon, lat = t5186_wgs.transform(x_m, y_m)
        if 37.3 <= lat <= 37.8 and 126.6 <= lon <= 127.3:
            boxes.append({"lon": lon, "lat": lat,
                          "num": s.get("sbox_num", ""),
                          "addr": s.get("detl_cn", ""),
                          "gu": s.get("mgc_nm", "")})
    except:
        pass
log.info(f"  제설함: {len(boxes):,}개")

# ── 2. 그래프 로드 ─────────────────────────────────────────────────────────────
log.info("OSM 보행 그래프 로드 중...")
G = ox.load_graphml(GRAPH)
G = ox.convert.to_undirected(G)
log.info(f"  노드 {G.number_of_nodes():,} / 엣지 {G.number_of_edges():,}")

# ── 3. walkable area 계산 (캐시) ───────────────────────────────────────────────
if os.path.exists(WALKABLE_CACHE):
    log.info("walkable area 캐시 로드")
    with open(WALKABLE_CACHE) as f:
        walkable_geojson_5186 = json.load(f)["walkable"]
    from shapely.geometry import shape
    walkable_5186 = shape(json.loads(walkable_geojson_5186))
else:
    log.info("walkable area 계산 중 (OSM 엣지 18m 버퍼 union, ~90초)...")
    gdf_e_all = ox.graph_to_gdfs(G, nodes=False, edges=True).to_crs("EPSG:5186")
    bufs = gdf_e_all.geometry.buffer(18, resolution=4)
    walkable_5186 = unary_union(bufs)
    log.info("  계산 완료 → 캐시 저장")
    walk_gs = gpd.GeoSeries([walkable_5186], crs="EPSG:5186")
    walk_geojson = json.dumps(walk_gs.iloc[0].__geo_interface__)
    with open(WALKABLE_CACHE, "w") as f:
        json.dump({"walkable": walk_geojson}, f)

# ── 4. 제설함 커버리지 계산 (캐시) ────────────────────────────────────────────
# 커버리지 통계만 계산 (폴리곤 대신 Leaflet circle로 렌더링)
if os.path.exists(COVERAGE_CACHE):
    log.info("커버리지 통계 캐시 로드")
    with open(COVERAGE_CACHE) as f:
        area_stats = json.load(f)["stats"]
else:
    log.info("커버리지 통계 계산 중...")
    gdf_boxes = gpd.GeoDataFrame(
        boxes,
        geometry=[Point(b["lon"], b["lat"]) for b in boxes],
        crs="EPSG:4326"
    ).to_crs("EPSG:5186")

    log.info("  100m/200m 버퍼 union...")
    covered_100 = unary_union(gdf_boxes.geometry.buffer(100))
    covered_200 = unary_union(gdf_boxes.geometry.buffer(200))

    icing_100 = walkable_5186.difference(covered_100)
    icing_200 = walkable_5186.difference(covered_200)

    walk_area = walkable_5186.area / 1e6
    area_stats = {
        "walkable_km2": round(walk_area, 1),
        "icing_100_km2": round(icing_100.area / 1e6, 1),
        "icing_200_km2": round(icing_200.area / 1e6, 1),
        "icing_100_pct": round(icing_100.area / walkable_5186.area * 100, 1),
        "icing_200_pct": round(icing_200.area / walkable_5186.area * 100, 1),
    }
    log.info(f"  보행 가능 도로: {area_stats['walkable_km2']} km²")
    log.info(f"  결빙취약 100m: {area_stats['icing_100_pct']}%")
    log.info(f"  결빙취약 200m: {area_stats['icing_200_pct']}%")

    with open(COVERAGE_CACHE, "w") as f:
        json.dump({"stats": area_stats}, f)
    log.info("  통계 캐시 저장")

# ── 5. 열선 도로명 매칭 (캐시) ────────────────────────────────────────────────
if os.path.exists(HEAT_LINE_CACHE):
    log.info("열선 라인 캐시 로드")
    with open(HEAT_LINE_CACHE) as f:
        heat_lines_geojson = json.load(f)["lines"]
    heat_stats = json.load(open(HEAT_LINE_CACHE))["stats"]
else:
    log.info("열선 도로명 → OSM 엣지 매칭 중...")

    # 열선 CSV 파싱
    df_heat = pd.read_csv(HEAT_L, encoding="utf-8-sig")
    df_heat.columns = [c.strip() for c in df_heat.columns]
    seg_col = next((c for c in df_heat.columns if "구간" in c), None)
    mgr_col = next((c for c in df_heat.columns if "관리" in c), None)
    len_col = next((c for c in df_heat.columns if "연장" in c), None)

    def parse_road_name(text):
        m = re.match(r'^(.+?)[\(（]', str(text))
        return m.group(1).strip() if m else str(text).strip()

    df_heat["road_nm"] = df_heat[seg_col].apply(parse_road_name)
    df_heat[len_col] = pd.to_numeric(df_heat[len_col], errors="coerce").fillna(0)

    # OSM 엣지 with name → + 구 경계 공간 조인
    log.info("  OSM 엣지 로드 및 구 경계 조인...")
    gdf_e = ox.graph_to_gdfs(G, nodes=False, edges=True)
    gdf_e = gdf_e[["name", "geometry", "length"]].copy()
    gdf_e = gdf_e[gdf_e["name"].notna()].to_crs("EPSG:5186")

    # 행정동 → 구 폴리곤
    gdf_dong = gpd.read_file(DONG_SHP).to_crs("EPSG:5186")
    gdf_dong.columns = [c.lower() for c in gdf_dong.columns]
    gdf_dong = gdf_dong[gdf_dong["adm_cd"].astype(str).str.startswith("11")]
    GU_CODE_MAP = {
        "11010":"종로구","11020":"중구","11030":"용산구","11040":"성동구","11050":"광진구",
        "11060":"동대문구","11070":"중랑구","11080":"성북구","11090":"강북구","11100":"도봉구",
        "11110":"노원구","11120":"은평구","11130":"서대문구","11140":"마포구","11150":"양천구",
        "11160":"강서구","11170":"구로구","11180":"금천구","11190":"영등포구","11200":"동작구",
        "11210":"관악구","11220":"서초구","11230":"강남구","11240":"송파구","11250":"강동구",
    }
    gdf_dong["gu_cd"] = gdf_dong["adm_cd"].astype(str).str[:5]
    gdf_dong["gu_nm"] = gdf_dong["gu_cd"].map(GU_CODE_MAP).fillna("기타")
    gdf_gu = gdf_dong.dissolve(by="gu_nm", as_index=False)[["gu_nm", "geometry"]]

    # 엣지 × 구 공간 조인 (which 구 does each edge belong to?)
    log.info("  엣지-구 공간 조인 중...")
    gdf_e_gu = gpd.sjoin(
        gdf_e, gdf_gu[["gu_nm", "geometry"]],
        predicate="intersects", how="left"
    )
    gdf_e_gu = gdf_e_gu.reset_index(drop=True)

    # name 컬럼이 리스트(multiple names)일 경우 첫 번째만 사용
    def normalize_name(n):
        if isinstance(n, list): return n[0] if n else ""
        return str(n)
    gdf_e_gu["name_str"] = gdf_e_gu["name"].apply(normalize_name)

    # 매칭
    log.info(f"  {len(df_heat)} 열선 구간 매칭 중...")
    matched_features = []
    matched_cnt = 0
    for _, row in df_heat.iterrows():
        gu   = str(row[mgr_col]).strip()
        road = str(row["road_nm"]).strip()
        if not road: continue
        mask = (
            gdf_e_gu["name_str"].str.contains(road, na=False, regex=False) &
            (gdf_e_gu["gu_nm"] == gu)
        )
        hits = gdf_e_gu[mask]
        if len(hits) > 0:
            matched_cnt += 1
            for _, h in hits.iterrows():
                geom_wgs = gpd.GeoSeries([h.geometry], crs="EPSG:5186") \
                              .to_crs("EPSG:4326").simplify(0.00005).iloc[0]
                # 좌표 정밀도 5자리로 제한
                def round_coords(c):
                    if hasattr(c[0], '__iter__'):
                        return [round_coords(p) for p in c]
                    return [round(c[0], 5), round(c[1], 5)]
                raw_geom = geom_wgs.__geo_interface__
                raw_geom["coordinates"] = round_coords(raw_geom["coordinates"])
                matched_features.append({
                    "type": "Feature",
                    "geometry": raw_geom,
                    "properties": {
                        "gu": gu,
                        "road": road,
                        "len_m": int(row[len_col]) if row[len_col] else 0,
                    }
                })

    log.info(f"  매칭 성공: {matched_cnt}/{len(df_heat)} 구간, {len(matched_features)} 엣지")
    heat_lines_geojson = json.dumps({
        "type": "FeatureCollection",
        "features": matched_features
    }, ensure_ascii=False, separators=(',', ':'))
    heat_stats = {
        "total_records": len(df_heat),
        "matched_records": matched_cnt,
        "matched_edges": len(matched_features),
    }
    with open(HEAT_LINE_CACHE, "w") as f:
        json.dump({"lines": heat_lines_geojson, "stats": heat_stats}, f)
    log.info("  열선 라인 캐시 저장")

# ── 6. 제설함 포인트 + 구별 통계 ──────────────────────────────────────────────
boxes_json = json.dumps(boxes, ensure_ascii=False)

gu_snow = {}
for b in boxes: gu_snow[b["gu"]] = gu_snow.get(b["gu"], 0) + 1

df_hl = pd.read_csv(HEAT_L, encoding="utf-8-sig")
df_hl.columns = [c.strip() for c in df_hl.columns]
len_col2 = next((c for c in df_hl.columns if "연장" in c), None)
mgr_col2 = next((c for c in df_hl.columns if "관리" in c), None)
df_hl[len_col2] = pd.to_numeric(df_hl[len_col2], errors="coerce").fillna(0)
gu_heat_m = df_hl.groupby(mgr_col2)[len_col2].sum().to_dict()

SEOUL_GU_CENTERS = {
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
gu_data = [{"gu":g, "snow_cnt":gu_snow.get(g,0), "heat_len":int(gu_heat_m.get(g,0)),
             "lat":c[0], "lon":c[1]}
            for g, c in SEOUL_GU_CENTERS.items()]
gu_data_json = json.dumps(gu_data, ensure_ascii=False)
max_heat = max((d["heat_len"] for d in gu_data), default=1)

total_snow = sum(d["snow_cnt"] for d in gu_data)
total_heat = sum(d["heat_len"] for d in gu_data)

# ── 7. 행정동 배경 GeoJSON ─────────────────────────────────────────────────────
gdf_d = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf_d.columns = [c.lower() for c in gdf_d.columns]
gdf_d = gdf_d[gdf_d["adm_cd"].astype(str).str.startswith("11")].copy()
gdf_d["geometry"] = gdf_d.geometry.simplify(0.002)
name_col = "adm_nm"
dong_features = []
for _, row in gdf_d.iterrows():
    g = row.geometry
    if g is None or g.is_empty: continue
    dong_features.append({"type":"Feature","geometry":g.__geo_interface__,
                           "properties":{"name":str(row.get(name_col,""))}})
dong_geojson = json.dumps({"type":"FeatureCollection","features":dong_features},
                           ensure_ascii=False)

# ── 8. HTML 생성 ───────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>겨울 결빙 취약지점 v2 — 서울 2026</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#0d1b2a;color:#eee;height:100vh;display:flex;flex-direction:column}}
#header{{background:#0a1628;padding:10px 18px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-bottom:2px solid #0d47a1}}
h1{{font-size:1rem;font-weight:700;color:#fff;white-space:nowrap}}
.sub{{font-size:.7rem;color:#90caf9;margin-left:4px}}
.ctrl{{display:flex;gap:5px;align-items:center}}
.ctrl label{{font-size:.7rem;color:#aaa;white-space:nowrap}}
.btn{{padding:4px 11px;border:1px solid #333;background:#0d1b2a;color:#ccc;border-radius:4px;cursor:pointer;font-size:.75rem;transition:.15s}}
.btn.active{{background:#0d47a1;border-color:#1565C0;color:#fff}}
.btn:hover:not(.active){{background:#1a2a3a}}
#map{{flex:1}}
#panel{{position:absolute;top:62px;right:12px;z-index:1000;background:rgba(10,22,40,.96);
        border:1px solid #0d47a1;border-radius:8px;padding:12px;width:235px;
        box-shadow:0 4px 24px rgba(0,0,0,.7)}}
#panel h3{{font-size:.8rem;margin-bottom:8px;color:#64B5F6;border-bottom:1px solid #0d47a1;padding-bottom:5px}}
.leg{{display:flex;align-items:center;gap:7px;margin-bottom:5px;font-size:.72rem;line-height:1.3}}
.dot{{width:13px;height:13px;border-radius:2px;flex-shrink:0}}
.line-dot{{width:22px;height:4px;border-radius:2px;flex-shrink:0}}
.stat{{margin-top:9px;padding-top:7px;border-top:1px solid #0d47a1;font-size:.7rem;color:#bbb;line-height:1.9}}
.stat strong{{color:#fff}}
#info{{position:absolute;bottom:28px;left:12px;z-index:1000;background:rgba(10,22,40,.93);
       border:1px solid #0d47a1;border-radius:6px;padding:9px 13px;min-width:175px;
       font-size:.75rem;display:none}}
#info .nm{{font-weight:700;font-size:.84rem;color:#fff;margin-bottom:4px}}
#info .row{{color:#ccc;margin-bottom:2px}}
</style>
</head>
<body>
<div id="header">
  <h1>🧂 겨울 결빙 취약지점 v2
    <span class="sub">제설함 커버리지 × 도로열선 설치 구간 — 한강·산지 제외</span>
  </h1>
  <div class="ctrl">
    <label>제설함 반경</label>
    <button class="btn active" id="btn100" onclick="setRadius(100)">100m</button>
    <button class="btn" id="btn200" onclick="setRadius(200)">200m</button>
  </div>
  <div class="ctrl">
    <label>레이어</label>
    <button class="btn active" id="btn-cov"   onclick="toggle('cov',this)">커버원 ON</button>
    <button class="btn active" id="btn-boxes" onclick="toggle('boxes',this)">제설함 ON</button>
    <button class="btn active" id="btn-heat"  onclick="toggle('heat',this)">열선 ON</button>
  </div>
  <div class="ctrl">
    <label>지도</label>
    <button class="btn active" id="tile-osm"  onclick="setTile('osm',this)">일반</button>
    <button class="btn"        id="tile-esri" onclick="setTile('esri',this)">위성</button>
    <button class="btn"        id="tile-dark" onclick="setTile('dark',this)">Dark</button>
  </div>
</div>
<div id="map"></div>

<div id="panel">
  <h3>🗺️ 범례</h3>
  <div class="leg"><div class="dot" style="background:#1565C0;opacity:.4;border:1px solid #42A5F5"></div>제설함 커버리지 원 (반경 토글)</div>
  <div class="leg"><div class="dot" style="background:#00E5FF;border-radius:50%"></div>제설함 위치</div>
  <div class="leg"><div class="line-dot" style="background:#FF8F00"></div>도로열선 설치 구간 (OSM 매칭)</div>
  <div class="leg"><div class="dot" style="background:#FF6F00;border-radius:50%"></div>구별 열선 총 연장 (버블)</div>
  <div class="stat">
    <strong>제설함</strong> {total_snow:,}개<br>
    <strong>열선</strong> {heat_stats['matched_records']}/{heat_stats['total_records']} 구간 매칭<br>
    &nbsp;&nbsp;({heat_stats['matched_edges']:,}개 도로 엣지)<br><br>
    보행 가능 도로망: <strong>{area_stats['walkable_km2']} km²</strong><br>
    미커버(100m): <strong style="color:#EF9A9A">{area_stats['icing_100_pct']}%</strong>
    &nbsp;({area_stats['icing_100_km2']} km²)<br>
    미커버(200m): <strong style="color:#EF9A9A">{area_stats['icing_200_pct']}%</strong>
    &nbsp;({area_stats['icing_200_km2']} km²)
  </div>
</div>

<div id="info">
  <div class="nm" id="i-name">-</div>
  <div class="row" id="i-snow">-</div>
  <div class="row" id="i-heat">-</div>
</div>

<script>
const BOXES      = {boxes_json};
const GU_DATA    = {gu_data_json};
const DONG_DATA  = {dong_geojson};
const HEAT_LINES = {heat_lines_geojson};
const MAX_HEAT   = {max_heat};
const AREA_STATS = {json.dumps(area_stats)};

// ─── 지도 ─────────────────────────────────────────────────────────────────────
const map = L.map('map', {{center:[37.5665,126.9780], zoom:12}});
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

// ─── 제설함 커버리지 원 ──────────────────────────────────────────────────────
let curR=100;
let covGroup = L.layerGroup();
const on = {{cov:true, boxes:true, heat:true}};

function buildCircles(r){{
  covGroup.clearLayers();
  BOXES.forEach(b=>{{
    L.circle([b.lat,b.lon],{{
      radius:r,
      fillColor:'#1565C0', fillOpacity:.15,
      color:'#1E88E5', weight:.3, opacity:.4
    }}).addTo(covGroup);
  }});
}}
buildCircles(100);
covGroup.addTo(map);

// ─── 열선 라인 ────────────────────────────────────────────────────────────────
const heatLineLayer = L.geoJSON(HEAT_LINES,{{
  style:{{color:'#FF8F00', weight:3, opacity:.9}},
  onEachFeature:(f,l)=>{{
    l.bindTooltip(
      `<b>${{f.properties.road}}</b><br>${{f.properties.gu}}<br>연장: ${{f.properties.len_m}}m`,
      {{sticky:true, direction:'top'}}
    );
  }}
}});

// ─── 제설함 포인트 ────────────────────────────────────────────────────────────
const boxesLayer = L.layerGroup();
BOXES.forEach(b=>{{
  L.circleMarker([b.lat,b.lon],{{
    radius:2, fillColor:'#00E5FF', color:'transparent', fillOpacity:.7
  }}).bindTooltip(`${{b.num}}<br>${{b.addr}}<br>${{b.gu}}`,{{direction:'top'}}).addTo(boxesLayer);
}});

// ─── 구별 열선 버블 ─────────────────────────────────────────────────────────
const guBubbleLayer = L.layerGroup();
GU_DATA.forEach(d=>{{
  if(!d.lat||!d.heat_len) return;
  const r=Math.max(7, Math.sqrt(d.heat_len/MAX_HEAT)*40);
  L.circleMarker([d.lat,d.lon],{{
    radius:r, fillColor:'#FF6F00', color:'#FFB74D', weight:1.5, fillOpacity:.7
  }}).bindTooltip(
    `<b>${{d.gu}}</b><br>열선: ${{d.heat_len.toLocaleString()}}m<br>제설함: ${{d.snow_cnt}}개`,
    {{direction:'top',sticky:true}}
  ).on('click',()=>{{
    document.getElementById('i-name').textContent=d.gu;
    document.getElementById('i-snow').textContent='제설함: '+d.snow_cnt+'개';
    document.getElementById('i-heat').textContent='열선: '+d.heat_len.toLocaleString()+'m';
    document.getElementById('info').style.display='block';
  }}).addTo(guBubbleLayer);
}});

const heatGroup = L.layerGroup([heatLineLayer, guBubbleLayer]);
boxesLayer.addTo(map);
heatGroup.addTo(map);

function toggle(key, btn){{
  on[key]=!on[key];
  if(key==='cov')   on.cov  ?covGroup.addTo(map)   :map.removeLayer(covGroup);
  if(key==='boxes') on.boxes?boxesLayer.addTo(map) :map.removeLayer(boxesLayer);
  if(key==='heat')  on.heat ?heatGroup.addTo(map)  :map.removeLayer(heatGroup);
  btn.classList.toggle('active',on[key]);
  const labels={{cov:'커버원',boxes:'제설함',heat:'열선'}};
  btn.textContent=labels[key]+' '+(on[key]?'ON':'OFF');
}}

function setRadius(r){{
  curR=r; buildCircles(r);
  document.getElementById('btn100').classList.toggle('active',r===100);
  document.getElementById('btn200').classList.toggle('active',r===200);
}}
</script>
</body>
</html>"""

out_path = os.path.join(OUT_DIR, "08_b3_snow_icing_260421.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {os.path.getsize(out_path)//1024} KB")
