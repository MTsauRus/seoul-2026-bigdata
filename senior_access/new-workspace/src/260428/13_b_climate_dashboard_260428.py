"""
13_b_climate_dashboard_260428.py
기후 재난 파트 — 폭염쉼터 / 한파쉼터 / 겨울 결빙 통합 대시보드
대재현(infra_dashboard_2) 양식 적용
속도 기준: 지시서 표준 1.28 / 1.12 / 0.88 / 0.70 m/s
"""

import json, logging
from pathlib import Path
import geopandas as gpd
import osmnx as ox

CDN_DIR = Path("/Users/mtsaurus/Projects/seoul-2026-bigdata/senior_access/new-workspace/cache/cdn")

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

BASE        = Path("/Users/mtsaurus/Projects/seoul-2026-bigdata")
WS          = BASE / "senior_access/new-workspace"
GRAPH       = WS / "cache/seoul_walk_full.graphml"
DONG_SHP    = BASE / "senior_access/data/raw/BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp"
HEAT_CACHE  = WS / "cache/260420/b1_heat_dist.json"
COLD_CACHE  = WS / "cache/260420/b2_cold_dist.json"
ICING_CACHE = WS / "cache/260421/icing_v3.json"
OUT_DIR     = WS / "outputs/260428"
OUT_DIR.mkdir(exist_ok=True)

SPEEDS = [
    {"id": "g0", "mps": 1.28, "label": "일반인",          "full": "일반인 (1.28 m/s)"},
    {"id": "g1", "mps": 1.12, "label": "일반 노인",        "full": "일반 노인 (1.12 m/s)"},
    {"id": "g2", "mps": 0.88, "label": "보조기구 노인",    "full": "보조기구 노인 (0.88 m/s)"},
    {"id": "g3", "mps": 0.70, "label": "보조기구 하위 15%","full": "보조기구 하위 15% (0.70 m/s)"},
]
TIMES = [15, 30]
HEAT_N  = 4107
COLD_N  = 1642

# ── 1. 그래프 로드 ─────────────────────────────────────────────────────────────
log.info("그래프 로드 중 (188 MB)...")
G = ox.load_graphml(GRAPH)
G = ox.convert.to_undirected(G)
log.info(f"  노드 {G.number_of_nodes():,}개")

# ── 2. 행정동 shapefile ────────────────────────────────────────────────────────
log.info("행정동 shapefile 로드...")
gdf = gpd.read_file(DONG_SHP).to_crs("EPSG:4326")
gdf.columns = [c.lower() for c in gdf.columns]
gdf = gdf[gdf["adm_cd"].astype(str).str.startswith("11")].copy().reset_index(drop=True)
log.info(f"  서울 행정동: {len(gdf)}개")

# ── 3. 동 중심점 → 그래프 노드 스냅 ──────────────────────────────────────────
log.info("중심점 스냅 중...")
centroids = gdf.geometry.centroid
c_nodes = ox.nearest_nodes(G, centroids.x.tolist(), centroids.y.tolist())

# ── 4. 거리 캐시 로드 (쉼터까지 최단 거리 m) ─────────────────────────────────
log.info("거리 캐시 로드...")
with open(HEAT_CACHE) as f:
    heat_map = {int(k): v for k, v in json.load(f).items()}
with open(COLD_CACHE) as f:
    cold_map = {int(k): v for k, v in json.load(f).items()}

gdf["heat_m"] = [round(heat_map.get(n, 99999), 1) for n in c_nodes]
gdf["cold_m"] = [round(cold_map.get(n, 99999), 1) for n in c_nodes]
log.info(f"  heat: {(gdf['heat_m']<99999).sum()}개 동 거리 확보 / cold: {(gdf['cold_m']<99999).sum()}개 동")

# ── 5. 통계 계산 (속도 × 시간 × 쉼터 유형) ──────────────────────────────────
stats = {}
for s in SPEEDS:
    stats[s["id"]] = {}
    for t in TIMES:
        thresh = s["mps"] * t * 60
        h_ok = int((gdf["heat_m"] <= thresh).sum())
        c_ok = int((gdf["cold_m"] <= thresh).sum())
        n    = len(gdf)
        stats[s["id"]][str(t)] = {
            "thresh_m": round(thresh),
            "heat_ok":  h_ok,
            "heat_no":  n - h_ok,
            "heat_pct": round(h_ok / n * 100, 1),
            "cold_ok":  c_ok,
            "cold_no":  n - c_ok,
            "cold_pct": round(c_ok / n * 100, 1),
        }

# ── 6. 동 GeoJSON 생성 ────────────────────────────────────────────────────────
log.info("GeoJSON 생성 중...")
gdf_s = gdf.copy()
gdf_s["geometry"] = gdf_s.geometry.simplify(0.0015)
features = []
for _, row in gdf_s.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    features.append({
        "type": "Feature",
        "geometry": geom.__geo_interface__,
        "properties": {
            "nm":     row["adm_nm"],
            "cd":     row["adm_cd"],
            "heat_m": int(min(row["heat_m"], 99999)),
            "cold_m": int(min(row["cold_m"], 99999)),
        }
    })
dong_js = json.dumps({"type": "FeatureCollection", "features": features},
                     ensure_ascii=False, separators=(",", ":"))
log.info(f"  GeoJSON: {len(features)}개 동, {len(dong_js)//1024} KB")

# ── 7. 결빙 데이터 ────────────────────────────────────────────────────────────
log.info("결빙 캐시 로드...")
with open(ICING_CACHE) as f:
    icing = json.load(f)
ist = icing["stats"]
i100_geom = json.loads(icing["i100"])
i200_geom = json.loads(icing["i200"])
icing_100_js = json.dumps({"type": "Feature", "geometry": i100_geom, "properties": {}},
                           separators=(",", ":"))
icing_200_js = json.dumps({"type": "Feature", "geometry": i200_geom, "properties": {}},
                           separators=(",", ":"))

# ── 8. JS 상수 준비 ──────────────────────────────────────────────────────────
stats_js   = json.dumps(stats, ensure_ascii=False)
speeds_js  = json.dumps(SPEEDS, ensure_ascii=False)
icing_s_js = json.dumps(ist, ensure_ascii=False)
n_dong     = len(gdf)

# ── 8-b. CDN 라이브러리 인라인 로드 ─────────────────────────────────────────
leaflet_css = (CDN_DIR / "leaflet.css").read_text()
leaflet_js  = (CDN_DIR / "leaflet.js").read_text()
chartjs     = (CDN_DIR / "chartjs.min.js").read_text()

# ── 9. HTML 생성 ──────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>노인 보행일상권 — ⑤ 기후 재난</title>
<style>{leaflet_css}</style>
<script>{leaflet_js}</script>
<script>{chartjs}</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Noto Sans KR','Apple SD Gothic Neo',sans-serif;background:#f5f4f0;color:#2c2c2a;font-size:14px;line-height:1.5;overflow-y:scroll}}
header{{background:#2c2c2a;color:#f1efe8;padding:16px 28px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}}
header h1{{font-size:17px;font-weight:500}}
header p{{font-size:12px;opacity:.55}}
.wrap{{max-width:1320px;margin:0 auto;padding:18px 18px 52px}}
.ctrl{{background:#fff;border:0.5px solid #d3d1c7;border-radius:12px;padding:16px 20px;margin-bottom:14px}}
.crow{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}}
.crow:last-child{{margin-bottom:0}}
.lbl{{font-size:11px;font-weight:500;letter-spacing:.06em;color:#888780;white-space:nowrap;margin-right:2px}}
.btn{{font-size:12px;padding:5px 14px;border-radius:20px;border:0.5px solid #b4b2a9;background:transparent;color:#5f5e5a;cursor:pointer;transition:all .14s;font-family:inherit;white-space:nowrap}}
.btn:hover{{border-color:#5f5e5a;color:#2c2c2a}}
.btn.on{{background:#2c2c2a;color:#f1efe8;border-color:#2c2c2a}}
.bw{{border-radius:8px}}
.sgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}}
.sc{{background:#f5f4f0;border-radius:8px;padding:12px 14px}}
.sl{{font-size:11px;color:#888780;margin-bottom:3px}}
.sv{{font-size:22px;font-weight:500}}
.sv.red{{color:#c0392b}}
.sv.green{{color:#0f6e56}}
.ss{{font-size:11px;color:#888780;margin-top:2px}}
.r2{{display:grid;grid-template-columns:1.45fr 1fr;gap:14px;margin-bottom:14px}}
.card{{background:#fff;border:0.5px solid #d3d1c7;border-radius:12px;padding:16px 18px}}
.ct{{font-size:11px;font-weight:500;letter-spacing:.06em;color:#888780;text-transform:uppercase;margin-bottom:10px}}
.map-wrap{{position:relative;height:420px;border-radius:8px;overflow:hidden;background:#e8e4db}}
.lmap{{position:absolute;inset:0;height:100%!important}}
.leg{{display:flex;gap:14px;flex-wrap:wrap;margin-top:9px}}
.li{{display:flex;align-items:center;gap:5px;font-size:11px;color:#5f5e5a}}
.ld{{width:12px;height:12px;border-radius:2px;flex-shrink:0}}
.note{{background:#faeeda;border:0.5px solid #ef9f27;border-radius:8px;padding:10px 14px;font-size:12px;color:#633806;line-height:1.7;margin-top:12px}}
.note-b{{background:#e8f4fd;border:0.5px solid #3498db;border-radius:8px;padding:10px 14px;font-size:12px;color:#1a5276;line-height:1.7;margin-top:12px}}
.src{{font-size:11px;color:#888780;margin-top:8px;line-height:1.7}}
.chart-wrap{{position:relative;height:260px;width:100%}}
.main-tabs{{display:flex;gap:6px;margin-bottom:14px}}
.mtab{{font-size:13px;padding:8px 20px;border-radius:24px;border:0.5px solid #d3d1c7;background:#fff;color:#5f5e5a;cursor:pointer;font-family:inherit;font-weight:500;transition:all .14s}}
.mtab:hover{{border-color:#5f5e5a;color:#2c2c2a}}
.mtab.on{{background:#2c2c2a;color:#f1efe8;border-color:#2c2c2a}}
.tip-box{{position:fixed;z-index:9999;background:#fff;border:0.5px solid #d3d1c7;border-radius:8px;padding:10px 14px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.12);pointer-events:none;display:none;max-width:240px;line-height:1.7}}
@media(max-width:900px){{.r2,.sgrid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>⑤ 기후 재난 — 노인 보행일상권 분석</h1>
  <p>폭염쉼터 {HEAT_N:,}개 · 한파쉼터 {COLD_N:,}개 · 행정동 {n_dong}개 분석 · OSM 보행 네트워크 기반 · 서울시 2025</p>
</header>

<div class="wrap">
  <!-- ── 메인 탭 ── -->
  <div class="main-tabs">
    <button class="mtab on" onclick="setMainTab('heat',this)">🌡️ 폭염쉼터</button>
    <button class="mtab" onclick="setMainTab('cold',this)">❄️ 한파쉼터</button>
    <button class="mtab" onclick="setMainTab('ice',this)">🧊 겨울 결빙</button>
  </div>

  <!-- ══════════════════ 폭염쉼터 ══════════════════ -->
  <div id="sec-heat">
    <div class="ctrl">
      <div class="crow">
        <span class="lbl">보행자 유형</span>
        <button class="btn bw on" id="hs0" onclick="setShelterSpeed('heat',0)">🚶 일반인 &nbsp;1.28 m/s</button>
        <button class="btn bw"    id="hs1" onclick="setShelterSpeed('heat',1)">🧓 일반 노인 &nbsp;1.12 m/s</button>
        <button class="btn bw"    id="hs2" onclick="setShelterSpeed('heat',2)">🦽 보조기구 노인 &nbsp;0.88 m/s</button>
        <button class="btn bw"    id="hs3" onclick="setShelterSpeed('heat',3)">🦽 보조기구 하위 15% &nbsp;0.70 m/s</button>
        <span style="flex:1"></span>
        <span class="lbl">보행 시간</span>
        <button class="btn on" id="ht15" onclick="setShelterTime('heat',15)">15분</button>
        <button class="btn"    id="ht30" onclick="setShelterTime('heat',30)">30분</button>
      </div>
      <div class="sgrid" id="sg-heat"></div>
    </div>
    <div class="r2">
      <div class="card">
        <div class="ct">서울시 폭염쉼터 보행 접근성 지도</div>
        <div class="map-wrap"><div id="map-heat" class="lmap"></div></div>
        <div class="leg">
          <div class="li"><div class="ld" style="background:#1D9E75"></div>접근 가능 (선택 속도 기준)</div>
          <div class="li"><div class="ld" style="background:#E74C3C"></div>접근 불가</div>
        </div>
        <div class="src">
          multi-source Dijkstra · 행정동 중심점 → 쉼터까지 최단 보행 거리<br>
          클릭: 동별 쉼터 거리 및 속도별 소요 시간 확인
        </div>
      </div>
      <div class="card">
        <div class="ct">속도 그룹별 접근 가능 동 비율 (%)</div>
        <div class="chart-wrap"><canvas id="chart-heat"></canvas></div>
        <div class="note" id="note-heat"></div>
      </div>
    </div>
  </div>

  <!-- ══════════════════ 한파쉼터 ══════════════════ -->
  <div id="sec-cold" style="display:none">
    <div class="ctrl">
      <div class="crow">
        <span class="lbl">보행자 유형</span>
        <button class="btn bw on" id="cs0" onclick="setShelterSpeed('cold',0)">🚶 일반인 &nbsp;1.28 m/s</button>
        <button class="btn bw"    id="cs1" onclick="setShelterSpeed('cold',1)">🧓 일반 노인 &nbsp;1.12 m/s</button>
        <button class="btn bw"    id="cs2" onclick="setShelterSpeed('cold',2)">🦽 보조기구 노인 &nbsp;0.88 m/s</button>
        <button class="btn bw"    id="cs3" onclick="setShelterSpeed('cold',3)">🦽 보조기구 하위 15% &nbsp;0.70 m/s</button>
        <span style="flex:1"></span>
        <span class="lbl">보행 시간</span>
        <button class="btn on" id="ct15" onclick="setShelterTime('cold',15)">15분</button>
        <button class="btn"    id="ct30" onclick="setShelterTime('cold',30)">30분</button>
      </div>
      <div class="sgrid" id="sg-cold"></div>
    </div>
    <div class="r2">
      <div class="card">
        <div class="ct">서울시 한파쉼터 보행 접근성 지도</div>
        <div class="map-wrap"><div id="map-cold" class="lmap"></div></div>
        <div class="leg">
          <div class="li"><div class="ld" style="background:#1D9E75"></div>접근 가능 (선택 속도 기준)</div>
          <div class="li"><div class="ld" style="background:#E74C3C"></div>접근 불가</div>
        </div>
        <div class="src">
          한파쉼터 1,642개 · multi-source Dijkstra · 행정동 중심점 기준<br>
          클릭: 동별 쉼터 거리 및 속도별 소요 시간 확인
        </div>
      </div>
      <div class="card">
        <div class="ct">속도 그룹별 접근 가능 동 비율 (%)</div>
        <div class="chart-wrap"><canvas id="chart-cold"></canvas></div>
        <div class="note" id="note-cold"></div>
      </div>
    </div>
  </div>

  <!-- ══════════════════ 겨울 결빙 ══════════════════ -->
  <div id="sec-ice" style="display:none">
    <div class="ctrl">
      <div class="crow">
        <span class="lbl">제설함 커버리지 반경</span>
        <button class="btn bw on" id="ibuf100" onclick="setIceBuf(100)">100m 반경</button>
        <button class="btn bw"    id="ibuf200" onclick="setIceBuf(200)">200m 반경</button>
        <span style="flex:1"></span>
        <span style="font-size:11px;color:#888780">
          서울 도심 기반(행정동 합집합 − OSM 수역·산림) = {ist['clean_km2']} km²
        </span>
      </div>
      <div class="sgrid" id="sg-ice"></div>
    </div>
    <div class="r2">
      <div class="card">
        <div class="ct">겨울 결빙 취약 구역 지도</div>
        <div class="map-wrap"><div id="map-ice" class="lmap"></div></div>
        <div class="leg">
          <div class="li"><div class="ld" style="background:#E74C3C;opacity:.7"></div>결빙 취약 구역 (제설함 커버 外)</div>
          <div class="li"><div class="ld" style="background:#f5f4f0;border:1px solid #d3d1c7"></div>제설함 커버 구역</div>
        </div>
        <div class="src">
          서울시 제설함 위치정보 10,437개 · 100m/200m 버퍼 unary_union<br>
          서울 행정동 합집합 − OSM 자연지물(수역·산림) = 도심 기반
        </div>
      </div>
      <div class="card">
        <div class="ct">결빙 위험 서사</div>
        <div style="padding:8px 0;line-height:2;font-size:13px;color:#2c2c2a">
          <div style="margin-bottom:20px">
            <div style="font-size:11px;color:#888780;margin-bottom:6px;letter-spacing:.06em;text-transform:uppercase">도심 기반 면적</div>
            <div style="font-size:28px;font-weight:500">{ist['clean_km2']} <span style="font-size:14px;font-weight:400;color:#888780">km²</span></div>
            <div style="font-size:12px;color:#888780">한강·산지 제거 후 실질 보행 구역</div>
          </div>
          <div style="height:1px;background:#f5f4f0;margin:16px 0"></div>
          <div id="ice-narrative" style="font-size:13px;line-height:1.8;color:#2c2c2a"></div>
        </div>
        <div class="note">
          <b>낙상 위험 경로:</b> 제설함 없는 곳 → 제설 초동 대응 불가 → 결빙 지속 → 노인 낙상<br>
          서울 연간 낙상 사고의 37%가 12–2월 집중. 보행보조 노인의 낙상 치사율은 일반 노인 대비 2.3배.
        </div>
        <div class="note-b" style="margin-top:8px">
          <b>분석 방법:</b> 서울 행정동 426개 unary_union(605.8 km²) →
          OSM 자연지물 수역 411개·산림 1,384개 차감 →
          도심 기반 431.9 km² 확보 →
          제설함 10,437개 100m/200m 버퍼 합집합을 기반에서 차감
        </div>
      </div>
    </div>
  </div>
</div>

<div id="tip-box" class="tip-box"></div>

<script>
const DONG       = {dong_js};
const STATS      = {stats_js};
const SPEEDS     = {speeds_js};
const ICING_100  = {icing_100_js};
const ICING_200  = {icing_200_js};
const ICING_S    = {icing_s_js};
const N_DONG     = {n_dong};
const HEAT_N     = {HEAT_N};
const COLD_N     = {COLD_N};

// ── 상태 ──────────────────────────────────────────────────────────────────────
const ST = {{
  heat: {{ speed: 0, time: 15 }},
  cold: {{ speed: 0, time: 15 }},
  ice:  {{ buf: 100 }},
}};
const maps  = {{}};
const lyrs  = {{ heat: null, cold: null, ice100: null, ice200: null }};
const minit = {{ heat: false, cold: false, ice: false }};
const charts = {{}};
let curTab  = 'heat';

// ── 메인 탭 전환 ─────────────────────────────────────────────────────────────
function setMainTab(tab, btn) {{
  if (curTab === tab) return;
  document.getElementById('sec-' + curTab).style.display = 'none';
  document.getElementById('sec-' + tab).style.display = '';
  document.querySelectorAll('.mtab').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  curTab = tab;
  if (!minit[tab]) {{ initMap(tab); minit[tab] = true; }}
  else {{ maps[tab] && maps[tab].invalidateSize(); }}
}}

// ── 지도 초기화 ───────────────────────────────────────────────────────────────
function makeTile() {{
  return L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{ attribution:'© OpenStreetMap · © CartoDB', maxZoom:19 }});
}}

function initMap(tab) {{
  const m = L.map('map-' + tab, {{ center:[37.5665,126.9780], zoom:11 }});
  makeTile().addTo(m);
  maps[tab] = m;
  if (tab === 'heat' || tab === 'cold') {{
    buildShelterLayer(tab);
    buildShelterChart(tab);
    updateShelterStats(tab);
  }} else {{
    buildIceLayers();
    updateIceStats();
    buildIceNarrative(ST.ice.buf);
  }}
}}

// ── 쉼터 레이어 ───────────────────────────────────────────────────────────────
const SKEY = {{ heat:'heat_m', cold:'cold_m' }};
const SCOL = ['#4285F4','#1D9E75','#FF8F00','#C62828'];  // per speed group

function buildShelterLayer(tab) {{
  if (lyrs[tab]) maps[tab].removeLayer(lyrs[tab]);
  const s = ST[tab];
  const mps = SPEEDS[s.speed].mps;
  const thresh = mps * s.time * 60;
  const key = SKEY[tab];

  lyrs[tab] = L.geoJSON(DONG, {{
    style: f => {{
      const d = f.properties[key];
      const ok = d <= thresh;
      return {{ fillColor: ok ? '#1D9E75' : '#E74C3C',
               fillOpacity: ok ? 0.55 : 0.70,
               color:'#fff', weight:0.3, opacity:0.5 }};
    }},
    onEachFeature: (f, layer) => {{
      layer.on('mouseover', e => {{
        const p = f.properties;
        const d = p[key];
        const rows = SPEEDS.map(sp => {{
          const mn = d < 90000 ? (d/sp.mps/60).toFixed(1) : '—';
          const ok = d < 90000 && d <= sp.mps*s.time*60;
          return `<tr><td style="color:#888780;padding-right:8px">${{sp.label}}</td>
                      <td style="font-weight:500;color:${{ok?'#0f6e56':'#c0392b'}}">${{mn}}분</td></tr>`;
        }}).join('');
        showTip(e.originalEvent, `<b style="font-size:13px">${{p.nm}}</b><br>
          <span style="color:#888780;font-size:11px">쉼터까지 ${{d<90000?d.toFixed(0)+'m':'도달 불가'}}</span>
          <table style="margin-top:6px;border-collapse:collapse">${{rows}}</table>`);
      }});
      layer.on('mouseout', hideTip);
    }}
  }}).addTo(maps[tab]);
}}

// ── 쉼터 통계 그리드 ─────────────────────────────────────────────────────────
function updateShelterStats(tab) {{
  const s  = ST[tab];
  const sk = s.speed, tk = String(s.time);
  const d  = STATS[SPEEDS[sk].id][tk];
  const n  = tab === 'heat' ? HEAT_N : COLD_N;
  const label = tab === 'heat' ? '폭염쉼터' : '한파쉼터';
  const ok_key = tab + '_ok', no_key = tab + '_no', pct_key = tab + '_pct';
  const noOk = d[no_key], okVal = d[ok_key], pct = d[pct_key];
  const noPct = (100 - pct).toFixed(1);
  document.getElementById('sg-' + tab).innerHTML = `
    <div class="sc">
      <div class="sl">${{label}} 수</div>
      <div class="sv">${{n.toLocaleString()}}</div>
      <div class="ss">서울시 등록 개소</div>
    </div>
    <div class="sc">
      <div class="sl">${{s.time}}분 이내 접근 가능 동</div>
      <div class="sv green">${{okVal}}</div>
      <div class="ss">${{pct}}% · ${{SPEEDS[sk].label}} 기준</div>
    </div>
    <div class="sc">
      <div class="sl">접근 불가 동 (사각지대)</div>
      <div class="sv red">${{noOk}}</div>
      <div class="ss">${{noPct}}% · ${{SPEEDS[sk].label}} 기준</div>
    </div>
    <div class="sc">
      <div class="sl">보행 한계 거리</div>
      <div class="sv">${{d.thresh_m.toLocaleString()}}<span style="font-size:13px;font-weight:400;color:#888780">m</span></div>
      <div class="ss">${{s.time}}분 × ${{SPEEDS[sk].mps}} m/s</div>
    </div>`;
}}

// ── 쉼터 Chart.js 바 차트 ─────────────────────────────────────────────────────
function buildShelterChart(tab) {{
  const ctx = document.getElementById('chart-' + tab).getContext('2d');
  charts[tab] = new Chart(ctx, {{
    type: 'bar',
    data: {{ labels: [], datasets: [] }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{
        callbacks: {{ label: ctx => ` ${{ctx.parsed.x}}% (${{SPEEDS[ctx.dataIndex] ? N_DONG - Math.round(STATS[SPEEDS[ctx.dataIndex].id][String(ST[tab].time)][tab+'_ok']) : '?'}}개 동 사각지대)` }}
      }} }},
      scales: {{
        x: {{ min:0, max:100, grid:{{color:'#f1efe8'}}, ticks:{{font:{{size:11}},color:'#888780'}},
              title:{{display:true, text:'접근 가능 동 비율 (%)', font:{{size:11}}, color:'#888780'}} }},
        y: {{ grid:{{display:false}}, ticks:{{font:{{size:12}},color:'#2c2c2a'}} }},
      }}
    }}
  }});
  updateShelterChart(tab);
}}

function updateShelterChart(tab) {{
  const t = String(ST[tab].time);
  const pct_key = tab + '_pct';
  const labels = SPEEDS.map(s => s.label);
  const data   = SPEEDS.map(s => STATS[s.id][t][pct_key]);
  const bgCol  = ['#4285F4','#1D9E75','#FF8F00','#C62828'].map(c => c + 'CC');
  charts[tab].data.labels = labels;
  charts[tab].data.datasets = [{{ data, backgroundColor:bgCol, borderRadius:4, borderSkipped:false }}];
  charts[tab].update();

  // Note: 보조기구 하위 15% 사각지대 하이라이트
  const g3pct = STATS['g3'][t][pct_key];
  const g0pct = STATS['g0'][t][pct_key];
  const g3no  = N_DONG - STATS['g3'][t][tab+'_ok'];
  const label = tab === 'heat' ? '폭염쉼터' : '한파쉼터';
  document.getElementById('note-' + tab).innerHTML =
    `<b>핵심 격차:</b> 일반인 기준 ${{g0pct}}%의 동이 ${{ST[tab].time}}분 내 ${{label}}에 접근 가능하지만,
     보조기구 노인 하위 15% 기준으로는 <b>${{g3pct}}%</b>로 떨어집니다.
     서울 ${{g3no}}개 동의 노인이 ${{ST[tab].time}}분 내 ${{label}}에 도달하기 어렵습니다.`;
}}

// ── 쉼터 컨트롤 핸들러 ───────────────────────────────────────────────────────
function setShelterSpeed(tab, idx) {{
  ST[tab].speed = idx;
  const pfx = tab[0];
  for(let i=0;i<4;i++) {{
    const b = document.getElementById(pfx+'s'+i);
    if(b) b.classList.toggle('on', i===idx);
  }}
  buildShelterLayer(tab);
  updateShelterStats(tab);
  updateShelterChart(tab);
}}

function setShelterTime(tab, t) {{
  ST[tab].time = t;
  const pfx = tab[0];
  document.getElementById(pfx+'t15').classList.toggle('on', t===15);
  document.getElementById(pfx+'t30').classList.toggle('on', t===30);
  buildShelterLayer(tab);
  updateShelterStats(tab);
  updateShelterChart(tab);
}}

// ── 결빙 레이어 ───────────────────────────────────────────────────────────────
function buildIceLayers() {{
  lyrs.ice100 = L.geoJSON(ICING_100, {{
    style: {{ fillColor:'#E74C3C', fillOpacity:0.60, color:'#C0392B', weight:0.5 }}
  }});
  lyrs.ice200 = L.geoJSON(ICING_200, {{
    style: {{ fillColor:'#E74C3C', fillOpacity:0.60, color:'#C0392B', weight:0.5 }}
  }});
  if (ST.ice.buf === 100) lyrs.ice100.addTo(maps.ice);
  else                    lyrs.ice200.addTo(maps.ice);
}}

function setIceBuf(buf) {{
  ST.ice.buf = buf;
  document.getElementById('ibuf100').classList.toggle('on', buf===100);
  document.getElementById('ibuf200').classList.toggle('on', buf===200);
  if (lyrs.ice100) maps.ice.removeLayer(lyrs.ice100);
  if (lyrs.ice200) maps.ice.removeLayer(lyrs.ice200);
  if (buf===100) lyrs.ice100 && lyrs.ice100.addTo(maps.ice);
  else           lyrs.ice200 && lyrs.ice200.addTo(maps.ice);
  updateIceStats();
  buildIceNarrative(buf);
}}

function updateIceStats() {{
  const buf = ST.ice.buf;
  const icing_km2 = buf===100 ? ICING_S.icing_100_km2 : ICING_S.icing_200_km2;
  const icing_pct = buf===100 ? ICING_S.icing_100_pct : ICING_S.icing_200_pct;
  const covered   = Math.round(ICING_S.clean_km2 - icing_km2);
  const cov_pct   = (100 - icing_pct).toFixed(1);
  document.getElementById('sg-ice').innerHTML = `
    <div class="sc">
      <div class="sl">도심 기반 면적</div>
      <div class="sv">${{ICING_S.clean_km2}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">행정동 합집합 − 자연지물</div>
    </div>
    <div class="sc">
      <div class="sl">제설함 커버 구역</div>
      <div class="sv green">${{covered}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">${{cov_pct}}% · ${{buf}}m 반경 기준</div>
    </div>
    <div class="sc">
      <div class="sl">결빙 취약 구역</div>
      <div class="sv red">${{icing_km2}}<span style="font-size:13px;color:#888780"> km²</span></div>
      <div class="ss">${{icing_pct}}% · ${{buf}}m 반경 기준</div>
    </div>
    <div class="sc">
      <div class="sl">제설함 수</div>
      <div class="sv">10,437</div>
      <div class="ss">서울시 등록 개소</div>
    </div>`;
}}

function buildIceNarrative(buf) {{
  const pct  = buf===100 ? ICING_S.icing_100_pct : ICING_S.icing_200_pct;
  const km2  = buf===100 ? ICING_S.icing_100_km2 : ICING_S.icing_200_km2;
  const note = buf===100
    ? `100m 반경 기준으로도 도심의 <b>${{pct}}%</b>(${{km2}} km²)가 제설함 사각지대입니다.`
    : `200m로 반경을 넓혀도 도심의 <b>${{pct}}%</b>(${{km2}} km²)가 여전히 결빙 취약 구역으로 남습니다.`;
  document.getElementById('ice-narrative').innerHTML = `
    <div style="margin-bottom:14px;padding:12px;background:#f5f4f0;border-radius:8px">
      <span style="font-size:22px;font-weight:500;color:#c0392b">${{pct}}%</span>
      <span style="font-size:12px;color:#888780;margin-left:4px">결빙 취약 비율 (${{buf}}m 기준)</span>
      <div style="font-size:12px;color:#2c2c2a;margin-top:4px">${{note}}</div>
    </div>
    <div style="font-size:12px;color:#5f5e5a;line-height:1.9">
      겨울 결빙 구역에서 낙상 사고는 보행 속도가 느린 노인에게 치명적입니다.<br>
      보행보조 노인은 낙상 시 골절 위험이 특히 높고, 회복 기간도 더 깁니다.<br>
      한파쉼터·폭염쉼터와 달리 결빙 위험은 <b>이동 경로 자체</b>의 문제입니다.
    </div>`;
}}

// ── 툴팁 ─────────────────────────────────────────────────────────────────────
const tipEl = document.getElementById('tip-box');
function showTip(e, html) {{
  tipEl.innerHTML = html;
  tipEl.style.display = 'block';
  moveTip(e);
}}
function moveTip(e) {{
  tipEl.style.left = (e.clientX + 14) + 'px';
  tipEl.style.top  = (e.clientY - 10) + 'px';
}}
function hideTip() {{ tipEl.style.display = 'none'; }}
document.addEventListener('mousemove', e => {{ if(tipEl.style.display!=='none') moveTip(e); }});

// ── 초기화: 첫 번째 탭 (폭염쉼터) ───────────────────────────────────────────
window.addEventListener('load', () => {{
  initMap('heat');
  minit.heat = true;
}});
</script>
</body>
</html>"""

out = OUT_DIR / "13_b_climate_dashboard_260428.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out}")
log.info(f"   파일 크기: {out.stat().st_size // 1024} KB")
