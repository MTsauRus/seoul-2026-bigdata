"""
05_a1_dual_isochrone_260420.py
───────────────────────────────────────────────────────────────────────
시각화 A1 — "한 지점에서의 충격" 등시선 오버레이 지도

260418 → 260420 보완:
  ✗ 이전: 길동 단일 고정 지점, 슬라이더 없음, 타일 고정 Dark
  ✓ 이번:
      - 5개 지점 드롭다운
      - 지점별 인근 지하철역·주요시설 마커 (그룹 도달 여부 색상 분류)
      - 타일 스위처: 일반(OSM) / 위성(Esri) / Dark(CartoDB)
      - 시간 슬라이더 15 / 30 / 45분
      - 강조 그룹 슬라이더 (3단계 연구 기반 속도)
      - 3개 등시선 동시 중첩 표시

보행속도 (한음 외, 2020. 한국ITS학회 19(4). n=4,857):
  - 일반인   (65세 미만) : 1.28 m/s
  - 65세 이상 노인       : 1.12 m/s
  - 보행보조장치 사용    : 0.88 m/s

출력: ../outputs/05_a1_dual_isochrone_260420.html
"""

import json
import logging
import warnings
from pathlib import Path

import networkx as nx
import osmnx as ox
import pyproj
from shapely.geometry import MultiPoint, Point
from shapely.ops import transform as shp_transform

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── 경로 ──────────────────────────────────────────────────────────────
WORKSPACE  = Path(__file__).resolve().parents[2]
GRAPH_PATH = WORKSPACE / "cache" / "seoul_walk_full.graphml"
CACHE_DIR  = Path(__file__).resolve().parents[1] / "cache"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "isochrones_a1_260420.json"

# ── 5개 출발 지점 ─────────────────────────────────────────────────────
POINTS = [
    {"id": "p0", "name": "종로 탑골공원",   "lon": 126.9901, "lat": 37.5720,
     "desc": "도심 · 인프라 집중 지역"},
    {"id": "p1", "name": "강북구 미아역",   "lon": 127.0263, "lat": 37.6163,
     "desc": "동북권 · 경사·골목 많음"},
    {"id": "p2", "name": "관악구 신림동",   "lon": 126.9194, "lat": 37.4837,
     "desc": "서남권 · 급경사 지역"},
    {"id": "p3", "name": "강남구 삼성역",   "lon": 127.0627, "lat": 37.5088,
     "desc": "동남권 · 평지·신도시"},
    {"id": "p4", "name": "송파구 잠실새내", "lon": 127.0839, "lat": 37.5115,
     "desc": "대규모 아파트 단지"},
]

# ── 지점별 랜드마크 ───────────────────────────────────────────────────
# (name, lon, lat, type)  type: subway | hospital | market | gov | park
LANDMARKS = {
    "p0": [
        ("종로3가역",      126.9919, 37.5716, "subway"),
        ("종로5가역",      127.0006, 37.5701, "subway"),
        ("을지로3가역",    126.9929, 37.5662, "subway"),
        ("안국역",         126.9852, 37.5763, "subway"),
        ("종각역",         126.9827, 37.5701, "subway"),
        ("혜화역",         127.0016, 37.5826, "subway"),
        ("서울대병원",     126.9993, 37.5797, "hospital"),
        ("종로구청",       126.9783, 37.5726, "gov"),
        ("광장시장",       126.9997, 37.5699, "market"),
        ("탑골공원",       126.9901, 37.5726, "park"),
    ],
    "p1": [
        ("미아역",         127.0260, 37.6135, "subway"),
        ("미아사거리역",   127.0264, 37.6075, "subway"),
        ("솔밭공원역",     127.0261, 37.6196, "subway"),
        ("수유역",         127.0256, 37.6381, "subway"),
        ("강북구청",       127.0272, 37.6370, "gov"),
        ("강북보건소",     127.0249, 37.6182, "hospital"),
        ("미아시장",       127.0278, 37.6143, "market"),
    ],
    "p2": [
        ("신림역",         126.9232, 37.4845, "subway"),
        ("서원역",         126.9129, 37.4835, "subway"),
        ("신대방삼거리역", 126.9123, 37.4949, "subway"),
        ("봉천역",         126.9295, 37.4925, "subway"),
        ("관악구청",       126.9394, 37.4776, "gov"),
        ("관악보건소",     126.9259, 37.4784, "hospital"),
        ("신림시장",       126.9214, 37.4826, "market"),
        ("서울대입구역",   126.9527, 37.4813, "subway"),
    ],
    "p3": [
        ("삼성역",         127.0631, 37.5089, "subway"),
        ("선릉역",         127.0494, 37.5045, "subway"),
        ("종합운동장역",   127.0734, 37.5114, "subway"),
        ("봉은사역",       127.0596, 37.5147, "subway"),
        ("강남구청역",     127.0434, 37.5173, "subway"),
        ("강남구청",       127.0436, 37.5173, "gov"),
        ("코엑스",         127.0594, 37.5124, "market"),
        ("강남세브란스병원",127.0570, 37.4990, "hospital"),
    ],
    "p4": [
        ("잠실새내역",     127.0838, 37.5115, "subway"),
        ("잠실역",         127.1001, 37.5133, "subway"),
        ("잠실나루역",     127.0838, 37.5207, "subway"),
        ("석촌역",         127.1000, 37.5037, "subway"),
        ("올림픽공원역",   127.1179, 37.5221, "subway"),
        ("롯데월드몰",     127.0985, 37.5132, "market"),
        ("올림픽공원",     127.1179, 37.5222, "park"),
        ("송파보건소",     127.1107, 37.5130, "hospital"),
    ],
}

# ── 보행 그룹 ─────────────────────────────────────────────────────────
GROUPS = [
    {"id": "g0", "label": "일반인 (65세 미만)",  "short": "일반인",   "mps": 1.28},
    {"id": "g1", "label": "65세 이상 노인",       "short": "65세+",   "mps": 1.12},
    {"id": "g2", "label": "보행보조장치 사용",    "short": "보조장치", "mps": 0.88},
]

TIMES = [15, 30, 45]

# ── 좌표계 변환 ───────────────────────────────────────────────────────
_TO5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

def area_km2(poly):
    return shp_transform(_TO5179.transform, poly).area / 1e6


# ── 등시선 계산 ───────────────────────────────────────────────────────
def compute_iso(G, node, speed_mps, time_min):
    cutoff = time_min * 60.0

    def wt(u, v, d):
        vals = d.values() if isinstance(d, dict) else [d]
        return min(dd.get("length", 1.0) / speed_mps for dd in vals)

    reachable = nx.single_source_dijkstra_path_length(
        G, node, cutoff=cutoff, weight=wt
    )
    pts = [Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in reachable]
    if len(pts) < 3:
        return Point(G.nodes[node]["x"], G.nodes[node]["y"]).buffer(0.001)
    mp = MultiPoint(pts)
    try:
        poly = mp.concave_hull(ratio=0.05, allow_holes=False)
    except Exception:
        poly = mp.convex_hull
    return poly if (poly.is_valid and not poly.is_empty) else mp.convex_hull


# ── 전체 사전 계산 ────────────────────────────────────────────────────
def compute_all(G):
    """
    iso_data  : {pid: {gid: {str(time): geojson}}}
    area_data : {pid: {gid: {str(time): float}}}
    reach_data: {pid: {str(time): {landmark_idx: [g0_bool, g1_bool, g2_bool]}}}
    """
    iso_data   = {}
    area_data  = {}
    reach_data = {}

    total = len(POINTS) * len(GROUPS) * len(TIMES)
    done  = 0

    for pt in POINTS:
        pid  = pt["id"]
        node = ox.distance.nearest_nodes(G, pt["lon"], pt["lat"])
        logger.info("출발점: %s → 노드 %d", pt["name"], node)
        iso_data[pid]  = {}
        area_data[pid] = {}
        reach_data[pid] = {}

        # 그룹별 등시선 먼저 계산
        polys = {}  # {gid: {t: poly}}
        for grp in GROUPS:
            gid = grp["id"]
            iso_data[pid][gid]  = {}
            area_data[pid][gid] = {}
            polys[gid] = {}
            for t in TIMES:
                poly = compute_iso(G, node, grp["mps"], t)
                km2  = area_km2(poly)
                iso_data[pid][gid][str(t)]  = json.loads(json.dumps(poly.__geo_interface__))
                area_data[pid][gid][str(t)] = round(km2, 4)
                polys[gid][t] = poly
                done += 1
                logger.info("  [%d/%d] %s / %s / %d분 → %.3f km²",
                            done, total, pt["name"], grp["label"], t, km2)

        # 랜드마크 도달 여부: 각 시간별로 3개 그룹 체크
        lms = LANDMARKS.get(pid, [])
        for t in TIMES:
            reach_data[pid][str(t)] = {}
            for li, (lname, llon, llat, ltype) in enumerate(lms):
                p = Point(llon, llat)
                flags = [1 if polys[grp["id"]][t].contains(p) else 0
                         for grp in GROUPS]
                reach_data[pid][str(t)][str(li)] = flags

    return iso_data, area_data, reach_data


# ── HTML ──────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>같은 30분, 다른 서울</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
       background:#0d1117;color:#e6edf3;height:100vh;display:flex;flex-direction:column}

  header{background:#161b22;border-bottom:1px solid #30363d;padding:8px 14px;
         display:flex;align-items:center;gap:10px;flex-shrink:0;flex-wrap:wrap}
  header h1{font-size:14px;font-weight:700;color:#f0f6fc;white-space:nowrap}
  header p{font-size:10px;color:#8b949e}

  .controls{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;margin-left:auto}
  .ctrl-group{display:flex;flex-direction:column;gap:2px}
  .ctrl-group label{font-size:9px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em}
  select{background:#0d1117;border:1px solid #30363d;border-radius:5px;
         color:#e6edf3;font-size:12px;padding:4px 8px;cursor:pointer}
  select:focus{outline:none;border-color:#388bfd}

  .sl-wrap{background:#0d1117;border:1px solid #30363d;border-radius:5px;
           padding:5px 9px;min-width:170px}
  .sl-row{display:flex;align-items:center;gap:6px}
  input[type=range]{-webkit-appearance:none;flex:1;height:4px;border-radius:2px;
                    background:#30363d;outline:none;cursor:pointer}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:13px;height:13px;
    border-radius:50%;background:#388bfd;cursor:pointer}
  .sl-ticks{display:flex;justify-content:space-between;font-size:9px;color:#6e7681;
            margin-top:1px;padding:0 1px}
  .sl-val{font-size:11px;font-weight:700;color:#79c0ff;min-width:52px;text-align:right;white-space:nowrap}

  /* tile switcher */
  .tile-btns{display:flex;gap:4px}
  .tile-btn{background:#0d1117;border:1px solid #30363d;border-radius:4px;
            color:#8b949e;font-size:10px;padding:4px 7px;cursor:pointer;transition:all .15s}
  .tile-btn.active{background:#388bfd22;border-color:#388bfd;color:#79c0ff}

  .main{display:flex;flex:1;overflow:hidden}
  #map{flex:1}
  .side{width:295px;flex-shrink:0;background:#161b22;
        border-left:1px solid #30363d;display:flex;flex-direction:column;overflow-y:auto}

  .ps{padding:12px 14px;border-bottom:1px solid #21262d}
  .ps h3{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#8b949e;margin-bottom:9px}

  .area-cards{display:flex;flex-direction:column;gap:5px}
  .acard{border-radius:7px;padding:9px 11px;border:2px solid transparent;
         transition:all .2s;cursor:pointer}
  .acard .top{display:flex;justify-content:space-between;align-items:baseline}
  .acard .lbl{font-size:11px;font-weight:600}
  .acard .km2{font-size:15px;font-weight:700}
  .acard .bt{background:#1a1f27;border-radius:3px;height:5px;margin-top:6px}
  .acard .bf{height:5px;border-radius:3px;transition:width .5s}
  .acard .losslbl{font-size:10px;margin-top:3px}

  .sbox{background:#0d1117;border-radius:7px;padding:9px 11px;margin-top:6px}
  .sbox .st{font-size:9px;color:#8b949e;margin-bottom:5px}
  .sr{display:flex;justify-content:space-between;font-size:11px;padding:3px 0;
      border-bottom:1px solid #1a1f27}
  .sr:last-child{border:none}
  .sr .k{color:#8b949e}
  .sr .v{font-weight:700}

  /* landmark panel */
  .lm-section{padding:10px 14px;border-bottom:1px solid #21262d}
  .lm-section h3{font-size:10px;text-transform:uppercase;color:#8b949e;
                 letter-spacing:.06em;margin-bottom:8px}
  .lm-row{display:flex;align-items:center;gap:6px;padding:3px 0;font-size:11px}
  .lm-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
  .lm-name{flex:1;color:#c9d1d9}
  .lm-flags{display:flex;gap:3px}
  .lm-flag{font-size:9px;padding:1px 4px;border-radius:3px;font-weight:600}
  .lm-ok  {background:#14532d;color:#86efac}
  .lm-no  {background:#3f0f0f;color:#fca5a5}

  .pt-info{padding:10px 14px;background:#0d1117;border-top:1px solid #21262d;flex-shrink:0}
  .pt-info h4{font-size:12px;font-weight:700;color:#f0f6fc;margin-bottom:3px}
  .pt-info p{font-size:10px;color:#8b949e;line-height:1.5}

  .legend{padding:9px 14px;border-top:1px solid #30363d;flex-shrink:0;font-size:11px}
  .leg-row{display:flex;align-items:center;gap:6px;margin:3px 0}
  .leg-dot{width:14px;height:9px;border-radius:2px;flex-shrink:0}
  .leg-sep{border-top:1px solid #21262d;margin:6px 0}

  .note{padding:8px 14px;font-size:9px;color:#6e7681;line-height:1.6}
</style>
</head>
<body>
<header>
  <div>
    <h1>같은 30분, 다른 서울</h1>
    <p>OSM 실제 보행 네트워크 Dijkstra 등시선 · 3개 그룹 동시 중첩 비교</p>
  </div>
  <div class="controls">
    <!-- 타일 스위처 -->
    <div class="ctrl-group">
      <label>🗺 배경지도</label>
      <div class="tile-btns">
        <button class="tile-btn active" onclick="setTile('osm',this)">일반</button>
        <button class="tile-btn" onclick="setTile('esri',this)">위성</button>
        <button class="tile-btn" onclick="setTile('dark',this)">Dark</button>
      </div>
    </div>
    <!-- 지점 드롭다운 -->
    <div class="ctrl-group">
      <label>📍 출발 지점</label>
      <select id="sel-point" onchange="update()">__POINT_OPTS__</select>
    </div>
    <!-- 시간 슬라이더 -->
    <div class="ctrl-group">
      <label>⏱ 보행 시간</label>
      <div class="sl-wrap">
        <div class="sl-row">
          <input type="range" id="sl-time" min="0" max="2" step="1" value="1" oninput="update()"/>
          <span class="sl-val" id="lbl-time">30분</span>
        </div>
        <div class="sl-ticks"><span>15분</span><span>30분</span><span>45분</span></div>
      </div>
    </div>
    <!-- 강조 슬라이더 -->
    <div class="ctrl-group">
      <label>🔍 강조 그룹</label>
      <div class="sl-wrap">
        <div class="sl-row">
          <input type="range" id="sl-speed" min="0" max="2" step="1" value="2" oninput="update()"/>
          <span class="sl-val" id="lbl-speed">보조장치</span>
        </div>
        <div class="sl-ticks"><span>일반인</span><span>65세+</span><span>보조장치</span></div>
      </div>
    </div>
  </div>
</header>

<div class="main">
  <div id="map"></div>
  <aside class="side">
    <!-- 면적 비교 -->
    <div class="ps">
      <h3 id="panel-title">그룹별 도달 면적</h3>
      <div class="area-cards" id="gcards"></div>
      <div class="sbox" id="sbox"></div>
    </div>
    <!-- 랜드마크 -->
    <div class="lm-section">
      <h3>인근 랜드마크 도달 가능 여부</h3>
      <div id="lm-list"></div>
    </div>
    <!-- 지점 정보 -->
    <div class="pt-info">
      <h4 id="pt-name">—</h4>
      <p id="pt-desc">—</p>
    </div>
    <!-- 범례 -->
    <div class="legend">
      <div class="leg-row"><div class="leg-dot" style="background:rgba(66,148,245,.7)"></div> 일반인 (1.28 m/s)</div>
      <div class="leg-row"><div class="leg-dot" style="background:rgba(255,165,0,.7)"></div> 65세 이상 (1.12 m/s)</div>
      <div class="leg-row"><div class="leg-dot" style="background:rgba(248,81,73,.75)"></div> 보행보조장치 (0.88 m/s)</div>
      <div class="leg-row"><div class="leg-dot" style="background:rgba(210,153,34,.65)"></div> 잃어버린 영역</div>
      <div class="leg-sep"></div>
      <div class="leg-row"><div class="leg-dot" style="background:#00FF88;border-radius:50%"></div> 모두 도달 가능</div>
      <div class="leg-row"><div class="leg-dot" style="background:#FFD700;border-radius:50%"></div> 일반인만 도달</div>
      <div class="leg-row"><div class="leg-dot" style="background:#888;border-radius:50%"></div> 도달 불가</div>
    </div>
    <div class="note">
      출처: 한음 외 (2020). 한국ITS학회 19(4). n=4,857<br>
      보행 그래프: © OpenStreetMap (osmnx 2.1.0) · 162,440 노드
    </div>
  </aside>
</div>

<script>
const ISOS   = __ISO_DATA__;
const AREAS  = __AREA_DATA__;
const REACH  = __REACH_DATA__;
const POINTS = __POINT_DATA__;
const LMS    = __LM_DATA__;

const TIMES  = [15, 30, 45];
const GROUPS = [
  {id:'g0', label:'일반인 (65세 미만)',  short:'일반인',   mps:1.28,
   hiOp:0.30, loOp:0.10, border:'#4294f5', borderDim:'#1a3a6e', bg:'rgba(66,148,245,0.08)'},
  {id:'g1', label:'65세 이상 노인',       short:'65세+',    mps:1.12,
   hiOp:0.42, loOp:0.10, border:'#ffa500', borderDim:'#4a3000', bg:'rgba(255,165,0,0.08)'},
  {id:'g2', label:'보행보조장치 사용',    short:'보조장치', mps:0.88,
   hiOp:0.55, loOp:0.12, border:'#f85149', borderDim:'#4a1010', bg:'rgba(248,81,73,0.08)'},
];

const LM_TYPE_ICON = {
  subway:   '🚇',
  hospital: '🏥',
  market:   '🛒',
  gov:      '🏛️',
  park:     '🌿',
};
const LM_TYPE_COLOR = {
  subway:   '#60A5FA',
  hospital: '#F87171',
  market:   '#FBBF24',
  gov:      '#A78BFA',
  park:     '#4ADE80',
};

// ── 타일 레이어 ───────────────────────────────────────────
const TILES = {
  osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {attribution:'&copy; OpenStreetMap',maxZoom:19}),
  esri: L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {attribution:'Esri World Imagery',maxZoom:19}),
  dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {attribution:'&copy; OpenStreetMap &copy; CARTO',subdomains:'abcd',maxZoom:19}),
};
let curTile = 'osm';

const map = L.map('map',{center:[37.5665,126.978],zoom:12,zoomControl:true});
TILES.osm.addTo(map);

function setTile(key, btn){
  if(key===curTile) return;
  map.removeLayer(TILES[curTile]);
  TILES[key].addTo(map);
  curTile = key;
  document.querySelectorAll('.tile-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}

// ── 레이어 관리 ───────────────────────────────────────────
let isoLayers = [];
let lmLayers  = [];
let lyMarker  = null;

function rings(geoj){
  if(geoj.type==='Polygon')      return [geoj.coordinates.map(r=>r.map(c=>[c[1],c[0]]))];
  if(geoj.type==='MultiPolygon') return geoj.coordinates.map(p=>p.map(r=>r.map(c=>[c[1],c[0]])));
  return [];
}
function drawPoly(geoj, opts, tip){
  const g = L.featureGroup();
  rings(geoj).forEach(rr=>{
    const p = L.polygon(rr, opts);
    if(tip) p.bindTooltip(tip,{sticky:true});
    p.addTo(g);
  });
  g.addTo(map);
  return g;
}

// ── 메인 업데이트 ─────────────────────────────────────────
function update(){
  isoLayers.forEach(l=>map.removeLayer(l));
  lmLayers.forEach(l=>map.removeLayer(l));
  isoLayers = []; lmLayers = [];
  if(lyMarker) map.removeLayer(lyMarker);

  const pidx = parseInt(document.getElementById('sel-point').value);
  const tidx = parseInt(document.getElementById('sl-time').value);
  const sidx = parseInt(document.getElementById('sl-speed').value);
  const tmin = TIMES[tidx];
  const selG = GROUPS[sidx];

  document.getElementById('lbl-time').textContent  = tmin + '분';
  document.getElementById('lbl-speed').textContent = selG.short;

  const pt  = POINTS[pidx];
  const pid = pt.id;
  document.getElementById('pt-name').textContent = pt.name;
  document.getElementById('pt-desc').textContent = pt.desc;
  document.getElementById('panel-title').textContent = `그룹별 도달 면적 · ${pt.name} · ${tmin}분`;

  const aRef = AREAS[pid][GROUPS[0].id][String(tmin)];

  // ── 등시선 레이어 ──
  // 1. 잃어버린 영역 (일반인 polygon 황금 배경)
  isoLayers.push(drawPoly(ISOS[pid][GROUPS[0].id][String(tmin)],
    {color:'#d29922',weight:0,fillColor:'rgba(210,153,34,0.50)',fillOpacity:1},
    `🟡 잃어버린 영역 · ${(aRef - AREAS[pid][selG.id][String(tmin)]).toFixed(2)} km²`
  ));

  // 2. 세 등시선 (g0→g1→g2 순으로 덮어씌움)
  GROUPS.forEach((grp,i)=>{
    const isHi  = (i===sidx);
    const geo   = ISOS[pid][grp.id][String(tmin)];
    const fill  = isHi
      ? `rgba(${i===0?'66,148,245':i===1?'255,165,0':'248,81,73'},${grp.hiOp})`
      : `rgba(${i===0?'66,148,245':i===1?'255,165,0':'248,81,73'},${grp.loOp})`;
    const bdr   = isHi ? grp.border : grp.borderDim;
    const wt    = isHi ? 2.5 : 0.8;
    const a     = AREAS[pid][grp.id][String(tmin)];
    isoLayers.push(drawPoly(geo,
      {color:bdr,weight:wt,fillColor:fill,fillOpacity:1,opacity:0.95},
      `${isHi?'★ ':''}<b>${grp.label}</b><br>${tmin}분 도달: ${a.toFixed(2)} km²`
    ));
  });

  // ── 랜드마크 마커 ──
  const lms    = LMS[pid] || [];
  const rfdata = (REACH[pid]||{})[String(tmin)] || {};

  lms.forEach((lm, li)=>{
    const flags  = rfdata[String(li)] || [0,0,0];
    const allOk  = flags[0]&&flags[1]&&flags[2];
    const anyOk  = flags[0]||flags[1]||flags[2];
    const noneOk = !anyOk;

    const dotColor = allOk ? '#00FF88' : anyOk ? '#FFD700' : '#666666';
    const icon = L.divIcon({
      html: `<div style="
               width:14px;height:14px;border-radius:50%;
               background:${dotColor};border:2px solid #000;
               box-shadow:0 0 4px ${dotColor}88;
               display:flex;align-items:center;justify-content:center;
               font-size:8px;"></div>`,
      iconSize:[14,14], iconAnchor:[7,7]
    });

    const g0ok = flags[0]?'✅':'❌';
    const g1ok = flags[1]?'✅':'❌';
    const g2ok = flags[2]?'✅':'❌';
    const tipHtml =
      `<b>${LM_TYPE_ICON[lm.type]||'📍'} ${lm.name}</b><br>` +
      `<span style="font-size:10px">` +
      `일반인 ${g0ok} · 65세+ ${g1ok} · 보조장치 ${g2ok}</span>`;

    const mk = L.marker([lm.lat, lm.lon], {icon})
      .bindTooltip(tipHtml, {sticky:true, opacity:0.95})
      .bindPopup(`<b>${LM_TYPE_ICON[lm.type]||'📍'} ${lm.name}</b><br>
        <small>일반인 ${g0ok} · 65세+ ${g1ok} · 보조장치 ${g2ok}</small>`);
    mk.addTo(map);
    lmLayers.push(mk);
  });

  // 출발점 마커
  lyMarker = L.marker([pt.lat,pt.lon],{
    icon:L.divIcon({
      html:`<div style="width:22px;height:22px;border-radius:50%;
              background:#fff;border:3px solid #388bfd;
              box-shadow:0 0 12px #388bfd99;
              display:flex;align-items:center;justify-content:center;
              font-size:10px">★</div>`,
      iconSize:[22,22],iconAnchor:[11,11]
    })
  }).bindPopup(`<b>${pt.name}</b><br><small>${pt.desc}</small>`);
  lyMarker.addTo(map);

  // ── 사이드 패널: 면적 카드 ──
  let cardsHTML='';
  GROUPS.forEach((grp,i)=>{
    const a    = AREAS[pid][grp.id][String(tmin)];
    const pct  = aRef>0?(a/aRef*100):0;
    const loss = aRef>0?((aRef-a)/aRef*100):0;
    const sel  = i===sidx;
    cardsHTML+=`
      <div class="acard" style="background:${grp.bg};border-color:${sel?grp.border:'transparent'}"
           onclick="setSpeed(${i})">
        <div class="top">
          <span class="lbl" style="color:${grp.border}">${sel?'▶ ':''}${grp.label}</span>
          <span class="km2" style="color:${grp.border}">${a.toFixed(2)} km²</span>
        </div>
        <div class="bt"><div class="bf" style="width:${pct.toFixed(1)}%;background:${grp.border}"></div></div>
        <div class="losslbl" style="color:#6e7681">
          ${i===0?'기준값':`−${(aRef-a).toFixed(2)} km² (<b style="color:${grp.border}">${loss.toFixed(1)}% 손실</b>)`}
        </div>
      </div>`;
  });
  document.getElementById('gcards').innerHTML = cardsHTML;

  // 요약
  const a1=AREAS[pid]['g1'][String(tmin)], a2=AREAS[pid]['g2'][String(tmin)];
  document.getElementById('sbox').innerHTML=`
    <div class="st">📉 격차 요약 (일반인 기준 · ${tmin}분)</div>
    <div class="sr"><span class="k">→ 65세 이상</span>
      <span class="v" style="color:#ffa500">−${(aRef-a1).toFixed(2)} km² (${((aRef-a1)/aRef*100).toFixed(1)}%)</span></div>
    <div class="sr"><span class="k">→ 보조장치</span>
      <span class="v" style="color:#f85149">−${(aRef-a2).toFixed(2)} km² (${((aRef-a2)/aRef*100).toFixed(1)}%)</span></div>
    <div class="sr"><span class="k">65세+ 대비 보조장치</span>
      <span class="v" style="color:#f85149">−${(a1-a2).toFixed(2)} km² 추가</span></div>
  `;

  // ── 사이드 패널: 랜드마크 목록 ──
  let lmHTML='';
  lms.forEach((lm,li)=>{
    const flags  = rfdata[String(li)]||[0,0,0];
    const allOk  = flags[0]&&flags[1]&&flags[2];
    const dotC   = allOk?'#00FF88': flags[0]?'#FFD700':'#555';
    const icon   = LM_TYPE_ICON[lm.type]||'📍';
    lmHTML+=`
      <div class="lm-row">
        <div class="lm-dot" style="background:${dotC}"></div>
        <span class="lm-name">${icon} ${lm.name}</span>
        <div class="lm-flags">
          <span class="lm-flag ${flags[0]?'lm-ok':'lm-no'}">일반</span>
          <span class="lm-flag ${flags[1]?'lm-ok':'lm-no'}">65+</span>
          <span class="lm-flag ${flags[2]?'lm-ok':'lm-no'}">보조</span>
        </div>
      </div>`;
  });
  document.getElementById('lm-list').innerHTML = lmHTML || '<div style="color:#6e7681;font-size:11px">데이터 없음</div>';

  map.flyTo([pt.lat,pt.lon],13,{duration:0.6});
}

function setSpeed(i){
  document.getElementById('sl-speed').value=i;
  update();
}

update();
</script>
</body>
</html>
"""

def build_html(iso_data, area_data, reach_data):
    opts = "\n".join(
        f'<option value="{i}">{p["name"]}</option>'
        for i, p in enumerate(POINTS)
    )
    pt_js = json.dumps(
        [{"id": p["id"], "name": p["name"], "desc": p["desc"],
          "lon": p["lon"], "lat": p["lat"]} for p in POINTS],
        ensure_ascii=False
    )
    # 랜드마크 JS 데이터
    lm_js = json.dumps(
        {pid: [{"name": lm[0], "lon": lm[1], "lat": lm[2], "type": lm[3]}
               for lm in lms]
         for pid, lms in LANDMARKS.items()},
        ensure_ascii=False
    )
    html = HTML
    html = html.replace("__POINT_OPTS__", opts)
    html = html.replace("__ISO_DATA__",   json.dumps(iso_data,   ensure_ascii=False))
    html = html.replace("__AREA_DATA__",  json.dumps(area_data,  ensure_ascii=False))
    html = html.replace("__REACH_DATA__", json.dumps(reach_data, ensure_ascii=False))
    html = html.replace("__POINT_DATA__", pt_js)
    html = html.replace("__LM_DATA__",    lm_js)
    return html


# ── main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if CACHE_FILE.exists():
        logger.info("캐시 로드: %s", CACHE_FILE)
        with open(CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
        iso_data   = cached["iso"]
        area_data  = cached["area"]
        reach_data = cached.get("reach", {})
        # 캐시에 reach 없으면 재계산
        if not reach_data:
            logger.info("reach_data 없음 → 그래프 재로드하여 계산")
            G_dir = ox.load_graphml(str(GRAPH_PATH))
            G     = ox.convert.to_undirected(G_dir)
            iso_data, area_data, reach_data = compute_all(G)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"iso": iso_data, "area": area_data, "reach": reach_data},
                          f, ensure_ascii=False)
    else:
        logger.info("그래프 로드: %s", GRAPH_PATH)
        G_dir = ox.load_graphml(str(GRAPH_PATH))
        G     = ox.convert.to_undirected(G_dir)
        logger.info("노드: %d  엣지: %d", G.number_of_nodes(), G.number_of_edges())
        iso_data, area_data, reach_data = compute_all(G)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"iso": iso_data, "area": area_data, "reach": reach_data},
                      f, ensure_ascii=False)
        logger.info("캐시 저장: %s", CACHE_FILE)

    html = build_html(iso_data, area_data, reach_data)
    out  = OUTPUT_DIR / "05_a1_dual_isochrone_260420.html"
    out.write_text(html, encoding="utf-8")
    logger.info("저장: %s", out)
    print(f"\n✅ 출력 → {out}")
    print(f"   파일 크기: {out.stat().st_size / 1024:.0f} KB")
