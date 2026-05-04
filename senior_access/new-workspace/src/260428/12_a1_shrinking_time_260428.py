"""
12_a1_shrinking_time_260428.py
'수축하는 시간' — 보행속도별 30분 도달권 애니메이션

4개 속도 그룹 (지시서 표준):
  g0: 1.28 m/s  일반인
  g1: 1.12 m/s  일반 노인
  g2: 0.88 m/s  보행보조 노인
  g3: 0.70 m/s  보행보조 노인 하위 15%

g0~g2는 260420 캐시(isochrones_a1_260420.json) 재활용.
g3만 신규 계산 후 260428 캐시에 저장.

애니메이션 방식:
  4개 GeoJSON 레이어를 순서대로 cross-fade (requestAnimationFrame)
  blue(1.28) → teal(1.12) → orange(0.88) → red(0.70) → loop

출력: 12_a1_shrinking_time_260428.html
"""

import json, logging, warnings
from pathlib import Path

import networkx as nx
import geopandas as gpd
import osmnx as ox
import shapely
from shapely.geometry import MultiPoint, Point
from shapely.ops import transform as shp_transform
import pyproj

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
log = logging.getLogger(__name__)

BASE     = Path("/Users/mtsaurus/Projects/seoul-2026-bigdata")
WS       = BASE / "senior_access/new-workspace"
GRAPH    = WS / "cache/seoul_walk_full.graphml"
SRC_CACHE = WS / "cache/260420/isochrones_a1_260420.json"
NEW_CACHE = WS / "cache/260428/isochrones_anim_260428.json"
OUT_DIR  = WS / "outputs/260428"
OUT_DIR.mkdir(exist_ok=True)

# ── 5개 출발지 (260420과 동일) ────────────────────────────────────────────────
POINTS = [
    {"id": "p0", "name": "종로 탑골공원",   "lon": 126.9901, "lat": 37.5720, "desc": "도심 · 인프라 집중"},
    {"id": "p1", "name": "강북구 미아역",   "lon": 127.0263, "lat": 37.6163, "desc": "동북권 · 경사·골목"},
    {"id": "p2", "name": "관악구 신림동",   "lon": 126.9194, "lat": 37.4837, "desc": "서남권 · 급경사"},
    {"id": "p3", "name": "강남구 삼성역",   "lon": 127.0627, "lat": 37.5088, "desc": "동남권 · 평지·신도시"},
    {"id": "p4", "name": "송파구 잠실새내", "lon": 127.0839, "lat": 37.5115, "desc": "대규모 아파트 단지"},
]

TIMES   = [15, 30, 45]
SPEEDS  = [
    {"id": "g0", "mps": 1.28, "label": "일반인",          "full": "일반인 (1.28 m/s)",        "color": "#4285F4"},
    {"id": "g1", "mps": 1.12, "label": "일반 노인",        "full": "일반 노인 (1.12 m/s)",      "color": "#34A853"},
    {"id": "g2", "mps": 0.88, "label": "보행보조 노인",    "full": "보행보조 노인 (0.88 m/s)",  "color": "#FF8F00"},
    {"id": "g3", "mps": 0.70, "label": "보행보조 하위 15%","full": "보행보조 하위 15% (0.70 m/s)","color": "#C62828"},
]


def compute_iso(G, node, speed_mps, time_min):
    cutoff = time_min * 60 * speed_mps
    lengths = nx.single_source_dijkstra_path_length(
        G, node, cutoff=cutoff,
        weight=lambda u, v, d: min(dd.get("length", 1.0) / speed_mps for dd in d.values())
    )
    nodes = [nid for nid in lengths]
    if len(nodes) < 3:
        return None
    proj = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
    inv  = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform
    pts_proj = [shp_transform(proj, Point(G.nodes[n]["x"], G.nodes[n]["y"])) for n in nodes]
    hull = MultiPoint(pts_proj).convex_hull
    hull_wgs = shp_transform(inv, hull)
    return json.dumps(hull_wgs.__geo_interface__, separators=(",", ":"))


# ── 캐시 로드 또는 생성 ────────────────────────────────────────────────────────
if NEW_CACHE.exists():
    log.info("캐시 로드: isochrones_anim_260428.json")
    with open(NEW_CACHE) as f:
        cache = json.load(f)
else:
    # 4개 속도 전부 convex_hull 방식으로 통일 계산
    log.info("그래프 로드 중 (188 MB)...")
    G = ox.load_graphml(GRAPH)
    log.info(f"  노드 {len(G.nodes):,}개 로드 완료")

    cache = {"iso": {}, "area": {}}
    for p in POINTS:
        pid = p["id"]
        node = ox.distance.nearest_nodes(G, p["lon"], p["lat"])
        cache["iso"][pid]  = {}
        cache["area"][pid] = {}
        for s in SPEEDS:
            gid = s["id"]
            cache["iso"][pid][gid]  = {}
            cache["area"][pid][gid] = {}
            for t in TIMES:
                log.info(f"  {p['name']} · {s['mps']} m/s · {t}분")
                geojson = compute_iso(G, node, s["mps"], t)
                if geojson:
                    geo_dict = json.loads(geojson)
                    cache["iso"][pid][gid][str(t)] = geo_dict
                    from shapely.geometry import shape
                    geom = shape(geo_dict)
                    area_km2 = round(
                        gpd.GeoSeries([geom], crs="EPSG:4326")
                        .to_crs("EPSG:5186").area.iloc[0] / 1e6, 4
                    )
                else:
                    cache["iso"][pid][gid][str(t)] = None
                    area_km2 = 0.0
                cache["area"][pid][gid][str(t)] = area_km2

    with open(NEW_CACHE, "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    log.info(f"캐시 저장 → {NEW_CACHE}")

# ── HTML 데이터 준비 ───────────────────────────────────────────────────────────
iso_js   = json.dumps(cache["iso"],  ensure_ascii=False, separators=(",", ":"))
area_js  = json.dumps(cache["area"], ensure_ascii=False, separators=(",", ":"))
pts_js   = json.dumps(POINTS,  ensure_ascii=False)
spds_js  = json.dumps(SPEEDS,  ensure_ascii=False)

# ── HTML 생성 ──────────────────────────────────────────────────────────────────
log.info("HTML 생성 중...")

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>수축하는 시간 — 서울 보행 도달권</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;
  font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif}}
body{{background:#060e1a;color:#dde6f0;height:100vh;
     display:flex;flex-direction:column;overflow:hidden}}

/* ── 헤더 ── */
#hdr{{
  background:#06111e;border-bottom:1px solid #1a2c3e;
  padding:10px 18px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;
  flex-shrink:0;
}}
#hdr-title{{
  display:flex;flex-direction:column;
}}
#hdr h1{{font-size:.95rem;font-weight:700;color:#fff;line-height:1.2}}
#hdr .tagline{{font-size:.68rem;color:#6b8099;margin-top:2px}}

/* ── 컨트롤 바 ── */
#ctrl-bar{{
  background:#080f1c;border-bottom:1px solid #1a2c3e;
  padding:8px 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  flex-shrink:0;
}}
.ctrl-group{{display:flex;align-items:center;gap:6px}}
.ctrl-label{{font-size:.68rem;color:#6b8099;white-space:nowrap}}

select{{
  background:#0d1e30;color:#c9d9e8;border:1px solid #243548;
  border-radius:5px;padding:4px 8px;font-size:.75rem;cursor:pointer;
}}
select:focus{{outline:none;border-color:#3b82f6}}

.pill-group{{display:flex;gap:3px}}
.pill{{
  padding:3px 10px;border-radius:999px;font-size:.7rem;cursor:pointer;
  border:1px solid #243548;background:#0d1e30;color:#8fa3b8;transition:.15s;
}}
.pill.active{{border-color:currentColor;color:#fff;
  background:color-mix(in srgb,currentColor 20%,transparent)}}
.pill:hover:not(.active){{background:#172030}}

/* ── 재생 컨트롤 ── */
#play-btn{{
  width:34px;height:34px;border-radius:50%;
  border:2px solid #3b82f6;background:rgba(59,130,246,.15);
  color:#3b82f6;font-size:1rem;cursor:pointer;display:flex;
  align-items:center;justify-content:center;transition:.15s;flex-shrink:0;
}}
#play-btn:hover{{background:rgba(59,130,246,.3)}}
#play-btn.playing{{border-color:#34A853;color:#34A853;background:rgba(52,168,83,.15)}}

.speed-btns{{display:flex;gap:3px}}
.sp-btn{{
  padding:3px 8px;border-radius:4px;font-size:.68rem;cursor:pointer;
  border:1px solid #243548;background:#0d1e30;color:#8fa3b8;transition:.15s;
}}
.sp-btn.active{{background:#1a3a5c;border-color:#3b82f6;color:#fff}}

/* ── 지도 ── */
#map{{position:absolute;inset:0}}

/* ── 진행 바 ── */
#progress-bar{{
  position:absolute;bottom:0;left:0;right:0;height:3px;
  background:#0d1e30;z-index:500;
}}
#progress-fill{{
  height:100%;width:0;transition:width .1s linear;
}}

/* ── 사이드 패널 ── */
#panel{{
  position:absolute;top:10px;right:12px;z-index:1000;
  background:rgba(6,14,26,.93);border:1px solid #1a2c3e;
  border-radius:10px;padding:14px;width:220px;
  backdrop-filter:blur(8px);
}}

/* ── 속도 인디케이터 ── */
#speed-indicator{{
  display:flex;flex-direction:column;gap:6px;margin-bottom:12px;
}}
.speed-row{{
  display:flex;align-items:center;gap:8px;
  padding:6px 9px;border-radius:7px;border:1px solid transparent;
  transition:all .3s;opacity:.38;cursor:pointer;
}}
.speed-row.active{{opacity:1;border-color:var(--clr);
  background:color-mix(in srgb,var(--clr) 12%,transparent)}}
.speed-dot{{
  width:11px;height:11px;border-radius:50%;flex-shrink:0;
  background:var(--clr);transition:transform .3s;
}}
.speed-row.active .speed-dot{{transform:scale(1.35)}}
.speed-name{{font-size:.72rem;color:#c9d9e8;line-height:1.2}}
.speed-mps{{font-size:.62rem;color:#6b8099}}

/* ── 면적 통계 ── */
#area-stat{{
  border-top:1px solid #1a2c3e;padding-top:10px;
}}
.stat-row{{
  display:flex;justify-content:space-between;align-items:baseline;
  margin-bottom:4px;font-size:.72rem;
}}
.stat-label{{color:#6b8099}}
.stat-val{{color:#fff;font-weight:700}}
.stat-sub{{font-size:.62rem;color:#8fa3b8}}

/* ── 손실 바 ── */
#loss-bar-wrap{{margin-top:8px}}
.loss-label{{font-size:.62rem;color:#6b8099;margin-bottom:3px}}
#loss-bar-bg{{
  background:#0d1e30;border-radius:999px;height:6px;overflow:hidden;
}}
#loss-bar-fill{{
  height:100%;border-radius:999px;transition:width .4s ease,background .4s;
}}
#loss-text{{font-size:.62rem;color:#8fa3b8;margin-top:3px;text-align:right}}

/* ── 타일 스위처 ── */
.tile-btns{{display:flex;gap:3px;margin-left:auto}}
.tile-btn{{
  padding:3px 8px;border-radius:4px;font-size:.68rem;cursor:pointer;
  border:1px solid #243548;background:#0d1e30;color:#8fa3b8;transition:.15s;
}}
.tile-btn.active{{background:#1a3a5c;border-color:#3b82f6;color:#fff}}
</style>
</head>
<body>

<div id="hdr">
  <div id="hdr-title">
    <h1>⏳ 수축하는 시간</h1>
    <div class="tagline">같은 30분, 다른 서울 — 보행속도에 따라 줄어드는 도달권</div>
  </div>
</div>

<div id="ctrl-bar">
  <!-- 재생 -->
  <button id="play-btn" onclick="togglePlay()" title="재생/일시정지">▶</button>
  <div class="ctrl-group">
    <span class="ctrl-label">배속</span>
    <div class="speed-btns">
      <button class="sp-btn" onclick="setPlaySpeed(2000,this)">0.5×</button>
      <button class="sp-btn active" onclick="setPlaySpeed(1200,this)">1×</button>
      <button class="sp-btn" onclick="setPlaySpeed(600,this)">2×</button>
    </div>
  </div>

  <!-- 출발지 -->
  <div class="ctrl-group">
    <span class="ctrl-label">출발지</span>
    <select id="sel-pt" onchange="onPtChange()">
    </select>
  </div>

  <!-- 시간 -->
  <div class="ctrl-group">
    <span class="ctrl-label">기준 시간</span>
    <div class="pill-group" id="time-pills">
      <button class="pill" style="color:#6b8099" onclick="setTime(15,this)">15분</button>
      <button class="pill active" style="color:#3b82f6" onclick="setTime(30,this)">30분</button>
      <button class="pill" style="color:#6b8099" onclick="setTime(45,this)">45분</button>
    </div>
  </div>

  <!-- 타일 -->
  <div class="tile-btns" style="margin-left:auto">
    <button class="tile-btn active" onclick="setTile('osm',this)">일반</button>
    <button class="tile-btn" onclick="setTile('esri',this)">위성</button>
    <button class="tile-btn" onclick="setTile('dark',this)">Dark</button>
  </div>
</div>

<div style="position:relative;flex:1;min-height:0">
  <div id="map"></div>
  <div id="progress-bar"><div id="progress-fill"></div></div>

  <div id="panel">
    <div id="speed-indicator"></div>
    <div id="area-stat">
      <div class="stat-row">
        <span class="stat-label">현재 도달 면적</span>
        <span class="stat-val"><span id="val-area">—</span> km²</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">일반인 대비</span>
        <span class="stat-val"><span id="val-ratio">—</span>%</span>
      </div>
      <div id="loss-bar-wrap">
        <div class="loss-label">면적 유지율</div>
        <div id="loss-bar-bg"><div id="loss-bar-fill"></div></div>
        <div id="loss-text"></div>
      </div>
    </div>
  </div>
</div>

<script>
const ISO   = {iso_js};
const AREAS = {area_js};
const PTS   = {pts_js};
const SPDS  = {spds_js};

// ── 지도 초기화 ────────────────────────────────────────────────────────
const map = L.map('map', {{center:[37.5500,126.9780], zoom:12, zoomControl:true}});
const TILES = {{
  osm:  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          {{attribution:'© OpenStreetMap',maxZoom:19}}),
  esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
          {{attribution:'© Esri',maxZoom:19}}),
  dark: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_nolabels/{{z}}/{{x}}/{{y}}{{r}}.png',
          {{attribution:'© CartoDB',maxZoom:19}}),
}};
let curTile = 'osm'; TILES.osm.addTo(map);

function setTile(k, btn) {{
  map.removeLayer(TILES[curTile]); TILES[k].addTo(map); curTile = k;
  document.querySelectorAll('.tile-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}}

// ── 출발지 셀렉트 초기화 ────────────────────────────────────────────────
const sel = document.getElementById('sel-pt');
PTS.forEach(p => {{
  const opt = document.createElement('option');
  opt.value = p.id; opt.textContent = p.name; sel.appendChild(opt);
}});

// ── 속도 인디케이터 렌더 ────────────────────────────────────────────────
const indEl = document.getElementById('speed-indicator');
SPDS.forEach((s, i) => {{
  const div = document.createElement('div');
  div.className = 'speed-row';
  div.id = 'srow-' + s.id;
  div.style.setProperty('--clr', s.color);
  div.innerHTML = `<div class="speed-dot"></div>
    <div><div class="speed-name">${{s.label}}</div>
    <div class="speed-mps">${{s.mps}} m/s · 30분 ${{(s.mps*30*60/1000).toFixed(2)}}km</div></div>`;
  div.onclick = () => jumpTo(i);
  indEl.appendChild(div);
}});

// ── 출발지 마커 ──────────────────────────────────────────────────────────
let ptMarker = null;
function placePtMarker(p) {{
  if (ptMarker) map.removeLayer(ptMarker);
  ptMarker = L.circleMarker([p.lat, p.lon], {{
    radius: 7, fillColor: '#fff', fillOpacity: 1,
    color: '#4285F4', weight: 2.5
  }}).bindTooltip(p.name + '<br>' + p.desc, {{permanent: false}}).addTo(map);
  map.setView([p.lat, p.lon], 12, {{animate: true, duration: 0.5}});
}}

// ── 상태 ──────────────────────────────────────────────────────────────
let curPt    = 'p0';
let curTime  = 30;
let curFrame = 0;          // 0~3
let isPlaying= false;
let frameDur = 1200;       // ms per frame (hold duration)
let fadeDur  = 400;        // ms cross-fade
let animRaf  = null;
let holdTimer= null;

// ── GeoJSON 레이어 관리 ────────────────────────────────────────────────
let layers = [null, null, null, null];  // 4 speed layers

function buildLayers() {{
  layers.forEach(l => {{ if(l) map.removeLayer(l); }});
  layers = SPDS.map((s, i) => {{
    const geojson = ISO[curPt]?.[s.id]?.[String(curTime)];
    if (!geojson) return null;
    return L.geoJSON(geojson, {{
      style: {{
        fillColor: s.color,
        fillOpacity: 0,
        color: s.color,
        weight: 1.5,
        opacity: 0,
      }}
    }});
  }});
}}

// ── 크로스페이드 ──────────────────────────────────────────────────────
function setLayerOpacity(layer, fill, stroke) {{
  if (!layer) return;
  layer.setStyle({{fillOpacity: fill, opacity: stroke}});
}}

function showFrame(idx, instant) {{
  const FILL = 0.55, STROKE = 0.75;
  if (instant) {{
    layers.forEach((l, i) => {{
      if (!l) return;
      if (i !== idx) {{ map.removeLayer(l); }}
      else {{ l.addTo(map); setLayerOpacity(l, FILL, STROKE); }}
    }});
    updateUI(idx);
    return;
  }}
  // cross-fade: fade out previous, fade in next
  const prev = layers[((idx - 1) % 4 + 4) % 4];
  const next = layers[idx];
  if (next) next.addTo(map);

  let start = null;
  function step(ts) {{
    if (!start) start = ts;
    const t = Math.min((ts - start) / fadeDur, 1);
    if (prev && prev !== next) setLayerOpacity(prev, FILL*(1-t), STROKE*(1-t));
    if (next) setLayerOpacity(next, FILL*t, STROKE*t);
    if (t < 1) {{ animRaf = requestAnimationFrame(step); }}
    else {{
      if (prev && prev !== next) map.removeLayer(prev);
      updateUI(idx);
      if (isPlaying) scheduleNext();
    }}
  }}
  if (animRaf) cancelAnimationFrame(animRaf);
  animRaf = requestAnimationFrame(step);
}}

function scheduleNext() {{
  if (holdTimer) clearTimeout(holdTimer);
  holdTimer = setTimeout(() => {{
    curFrame = (curFrame + 1) % 4;
    showFrame(curFrame, false);
    updateProgress();
  }}, frameDur);
}}

// ── UI 업데이트 ───────────────────────────────────────────────────────
function updateUI(idx) {{
  // 속도 행 하이라이트
  SPDS.forEach((s, i) => {{
    document.getElementById('srow-'+s.id)?.classList.toggle('active', i === idx);
  }});

  // 면적 통계
  const area0 = AREAS[curPt]?.['g0']?.[String(curTime)] ?? 0;
  const areaI = AREAS[curPt]?.[SPDS[idx].id]?.[String(curTime)] ?? 0;
  const ratio = area0 > 0 ? Math.round(areaI / area0 * 100) : 0;

  document.getElementById('val-area').textContent = areaI.toFixed(2);
  document.getElementById('val-ratio').textContent = ratio;

  const fill = document.getElementById('loss-bar-fill');
  fill.style.width = ratio + '%';
  fill.style.background = SPDS[idx].color;

  const lost = 100 - ratio;
  document.getElementById('loss-text').textContent =
    idx === 0 ? '기준값 (100%)' : `일반인 대비 ${{lost}}% 면적 상실`;
}}

function updateProgress() {{
  const pct = ((curFrame + 1) / 4) * 100;
  const fill = document.getElementById('progress-fill');
  fill.style.width = pct + '%';
  fill.style.background = SPDS[curFrame].color;
}}

// ── 재생 제어 ────────────────────────────────────────────────────────
function togglePlay() {{
  isPlaying = !isPlaying;
  const btn = document.getElementById('play-btn');
  btn.textContent = isPlaying ? '⏸' : '▶';
  btn.classList.toggle('playing', isPlaying);
  if (isPlaying) scheduleNext();
  else {{
    if (holdTimer) clearTimeout(holdTimer);
    if (animRaf)   cancelAnimationFrame(animRaf);
  }}
}}

function setPlaySpeed(ms, btn) {{
  frameDur = ms;
  document.querySelectorAll('.sp-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}}

function jumpTo(idx) {{
  if (holdTimer) clearTimeout(holdTimer);
  if (animRaf)   cancelAnimationFrame(animRaf);
  curFrame = idx;
  showFrame(idx, true);
  updateProgress();
  if (isPlaying) scheduleNext();
}}

// ── 출발지 / 시간 변경 ──────────────────────────────────────────────
function onPtChange() {{
  curPt = document.getElementById('sel-pt').value;
  const p = PTS.find(x=>x.id===curPt);
  placePtMarker(p);
  rebuild();
}}

function setTime(t, btn) {{
  curTime = t;
  document.querySelectorAll('.pill').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  rebuild();
}}

function rebuild() {{
  if (holdTimer) clearTimeout(holdTimer);
  if (animRaf)   cancelAnimationFrame(animRaf);
  buildLayers();
  showFrame(curFrame, true);
  updateProgress();
  if (isPlaying) scheduleNext();
}}

// ── 초기 실행 ────────────────────────────────────────────────────────
placePtMarker(PTS[0]);
buildLayers();
showFrame(0, true);
updateProgress();
</script>
</body>
</html>"""

out_path = OUT_DIR / "12_a1_shrinking_time_260428.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
log.info(f"✅ 출력 → {out_path}")
log.info(f"   파일 크기: {out_path.stat().st_size // 1024} KB")
