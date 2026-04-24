"""
01_medical_access.py  ·  D3 의료 도메인 분석
─────────────────────────────────────────────
청년(1.2 m/s) vs 노인(0.78 m/s) 보행속도 기준
30분 도달 가능 의료시설 수 차이를 서울 행정동 단위로 시각화.

핵심 질문: 노인이 만성질환 관리를 동네에서 할 수 있는가?
대상 시설: 의원·병원·보건소 + 약국

출력:
  ../outputs/01_medical_loss_map.html   ← 동별 손실률 코로플레스 (Folium)
  ../outputs/02_access_compare.html     ← 청년 vs 노인 접근 시설 수 산점도 (Plotly)
  ../outputs/03_top_bottom_dong.html    ← 상·하위 동 바차트 (Plotly)
"""

import warnings, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from pyproj import Transformer
import folium
import branca.colormap as cm
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

# ── 경로 ──────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[1]
DATA_DIR  = ROOT / "data"
OUT_DIR   = ROOT / "outputs"
PROJ_ROOT = ROOT.parent

SHP_PATH  = PROJ_ROOT / "prototype" / "끊어진서울(가제)" / "data" \
            / "bnd_oa_11_2025_2Q" / "bnd_oa_11_2025_2Q.shp"
HOSP_CSV  = DATA_DIR / "서울시 병의원 위치 정보.csv"
PHARM_CSV = DATA_DIR / "서울시 약국 인허가 정보.csv"
OUT_DIR.mkdir(exist_ok=True)

# ── 보행 속도·거리 파라미터 ─────────────────────────────────────
SPEED_YOUNG   = 1.20   # m/s  (청년 표준 보행속도)
SPEED_SENIOR  = 0.78   # m/s  (노인 보행속도, 문헌 기준)
CUTOFF_MIN    = 30
DIST_YOUNG    = SPEED_YOUNG  * CUTOFF_MIN * 60   # 2,160 m
DIST_SENIOR   = SPEED_SENIOR * CUTOFF_MIN * 60   # 1,404 m

# ── 구 코드 매핑 ──────────────────────────────────────────────────
GU_MAP = {
    "11010": "종로구", "11020": "중구",    "11030": "용산구",
    "11040": "성동구", "11050": "광진구",  "11060": "동대문구",
    "11070": "중랑구", "11080": "성북구",  "11090": "강북구",
    "11100": "도봉구", "11110": "노원구",  "11120": "은평구",
    "11130": "서대문구","11140": "마포구", "11150": "양천구",
    "11160": "강서구", "11170": "구로구",  "11180": "금천구",
    "11190": "영등포구","11200": "동작구", "11210": "관악구",
    "11220": "서초구", "11230": "강남구",  "11240": "송파구",
    "11250": "강동구",
}

print("=" * 60)
print("D3 의료 접근성 분석 시작")
print(f"  청년 30분 도달 거리: {DIST_YOUNG:.0f} m")
print(f"  노인 30분 도달 거리: {DIST_SENIOR:.0f} m")
print("=" * 60)

# ═══════════════════════════════════════════════════════════════
# 1. 행정동 경계 로드 (집계구 → 행정동 dissolve)
# ═══════════════════════════════════════════════════════════════
print("\n[1/5] 행정동 경계 로드 중…")
gdf_oa = gpd.read_file(str(SHP_PATH))           # EPSG:5179
gdf_dong = (
    gdf_oa.dissolve(by="ADM_CD", as_index=False)
           .rename(columns={"ADM_CD": "dong_code"})
)
gdf_dong["dong_code"] = gdf_dong["dong_code"].astype(str)
gdf_dong["gu_code"]   = gdf_dong["dong_code"].str[:5]
gdf_dong["gu_name"]   = gdf_dong["gu_code"].map(GU_MAP).fillna("")

# 동 이름은 ADM_CD 끝 3자리를 임시 이름으로 사용 (shapefile에 동명 없음)
# 실제 서비스 시 행정동 코드-이름 매핑 CSV 별도 필요
gdf_dong["dong_name"] = gdf_dong["dong_code"]
gdf_dong["full_name"] = gdf_dong["gu_name"] + " " + gdf_dong["dong_code"].str[-3:]
gdf_dong = gdf_dong.to_crs("EPSG:5179")

# 중심점 (투영 좌표계 기준)
gdf_dong["cx"] = gdf_dong.geometry.centroid.x
gdf_dong["cy"] = gdf_dong.geometry.centroid.y
print(f"  서울 행정동 {len(gdf_dong)}개 로드 완료")

# ═══════════════════════════════════════════════════════════════
# 2. 의료시설 로드 및 전처리
# ═══════════════════════════════════════════════════════════════
print("\n[2/5] 의료시설 데이터 로드 중…")

# 2-a. 병의원 (WGS84 → EPSG:5179)
hosp_raw = pd.read_csv(HOSP_CSV, encoding="cp949")
hosp = hosp_raw[
    hosp_raw["병원분류명"].isin(["의원", "병원", "보건소", "종합병원"])
].copy()
hosp = hosp.dropna(subset=["병원경도", "병원위도"])
hosp = hosp[(hosp["병원경도"] > 120) & (hosp["병원위도"] > 35)]

t_hosp = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
hosp["x5179"], hosp["y5179"] = t_hosp.transform(
    hosp["병원경도"].values, hosp["병원위도"].values
)
gdf_hosp = gpd.GeoDataFrame(
    hosp,
    geometry=gpd.points_from_xy(hosp["x5179"], hosp["y5179"]),
    crs="EPSG:5179",
)
print(f"  병의원(의원·병원·보건소): {len(gdf_hosp)}개")

# 2-b. 약국 (EPSG:5174 → EPSG:5179)
pharm_raw = pd.read_csv(PHARM_CSV, encoding="cp949")
pharm = pharm_raw[
    (pharm_raw["영업상태명"] == "영업/정상") &
    (pharm_raw["도로명주소"].str.startswith("서울", na=False))
].copy()
pharm["x"] = pd.to_numeric(pharm["좌표정보(X)"].astype(str).str.strip(), errors="coerce")
pharm["y"] = pd.to_numeric(pharm["좌표정보(Y)"].astype(str).str.strip(), errors="coerce")
pharm = pharm.dropna(subset=["x", "y"])
pharm = pharm[(pharm["x"] > 100000) & (pharm["y"] > 300000)]

t_ph = Transformer.from_crs("EPSG:5174", "EPSG:5179", always_xy=True)
pharm["x5179"], pharm["y5179"] = t_ph.transform(pharm["x"].values, pharm["y"].values)
gdf_pharm = gpd.GeoDataFrame(
    pharm,
    geometry=gpd.points_from_xy(pharm["x5179"], pharm["y5179"]),
    crs="EPSG:5179",
)
print(f"  약국(영업중): {len(gdf_pharm)}개")

# 2-c. 전체 시설 합치기
gdf_all = pd.concat([
    gdf_hosp[["geometry"]].assign(ftype="병의원"),
    gdf_pharm[["geometry"]].assign(ftype="약국"),
], ignore_index=True)
gdf_all = gpd.GeoDataFrame(gdf_all, geometry="geometry", crs="EPSG:5179")
print(f"  전체 의료시설: {len(gdf_all)}개")

# ═══════════════════════════════════════════════════════════════
# 3. 동별 청년/노인 30분권 내 의료시설 수 계산 — 시설 종류별 분리
#    (유클리드 거리 기반 — 도보 네트워크 실거리의 근사치)
# ═══════════════════════════════════════════════════════════════
print("\n[3/5] 동별 접근 가능 시설 수 계산 중…")

def count_in_radius(fac_gdf: gpd.GeoDataFrame, dong_df: gpd.GeoDataFrame):
    """각 동 중심점에서 청년/노인 반경 내 시설 수 반환 (DataFrame columns 추가용)"""
    xy = np.column_stack([fac_gdf.geometry.x.values, fac_gdf.geometry.y.values])
    young_list, senior_list = [], []
    for _, row in dong_df.iterrows():
        cx, cy = row["cx"], row["cy"]
        d = np.sqrt((xy[:, 0] - cx) ** 2 + (xy[:, 1] - cy) ** 2)
        young_list.append(int((d <= DIST_YOUNG).sum()))
        senior_list.append(int((d <= DIST_SENIOR).sum()))
    return young_list, senior_list

# 병의원
ny_h, ns_h = count_in_radius(gdf_hosp, gdf_dong)
gdf_dong["n_young_hosp"]  = ny_h
gdf_dong["n_senior_hosp"] = ns_h
gdf_dong["loss_pct_hosp"] = np.where(
    gdf_dong["n_young_hosp"] > 0,
    (1 - gdf_dong["n_senior_hosp"] / gdf_dong["n_young_hosp"]) * 100, 0.0,
).round(1)

# 약국
ny_p, ns_p = count_in_radius(gdf_pharm, gdf_dong)
gdf_dong["n_young_pharm"]  = ny_p
gdf_dong["n_senior_pharm"] = ns_p
gdf_dong["loss_pct_pharm"] = np.where(
    gdf_dong["n_young_pharm"] > 0,
    (1 - gdf_dong["n_senior_pharm"] / gdf_dong["n_young_pharm"]) * 100, 0.0,
).round(1)

# 전체 합산
ny_a, ns_a = count_in_radius(gdf_all, gdf_dong)
gdf_dong["n_young"]  = ny_a
gdf_dong["n_senior"] = ns_a
gdf_dong["loss_pct"] = np.where(
    gdf_dong["n_young"] > 0,
    (1 - gdf_dong["n_senior"] / gdf_dong["n_young"]) * 100, 0.0,
).round(1)
gdf_dong["n_loss"] = gdf_dong["n_young"] - gdf_dong["n_senior"]

valid = gdf_dong[gdf_dong["n_young"] > 0]
print(f"  계산 완료 — 유효 동: {len(valid)}개")
print(f"  [병의원] 평균 손실률: {gdf_dong[gdf_dong['n_young_hosp']>0]['loss_pct_hosp'].mean():.1f}%  "
      f"(청년 {gdf_dong['n_young_hosp'].mean():.1f}개 → 노인 {gdf_dong['n_senior_hosp'].mean():.1f}개)")
print(f"  [약국]   평균 손실률: {gdf_dong[gdf_dong['n_young_pharm']>0]['loss_pct_pharm'].mean():.1f}%  "
      f"(청년 {gdf_dong['n_young_pharm'].mean():.1f}개 → 노인 {gdf_dong['n_senior_pharm'].mean():.1f}개)")
print(f"  [전체]   평균 손실률: {valid['loss_pct'].mean():.1f}%  "
      f"(청년 {valid['n_young'].mean():.1f}개 → 노인 {valid['n_senior'].mean():.1f}개)")

# ═══════════════════════════════════════════════════════════════
# 4. WGS84 변환 (Folium용)
# ═══════════════════════════════════════════════════════════════
print("\n[4/5] 지도 시각화 생성 중…")
gdf_wgs = gdf_dong.to_crs("EPSG:4326")
gdf_wgs["cx_wgs"] = gdf_wgs.geometry.centroid.x
gdf_wgs["cy_wgs"] = gdf_wgs.geometry.centroid.y

from folium.plugins import HeatMap

# 히트맵용 WGS84 좌표 준비
t_wgs = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

def make_heat_data(gdf_fac):
    lons, lats = t_wgs.transform(
        gdf_fac.geometry.x.values, gdf_fac.geometry.y.values
    )
    return list(zip(lats.tolist(), lons.tolist()))

heat_all   = make_heat_data(gdf_all)
heat_hosp  = make_heat_data(gdf_hosp)
heat_pharm = make_heat_data(gdf_pharm)

def add_choropleth_layer(m, gdf_w, loss_col, n_young_col, n_senior_col,
                         layer_name, tooltip_label, show=True):
    """손실률 코로플레스 레이어를 지도에 추가하는 헬퍼"""
    sub = gdf_w[gdf_w[n_young_col] > 0]
    p10 = float(sub[loss_col].quantile(0.10))
    p90 = float(sub[loss_col].quantile(0.90))
    cmap = cm.LinearColormap(
        colors=["#FFF5F0", "#FCBBA1", "#FC7050", "#D73027", "#67000D"],
        vmin=p10, vmax=p90,
        caption=f"{tooltip_label} 손실률(%) — 청년 대비",
    )
    geojson = json.loads(
        gdf_w[["dong_code", "gu_name", "full_name",
               n_young_col, n_senior_col, loss_col, "geometry"]].to_json()
    )
    def _style(feat):
        v = feat["properties"].get(loss_col) or 0
        return {
            "fillColor":   cmap(min(max(v, p10), p90)),
            "color":       "rgba(80,80,80,0.35)",
            "weight":      0.5,
            "fillOpacity": 0.80,
        }
    def _highlight(feat):
        return {"fillOpacity": 0.95, "weight": 2, "color": "#FFD700"}

    fg = folium.FeatureGroup(name=layer_name, show=show)
    folium.GeoJson(
        data=geojson,
        style_function=_style,
        highlight_function=_highlight,
        tooltip=folium.GeoJsonTooltip(
            fields=["full_name", loss_col, n_young_col, n_senior_col],
            aliases=["행정동", "손실률(%)", "청년 접근", "노인 접근"],
            localize=True, sticky=True,
            style="font-family:'Malgun Gothic',sans-serif;font-size:13px;",
        ),
    ).add_to(fg)
    fg.add_to(m)
    cmap.add_to(m)

    # 손실 상위 10개 동 마커
    top10 = gdf_w.nlargest(10, loss_col)
    fg_top = folium.FeatureGroup(name=f"{layer_name} · 손실 상위 10동", show=False)
    for _, row in top10.iterrows():
        folium.CircleMarker(
            location=[row["cy_wgs"], row["cx_wgs"]],
            radius=7, color="#FF3300", weight=1.5,
            fill=True, fill_color="#FF3300", fill_opacity=0.85,
            tooltip=folium.Tooltip(
                f"<b>{row['full_name']}</b><br>"
                f"손실률: {row[loss_col]:.1f}%<br>"
                f"청년 {row[n_young_col]}개 → 노인 {row[n_senior_col]}개",
                sticky=True,
            ),
        ).add_to(fg_top)
    fg_top.add_to(m)

# ── 지도 생성 ───────────────────────────────────────────────────
m = folium.Map(location=[37.5665, 126.978], zoom_start=11, tiles=None, prefer_canvas=True)
folium.TileLayer("OpenStreetMap", name="일반 지도").add_to(m)
folium.TileLayer("CartoDB dark_matter", name="Dark Map").add_to(m)

# 3개 코로플레스 레이어
add_choropleth_layer(m, gdf_wgs, "loss_pct",       "n_young",       "n_senior",
                     "전체 (병의원+약국) 손실률", "전체 의료시설",   show=True)
add_choropleth_layer(m, gdf_wgs, "loss_pct_hosp",  "n_young_hosp",  "n_senior_hosp",
                     "병의원 손실률",              "병의원",          show=False)
add_choropleth_layer(m, gdf_wgs, "loss_pct_pharm", "n_young_pharm", "n_senior_pharm",
                     "약국 손실률",                "약국",            show=False)

# 히트맵 레이어 3종
for heat_data, heat_name in [
    (heat_all,   "전체 의료시설 분포"),
    (heat_hosp,  "병의원 분포"),
    (heat_pharm, "약국 분포"),
]:
    fg_h = folium.FeatureGroup(name=f"히트맵 — {heat_name}", show=False)
    HeatMap(heat_data, radius=8, blur=10, min_opacity=0.3).add_to(fg_h)
    fg_h.add_to(m)

folium.LayerControl(collapsed=False, position="topright").add_to(m)

mean_loss = float(valid["loss_pct"].mean())
mean_loss_h = float(gdf_dong[gdf_dong["n_young_hosp"] > 0]["loss_pct_hosp"].mean())
mean_loss_p = float(gdf_dong[gdf_dong["n_young_pharm"] > 0]["loss_pct_pharm"].mean())
title_html = f"""
<div style="
    position:fixed; top:10px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(10,10,20,0.92);
    border:1px solid #444; border-radius:8px;
    padding:10px 28px; text-align:center;
    font-family:'Malgun Gothic',sans-serif;
    box-shadow:0 2px 12px rgba(0,0,0,0.5);">
  <div style="font-size:17px;font-weight:bold;color:#fff;">
    서울시 동별 의료 접근성 손실률 (D3. 의료)
  </div>
  <div style="font-size:11px;color:#aaa;margin-top:4px;">
    청년 (1.2 m/s) vs 노인 (0.78 m/s) · 30분 도달 가능 시설 수 비교
  </div>
  <div style="font-size:11px;color:#ddd;margin-top:3px;">
    전체 평균 손실 <b style="color:#FC7050">{mean_loss:.1f}%</b> &nbsp;|&nbsp;
    병의원 <b style="color:#FC7050">{mean_loss_h:.1f}%</b> &nbsp;|&nbsp;
    약국 <b style="color:#FC7050">{mean_loss_p:.1f}%</b>
  </div>
  <div style="font-size:10px;color:#888;margin-top:2px;">
    청년 30분권 {DIST_YOUNG:.0f}m · 노인 30분권 {DIST_SENIOR:.0f}m
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

out1 = OUT_DIR / "01_medical_loss_map.html"
m.save(str(out1))
print(f"  저장: {out1}")

# ═══════════════════════════════════════════════════════════════
# 5. 통계 시각화 (Plotly)
# ═══════════════════════════════════════════════════════════════
print("\n[5/5] 통계 차트 생성 중…")

df_plot = gdf_wgs[[
    "full_name", "gu_name",
    "n_young",       "n_senior",       "loss_pct",
    "n_young_hosp",  "n_senior_hosp",  "loss_pct_hosp",
    "n_young_pharm", "n_senior_pharm", "loss_pct_pharm",
]].copy()
df_plot = df_plot[df_plot["n_young"] > 0].reset_index(drop=True)

ratio = DIST_SENIOR / DIST_YOUNG

# ── 5-a. 청년 vs 노인 산점도 — 시설 종류별 3패널 ─────────────
fig_scatter = make_subplots(
    rows=1, cols=3,
    subplot_titles=(
        f"전체 (병의원+약국)<br>평균 손실 {mean_loss:.1f}%",
        f"병의원만<br>평균 손실 {mean_loss_h:.1f}%",
        f"약국만<br>평균 손실 {mean_loss_p:.1f}%",
    ),
    horizontal_spacing=0.08,
)

PANEL_CFG = [
    ("n_young",       "n_senior",       "loss_pct",       "#4292C6", 1),
    ("n_young_hosp",  "n_senior_hosp",  "loss_pct_hosp",  "#2ca02c", 2),
    ("n_young_pharm", "n_senior_pharm", "loss_pct_pharm", "#9467bd", 3),
]

for xc, yc, lc, color, col in PANEL_CFG:
    sub = df_plot[df_plot[xc] > 0]
    max_v = int(sub[[xc, yc]].max().max()) + 5
    fig_scatter.add_trace(
        go.Scatter(
            x=sub[xc], y=sub[yc],
            mode="markers",
            marker=dict(
                color=sub[lc],
                colorscale="RdYlGn_r",
                size=5, opacity=0.7,
                showscale=(col == 1),
                colorbar=dict(title="손실률(%)", x=0.32) if col == 1 else {},
            ),
            text=sub["full_name"] + "<br>손실: " + sub[lc].round(1).astype(str) + "%",
            hovertemplate="%{text}<br>청년: %{x}개 / 노인: %{y}개<extra></extra>",
            showlegend=False,
        ),
        row=1, col=col,
    )
    # 기준선
    fig_scatter.add_trace(
        go.Scatter(x=[0, max_v], y=[0, max_v],
                   mode="lines", line=dict(dash="dash", color="gray", width=1),
                   name="손실 0%", showlegend=(col == 1)),
        row=1, col=col,
    )
    fig_scatter.add_trace(
        go.Scatter(x=[0, max_v], y=[0, max_v * ratio ** 2],
                   mode="lines", line=dict(dash="dot", color="orange", width=1.5),
                   name=f"이론선({ratio:.2f}²)", showlegend=(col == 1)),
        row=1, col=col,
    )

fig_scatter.update_layout(
    title_text="청년 vs 노인 30분권 내 의료시설 접근 수 비교 (동 단위, 시설 종류별)",
    font_family="Malgun Gothic",
    height=500,
    plot_bgcolor="#f8f8f8",
    legend=dict(orientation="h", y=-0.15),
)
for col in range(1, 4):
    fig_scatter.update_xaxes(title_text="청년 접근 시설 수", row=1, col=col)
    fig_scatter.update_yaxes(title_text="노인 접근 시설 수", row=1, col=col)

out2 = OUT_DIR / "02_access_scatter.html"
fig_scatter.write_html(str(out2))
print(f"  저장: {out2}")

# ── 5-b. 구별 평균 손실률 — 시설 종류별 3패널 바차트 ─────────
df_gu = (
    df_plot.groupby("gu_name")
    .agg(
        loss_all=("loss_pct",       "mean"),
        loss_h  =("loss_pct_hosp",  "mean"),
        loss_p  =("loss_pct_pharm", "mean"),
        ny_all  =("n_young",        "mean"),
        ns_all  =("n_senior",       "mean"),
        ny_h    =("n_young_hosp",   "mean"),
        ns_h    =("n_senior_hosp",  "mean"),
        ny_p    =("n_young_pharm",  "mean"),
        ns_p    =("n_senior_pharm", "mean"),
    )
    .reset_index()
    .sort_values("loss_all", ascending=False)
)

fig_bar = make_subplots(
    rows=1, cols=3,
    subplot_titles=("전체 손실률(%)", "병의원 손실률(%)", "약국 손실률(%)"),
    horizontal_spacing=0.10,
)

for (loss_col, color, col) in [
    ("loss_all", "Reds",   1),
    ("loss_h",   "Greens", 2),
    ("loss_p",   "Purples",3),
]:
    df_s = df_gu.sort_values(loss_col, ascending=True)
    fig_bar.add_trace(
        go.Bar(
            y=df_s["gu_name"], x=df_s[loss_col],
            orientation="h",
            marker=dict(color=df_s[loss_col], colorscale=color),
            text=df_s[loss_col].round(1).astype(str) + "%",
            textposition="outside",
            showlegend=False,
        ),
        row=1, col=col,
    )

fig_bar.update_layout(
    title_text="서울 25개 구별 의료 접근성 손실률 — 시설 종류별 비교",
    font_family="Malgun Gothic",
    height=750,
    plot_bgcolor="#f8f8f8",
)
for col in range(1, 4):
    fig_bar.update_xaxes(title_text="평균 손실률(%)", row=1, col=col)

out3 = OUT_DIR / "03_gu_comparison.html"
fig_bar.write_html(str(out3))
print(f"  저장: {out3}")

# ── 5-c. 분포 히스토그램 — 시설 종류별 ──────────────────────
fig_hist = make_subplots(
    rows=1, cols=3,
    subplot_titles=("전체 손실률(%) 분포", "병의원 손실률(%) 분포", "약국 손실률(%) 분포"),
)
for (lc, color, col, name) in [
    ("loss_pct",       "#E6550D", 1, "전체"),
    ("loss_pct_hosp",  "#2ca02c", 2, "병의원"),
    ("loss_pct_pharm", "#9467bd", 3, "약국"),
]:
    fig_hist.add_trace(
        go.Histogram(x=df_plot[lc], name=name,
                     marker_color=color, opacity=0.8, nbinsx=30),
        row=1, col=col,
    )
fig_hist.update_layout(
    font_family="Malgun Gothic", height=400,
    plot_bgcolor="#f8f8f8", showlegend=False,
)
for col in range(1, 4):
    fig_hist.update_xaxes(title_text="손실률(%)", row=1, col=col)
    fig_hist.update_yaxes(title_text="동 수", row=1, col=col)

out4 = OUT_DIR / "04_distribution.html"
fig_hist.write_html(str(out4))
print(f"  저장: {out4}")

print("\n" + "=" * 60)
print("분석 완료!")
print(f"  [전체]  평균 손실률: {mean_loss:.1f}%  "
      f"(청년 {df_plot['n_young'].mean():.1f}개 → 노인 {df_plot['n_senior'].mean():.1f}개)")
print(f"  [병의원] 평균 손실률: {mean_loss_h:.1f}%  "
      f"(청년 {df_plot['n_young_hosp'].mean():.1f}개 → 노인 {df_plot['n_senior_hosp'].mean():.1f}개)")
print(f"  [약국]  평균 손실률: {mean_loss_p:.1f}%  "
      f"(청년 {df_plot['n_young_pharm'].mean():.1f}개 → 노인 {df_plot['n_senior_pharm'].mean():.1f}개)")
print("=" * 60)
print(f"\n출력 파일:")
for f in [out1, out2, out3, out4]:
    print(f"  {f}")
