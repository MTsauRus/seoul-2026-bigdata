"""
06_seoul_loss_map.py
--------------------
서울 전체 426개 행정동의 30분 보행 손실률 코로플레스 지도.

각 동 중심점에서 일반인(1.28 m/s) vs 보행보조장치(0.88 m/s) 30분
도달 가능 노드 수를 비교하여 손실률 계산.

  손실률(%) = (1 - 보조장치 도달 노드 수 / 일반인 도달 노드 수) × 100

노드 수는 도달 면적의 프록시 (그래프 밀도 균일 가정).
멀티프로세싱으로 병렬 계산 — 예상 소요 5~10분.

출력:
  ../cache/dong_loss_ratio.csv   중간 결과 캐시 (재실행 시 생략)
  ../outputs/06_seoul_loss_map.html
"""

import logging
import warnings
import multiprocessing as mp
import json
import sys
from pathlib import Path

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── 경로 (모듈 수준) ──────────────────────────────────────
WORKSPACE    = Path(__file__).resolve().parents[1]
SENIOR_ROOT  = WORKSPACE.parents[0]          # senior_access/
GRAPH_PATH   = WORKSPACE / "cache" / "seoul_walk_full.graphml"
SHP_PATH     = SENIOR_ROOT / "data" / "raw" / "BND_ADM_DONG_PG" / "BND_ADM_DONG_PG.shp"
OUTPUT_DIR = WORKSPACE / "outputs"
CACHE_CSV  = WORKSPACE / "cache" / "dong_loss_ratio.csv"

SPEED_YOUNG = 1.28
SPEED_AID   = 0.88
CUTOFF_SEC  = 30 * 60   # 30분

# 서울 구 코드 → 구 이름 매핑
GU_CODE_MAP = {
    "11010": "종로구", "11020": "중구",   "11030": "용산구",
    "11040": "성동구", "11050": "광진구", "11060": "동대문구",
    "11070": "중랑구", "11080": "성북구", "11090": "강북구",
    "11100": "도봉구", "11110": "노원구", "11120": "은평구",
    "11130": "서대문구","11140": "마포구", "11150": "양천구",
    "11160": "강서구", "11170": "구로구", "11180": "금천구",
    "11190": "영등포구","11200": "동작구", "11210": "관악구",
    "11220": "서초구", "11230": "강남구", "11240": "송파구",
    "11250": "강동구",
}

# ── worker 전용 전역 그래프 ───────────────────────────────
_G = None

def _init_worker(graph_path_str: str):
    """각 worker 프로세스 초기화: 그래프 1회 로드"""
    global _G
    import osmnx as ox
    _G = ox.convert.to_undirected(ox.load_graphml(graph_path_str))


# weight 함수: 모듈 수준에 정의해야 pickle 가능
def _wt_young(u, v, d):
    vals = d.values() if isinstance(d, dict) else [d]
    return min(dd.get("length", 1.0) / SPEED_YOUNG for dd in vals)

def _wt_aid(u, v, d):
    vals = d.values() if isinstance(d, dict) else [d]
    return min(dd.get("length", 1.0) / SPEED_AID for dd in vals)


def _compute_loss(args):
    """(dong_code, dong_name, gu_name, lon, lat) → (dong_code, n_young, n_aid, loss_pct)"""
    import networkx as nx
    import osmnx as ox
    global _G

    dong_code, dong_name, gu_name, lon, lat = args
    try:
        node = ox.distance.nearest_nodes(_G, lon, lat)

        young = nx.single_source_dijkstra_path_length(
            _G, node, cutoff=CUTOFF_SEC, weight=_wt_young
        )
        aid = nx.single_source_dijkstra_path_length(
            _G, node, cutoff=CUTOFF_SEC, weight=_wt_aid
        )

        n_young = len(young)
        n_aid   = len(aid)
        loss    = round((1 - n_aid / n_young) * 100, 2) if n_young > 0 else 0.0
        return (dong_code, dong_name, gu_name, lon, lat, n_young, n_aid, loss)
    except Exception as e:
        return (dong_code, dong_name, gu_name, lon, lat, 0, 0, 0.0)


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import geopandas as gpd
    import pandas as pd
    import numpy as np
    import folium
    import branca.colormap as cm

    OUTPUT_DIR.mkdir(exist_ok=True)

    # ── 1. 행정동 shapefile 로드 ──────────────────────────
    logger.info("행정동 경계 로드: %s", SHP_PATH)
    gdf_raw = gpd.read_file(str(SHP_PATH))
    logger.info("전체: %d행, CRS: %s", len(gdf_raw), gdf_raw.crs)

    # 서울만 필터 (ADM_CD 앞 2자리 = '11')
    gdf = gdf_raw[gdf_raw["ADM_CD"].astype(str).str.startswith("11")].copy()
    logger.info("서울 행정동: %d개", len(gdf))

    # WGS84 변환
    gdf = gdf.to_crs("EPSG:4326")

    # 구 이름 추가 (ADM_CD 앞 5자리)
    gdf["gu_code"]   = gdf["ADM_CD"].astype(str).str[:5]
    gdf["gu_name"]   = gdf["gu_code"].map(GU_CODE_MAP).fillna("")
    gdf["full_name"] = gdf["gu_name"] + " " + gdf["ADM_NM"]

    # 중심점
    gdf["cx"] = gdf.geometry.centroid.x
    gdf["cy"] = gdf.geometry.centroid.y

    tasks = [
        (str(row["ADM_CD"]), str(row["ADM_NM"]), str(row["gu_name"]),
         row["cx"], row["cy"])
        for _, row in gdf.iterrows()
    ]
    logger.info("총 %d개 동 계산 예정", len(tasks))

    # ── 2. 캐시 확인 ─────────────────────────────────────
    if CACHE_CSV.exists():
        logger.info("캐시 발견 — 로드: %s", CACHE_CSV)
        df_loss = pd.read_csv(CACHE_CSV, dtype={"dong_code": str})
    else:
        # ── 3. 멀티프로세싱 계산 ─────────────────────────
        n_cpu     = mp.cpu_count()
        n_workers = min(n_cpu, 6)
        logger.info("멀티프로세싱: %d workers (CPU %d개)", n_workers, n_cpu)
        logger.info("예상 소요: 5~10분 (그래프 로드 + Dijkstra)")

        with mp.Pool(
            processes=n_workers,
            initializer=_init_worker,
            initargs=(str(GRAPH_PATH),),
        ) as pool:
            results = []
            total = len(tasks)
            for i, res in enumerate(
                pool.imap_unordered(_compute_loss, tasks, chunksize=5), 1
            ):
                results.append(res)
                if i % 30 == 0 or i == total:
                    logger.info(
                        "  진행: %d/%d (%.0f%%)", i, total, i / total * 100
                    )

        df_loss = pd.DataFrame(
            results,
            columns=["dong_code", "dong_name", "gu_name", "lon", "lat",
                     "n_young", "n_aid", "loss_pct"],
        )
        df_loss.to_csv(CACHE_CSV, index=False)
        logger.info("캐시 저장: %s", CACHE_CSV)

    # ── 4. 병합 ──────────────────────────────────────────
    gdf["dong_code"] = gdf["ADM_CD"].astype(str)
    gdf = gdf.merge(
        df_loss[["dong_code", "n_young", "n_aid", "loss_pct"]],
        on="dong_code", how="left",
    )
    gdf["loss_pct"] = gdf["loss_pct"].fillna(0).round(1)

    valid = gdf[gdf["n_young"] > 0]
    logger.info("\n=== 손실률 통계 (서울 %d개 동) ===", len(valid))
    logger.info("  평균: %.1f%%", valid["loss_pct"].mean())
    logger.info("  중앙값: %.1f%%", valid["loss_pct"].median())
    logger.info("  최대: %.1f%%  ← %s",
                valid["loss_pct"].max(),
                valid.loc[valid["loss_pct"].idxmax(), "full_name"])
    logger.info("  최소: %.1f%%  ← %s",
                valid["loss_pct"].min(),
                valid.loc[valid["loss_pct"].idxmin(), "full_name"])

    top10 = valid.nlargest(10, "loss_pct")[["full_name", "loss_pct"]]
    logger.info("\n상위 10개 동 (손실 큰 곳):")
    for _, r in top10.iterrows():
        logger.info("  %s: %.1f%%", r["full_name"], r["loss_pct"])

    # ── 5. Folium 지도 ────────────────────────────────────
    logger.info("Folium 지도 생성 중…")

    m = folium.Map(
        location=[37.5665, 126.9780],
        zoom_start=11,
        tiles=None,
        prefer_canvas=True,
    )

    # 타일 3종
    folium.TileLayer("OpenStreetMap",   name="🗺️ 일반 지도 (OSM)").add_to(m)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services"
            "/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="🛰️ 위성지도 (Esri)",
    ).add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="🌑 Dark Map").add_to(m)

    # 컬러맵: 연한 노랑 → 주황 → 진한 빨강
    p25 = float(np.percentile(valid["loss_pct"], 10))
    p75 = float(np.percentile(valid["loss_pct"], 90))
    colormap = cm.LinearColormap(
        colors=["#FFF5F0", "#FCBBA1", "#FC7050", "#D73027", "#67000D"],
        vmin=p25,
        vmax=p75,
        caption=f"30분 보행 손실률 (%) — 일반인 대비 보행보조장치",
    )

    # GeoJSON 직렬화 (필요한 컬럼만)
    gdf_out = gdf[["ADM_CD", "ADM_NM", "gu_name", "full_name",
                   "n_young", "n_aid", "loss_pct", "geometry"]].copy()
    geojson_data = json.loads(gdf_out.to_json())

    # 스타일 함수
    def style_fn(feature):
        loss = feature["properties"].get("loss_pct") or 0
        clipped = min(max(loss, p25), p75)
        return {
            "fillColor":   colormap(clipped),
            "color":       "rgba(80,80,80,0.4)",
            "weight":      0.6,
            "fillOpacity": 0.78,
        }

    def highlight_fn(feature):
        return {
            "fillOpacity": 0.95,
            "weight":      2,
            "color":       "#FFD700",
        }

    fg = folium.FeatureGroup(name="동별 30분 보행 손실률", show=True)
    folium.GeoJson(
        data=geojson_data,
        style_function=style_fn,
        highlight_function=highlight_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=["full_name", "loss_pct", "n_young", "n_aid"],
            aliases=["행정동", "손실률(%)", "일반인 도달 노드", "보조장치 도달 노드"],
            localize=True,
            sticky=True,
            style=(
                "font-family:'AppleGothic','Malgun Gothic',sans-serif;"
                "font-size:13px;"
            ),
        ),
        popup=folium.GeoJsonPopup(
            fields=["full_name", "loss_pct", "n_young", "n_aid"],
            aliases=["행정동", "손실률(%)", "일반인 도달", "보조장치 도달"],
        ),
    ).add_to(fg)
    fg.add_to(m)

    colormap.add_to(m)
    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # 상위 10개 동 마커 (손실 큰 곳)
    fg_top = folium.FeatureGroup(name="🔴 손실 상위 10개 동", show=True)
    for _, row in top10.iterrows():
        # dong_code → 좌표
        r2 = df_loss[df_loss["dong_code"] == row.get("dong_code",
             gdf.loc[gdf["full_name"] == row["full_name"], "dong_code"].values[0]
             if "dong_code" not in row else row["dong_code"])]
        if len(r2) == 0:
            matched = gdf[gdf["full_name"] == row["full_name"]]
            if matched.empty:
                continue
            cx = float(matched["cx"].values[0])
            cy = float(matched["cy"].values[0])
        else:
            cx = float(r2["lon"].values[0])
            cy = float(r2["lat"].values[0])

        folium.CircleMarker(
            location=[cy, cx],
            radius=7,
            color="#FF3300",
            weight=1.5,
            fill=True,
            fill_color="#FF3300",
            fill_opacity=0.85,
            tooltip=folium.Tooltip(
                f"<b>{row['full_name']}</b><br>손실률: {row['loss_pct']:.1f}%",
                sticky=True,
            ),
        ).add_to(fg_top)
    fg_top.add_to(m)

    # 타이틀
    mean_loss = valid["loss_pct"].mean()
    title_html = f"""
<div style="
    position:fixed; top:10px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(10,10,20,0.92);
    border:1px solid #444; border-radius:8px;
    padding:10px 28px; text-align:center;
    font-family:'AppleGothic','Malgun Gothic',sans-serif;
    box-shadow:0 2px 12px rgba(0,0,0,0.5);">
  <div style="font-size:17px;font-weight:bold;color:#fff;">
    서울시 동별 30분 보행 손실률
  </div>
  <div style="font-size:11px;color:#aaa;margin-top:3px;">
    일반인 (1.28 m/s) vs 보행보조장치 (0.88 m/s)  |
    서울 평균 손실: <b style="color:#FC7050">{mean_loss:.1f}%</b>  |
    진할수록 손실 큼
  </div>
</div>
"""
    m.get_root().html.add_child(folium.Element(title_html))

    out_path = OUTPUT_DIR / "06_seoul_loss_map.html"
    m.save(str(out_path))
    logger.info("저장 완료: %s", out_path)
    print(f"\n✅ 출력 → {out_path}")
    print(f"   서울 평균 손실률: {mean_loss:.1f}%")
