"""
07_correlation_analysis.py
--------------------------
① 네트워크 접근성(n_young) × 손실률 — 도시 구조가 손실을 설명하는가?
② 노인 인구 × 손실률 — 상관관계가 실제로 있는가?
③ 핵심 지표: 영향받는 노인 수 = loss_pct × pop_65plus / 100
   → 개입 우선순위 코로플레스 지도

출력:
  ../outputs/07a_scatter_network.html    산점도 A: 네트워크 접근성 vs 손실률
  ../outputs/07b_scatter_senior.html     산점도 B: 노인 인구 vs 손실률
  ../outputs/07c_priority_map.html       코로플레스: 영향받는 노인 수 (개입 우선순위)
"""

import warnings, json, logging
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy import stats
import plotly.graph_objects as go
import plotly.express as px
import folium
import branca.colormap as cm

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE   = Path(__file__).resolve().parents[1]
SENIOR_ROOT = WORKSPACE.parents[0]
OUTPUT_DIR  = WORKSPACE / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

GU_NAMES = {
    "종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구",
    "강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구",
    "구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구",
}

# ── 1. 손실률 데이터 로드 ─────────────────────────────────
logger.info("손실률 데이터 로드…")
df_loss = pd.read_csv(
    WORKSPACE / "cache" / "dong_loss_ratio.csv",
    dtype={"dong_code": str}
)
logger.info("  %d개 동", len(df_loss))

# ── 2. 주민등록 인구 CSV → 동별 65세+ 인구 추출 ──────────
logger.info("주민등록 인구 CSV 파싱…")
CSV_PATH = SENIOR_ROOT / "data" / "raw" / "seoul_data_hub" / "서울시주민등록인구_동별집계.csv"

df_raw = pd.read_csv(CSV_PATH, encoding="utf-8-sig", header=None,
                     on_bad_lines="skip", engine="python")
df_raw.columns = ["dong", "age", "item", "unit", "pop", "extra"]
df = df_raw[df_raw["dong"] != "동별"].copy()
df["pop"] = pd.to_numeric(df["pop"], errors="coerce").fillna(0)

is_summary = df["dong"].isin({"합계"} | GU_NAMES)
df_dong = df[~is_summary].copy()

def is_senior_age(age_str):
    if not isinstance(age_str, str): return False
    if age_str == "100세이상": return True
    if age_str.endswith("세"):
        try: return int(age_str.replace("세", "")) >= 65
        except: return False
    return False

df_senior = df_dong[df_dong["age"].apply(is_senior_age)]
dong_senior = df_senior.groupby("dong")["pop"].sum().reset_index().rename(columns={"pop":"pop_65plus"})
dong_total  = df_dong[df_dong["age"]=="합계"].groupby("dong")["pop"].sum().reset_index().rename(columns={"pop":"pop_total"})
df_pop = dong_senior.merge(dong_total, on="dong", how="left")
df_pop["senior_ratio"] = (df_pop["pop_65plus"] / df_pop["pop_total"] * 100).round(1)

# 구-동 매핑
gu_order, current_gu = [], None
for _, row in df_raw.iterrows():
    if row["dong"] in GU_NAMES:
        current_gu = row["dong"]
    elif row["dong"] not in {"합계","동별"} and row["age"] == "합계":
        gu_order.append({"dong": row["dong"], "gu": current_gu})
df_gu_map = pd.DataFrame(gu_order).drop_duplicates("dong")
df_pop = df_pop.merge(df_gu_map, on="dong", how="left")
df_pop["full_name"] = df_pop["gu"].fillna("") + " " + df_pop["dong"]
logger.info("  %d개 동 인구 집계 완료", len(df_pop))

# ── 3. 병합: 동명 + 구명으로 join ────────────────────────
logger.info("손실률 × 노인인구 병합 (동명+구명)…")
df_loss["full_name"] = df_loss["gu_name"] + " " + df_loss["dong_name"]
df_merged = df_loss.merge(
    df_pop[["full_name", "pop_65plus", "pop_total", "senior_ratio"]],
    on="full_name", how="inner"
)
logger.info("  매칭: %d / %d개 동", len(df_merged), len(df_loss))

# 핵심 지표: 영향받는 노인 수
df_merged["affected_seniors"] = (df_merged["loss_pct"] / 100 * df_merged["pop_65plus"]).round(0)
df_merged["senior_density"]   = df_merged["pop_65plus"]   # 절대 인구수 사용

# ── 4. 상관계수 계산 ─────────────────────────────────────
r_network, p_network = stats.pearsonr(df_merged["n_young"], df_merged["loss_pct"])
r_senior,  p_senior  = stats.pearsonr(df_merged["pop_65plus"], df_merged["loss_pct"])
r_ratio,   p_ratio   = stats.pearsonr(df_merged["senior_ratio"], df_merged["loss_pct"])

logger.info("\n=== 상관계수 (Pearson r) ===")
logger.info("  n_young × loss_pct:      r=%.3f  p=%.4f", r_network, p_network)
logger.info("  pop_65plus × loss_pct:   r=%.3f  p=%.4f", r_senior,  p_senior)
logger.info("  senior_ratio × loss_pct: r=%.3f  p=%.4f", r_ratio,   p_ratio)

# 회귀선
def reg_line(x, y):
    slope, intercept, r, p, _ = stats.linregress(x, y)
    x_range = np.linspace(x.min(), x.max(), 100)
    return x_range, intercept + slope * x_range, r, p

# ═══════════════════════════════════════════════════════════
# 산점도 A: 네트워크 접근성(n_young) × 손실률
# ═══════════════════════════════════════════════════════════
logger.info("산점도 A 생성…")
xA, yA, rA, pA = reg_line(df_merged["n_young"], df_merged["loss_pct"])

fig_a = go.Figure()

# 산점
fig_a.add_trace(go.Scatter(
    x=df_merged["n_young"],
    y=df_merged["loss_pct"],
    mode="markers",
    marker=dict(
        size=8,
        color=df_merged["loss_pct"],
        colorscale="RdYlBu_r",
        showscale=True,
        colorbar=dict(title="손실률(%)"),
        opacity=0.75,
        line=dict(width=0.5, color="#333"),
    ),
    text=df_merged["full_name"],
    customdata=df_merged[["pop_65plus","senior_ratio","gu_name"]].values,
    hovertemplate=(
        "<b>%{text}</b><br>"
        "일반인 도달 노드: %{x:,}<br>"
        "손실률: %{y:.1f}%<br>"
        "65세+: %{customdata[0]:,.0f}명 (%{customdata[1]:.1f}%)<br>"
        "<extra></extra>"
    ),
    name="행정동",
))

# 회귀선
sig_text = "p<0.001" if pA < 0.001 else f"p={pA:.3f}"
fig_a.add_trace(go.Scatter(
    x=xA, y=yA,
    mode="lines",
    line=dict(color="#E63946", width=2, dash="dash"),
    name=f"회귀선 (r={rA:.2f}, {sig_text})",
    hoverinfo="skip",
))

fig_a.update_layout(
    title=dict(
        text=(
            "<b>네트워크 접근성 vs 보행 손실률</b>"
            f"<br><sup>일반인 30분 도달 노드 수 vs 손실률 | r={rA:.3f}, {sig_text}"
            f" | n={len(df_merged)}개 동</sup>"
        ),
        x=0.5, font=dict(size=15)
    ),
    xaxis=dict(
        title="일반인 30분 도달 노드 수 (네트워크 접근성 프록시)",
        gridcolor="#eee",
    ),
    yaxis=dict(
        title="30분 보행 손실률 (%)",
        gridcolor="#eee",
    ),
    plot_bgcolor="#fafafa",
    paper_bgcolor="white",
    height=560,
    font=dict(family="AppleGothic, Malgun Gothic, sans-serif"),
    annotations=[
        dict(
            x=0.97, y=0.97, xref="paper", yref="paper",
            text=(
                f"<b>해석</b><br>"
                f"r = {rA:.3f}<br>"
                f"노드 수 많을수록(연결성 좋을수록)<br>"
                f"{'손실률 감소 경향' if rA < 0 else '손실률 증가 경향'}"
            ),
            showarrow=False,
            align="right",
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#ccc",
            borderwidth=1,
            font=dict(size=12),
            xanchor="right", yanchor="top",
        )
    ],
    legend=dict(x=0.01, y=0.01, bgcolor="rgba(255,255,255,0.8)"),
)

out_a = OUTPUT_DIR / "07a_scatter_network.html"
fig_a.write_html(str(out_a))
logger.info("저장: %s", out_a)

# ═══════════════════════════════════════════════════════════
# 산점도 B: 노인 인구 / 고령화율 × 손실률
# ═══════════════════════════════════════════════════════════
logger.info("산점도 B 생성…")
xB, yB, rB, pB = reg_line(df_merged["senior_ratio"], df_merged["loss_pct"])

fig_b = go.Figure()

# 버블 산점도: x=고령화율, y=손실률, 버블크기=노인 절대인구수
max_pop = df_merged["pop_65plus"].max()
fig_b.add_trace(go.Scatter(
    x=df_merged["senior_ratio"],
    y=df_merged["loss_pct"],
    mode="markers",
    marker=dict(
        size=df_merged["pop_65plus"] / max_pop * 40 + 5,
        color=df_merged["affected_seniors"],
        colorscale="OrRd",
        showscale=True,
        colorbar=dict(title="영향받는<br>노인 수(명)"),
        opacity=0.7,
        line=dict(width=0.5, color="#555"),
    ),
    text=df_merged["full_name"],
    customdata=df_merged[["pop_65plus","affected_seniors","loss_pct"]].values,
    hovertemplate=(
        "<b>%{text}</b><br>"
        "고령화율: %{x:.1f}%<br>"
        "손실률: %{y:.1f}%<br>"
        "65세+ 인구: %{customdata[0]:,.0f}명<br>"
        "<b>영향받는 노인: %{customdata[1]:,.0f}명</b>"
        "<extra></extra>"
    ),
    name="행정동 (버블 크기 = 노인 절대 인구)",
))

# 회귀선
sig_text_b = "p<0.001" if pB < 0.001 else f"p={pB:.3f}"
fig_b.add_trace(go.Scatter(
    x=xB, y=yB,
    mode="lines",
    line=dict(color="#E63946", width=2, dash="dash"),
    name=f"회귀선 (r={rB:.2f}, {sig_text_b})",
    hoverinfo="skip",
))

# 사분면 기준선 (평균)
mean_ratio = df_merged["senior_ratio"].mean()
mean_loss  = df_merged["loss_pct"].mean()

for val, axis, dash, color, text in [
    (mean_ratio, "x", "dot", "#888", f"고령화율 평균 {mean_ratio:.1f}%"),
    (mean_loss,  "y", "dot", "#888", f"손실률 평균 {mean_loss:.1f}%"),
]:
    fig_b.add_shape(
        type="line",
        **({axis+"0": val, axis+"1": val,
            ("y0" if axis=="x" else "x0"): 0,
            ("y1" if axis=="x" else "x1"): 1}),
        xref="x" if axis=="x" else "paper",
        yref="y" if axis=="y" else "paper",
        line=dict(color=color, width=1, dash=dash),
    )

# 사분면 라벨
quad_labels = [
    (mean_ratio*1.5, mean_loss*1.12, "🔴 고위험<br>고령화↑ 손실↑", "rgba(255,100,100,0.15)"),
    (mean_ratio*0.4, mean_loss*1.12, "🟡 네트워크 문제<br>고령화↓ 손실↑", "rgba(255,220,50,0.15)"),
    (mean_ratio*1.5, mean_loss*0.88, "🟠 인구 위험<br>고령화↑ 손실↓", "rgba(255,160,50,0.15)"),
    (mean_ratio*0.4, mean_loss*0.88, "🟢 상대 양호<br>고령화↓ 손실↓", "rgba(50,200,100,0.15)"),
]

# 핵심 insight 박스: 영향받는 노인 수 상위 5개 동
top5 = df_merged.nlargest(5, "affected_seniors")
top5_text = "<br>".join(
    f"  {r['full_name']}: {r['affected_seniors']:,.0f}명 (손실 {r['loss_pct']:.1f}%)"
    for _, r in top5.iterrows()
)

fig_b.update_layout(
    title=dict(
        text=(
            "<b>고령화율 vs 보행 손실률</b>  (버블 크기 = 노인 절대 인구)"
            f"<br><sup>r={rB:.3f}, {sig_text_b} | n={len(df_merged)}개 동"
            f" | 평균 손실: {mean_loss:.1f}%</sup>"
        ),
        x=0.5, font=dict(size=15)
    ),
    xaxis=dict(
        title="고령화율 (65세 이상 / 전체 인구, %)",
        gridcolor="#eee",
    ),
    yaxis=dict(
        title="30분 보행 손실률 (%)",
        gridcolor="#eee",
    ),
    plot_bgcolor="#fafafa",
    paper_bgcolor="white",
    height=600,
    font=dict(family="AppleGothic, Malgun Gothic, sans-serif"),
    annotations=[
        dict(
            x=0.98, y=0.02, xref="paper", yref="paper",
            text=(
                f"<b>영향받는 노인 수 TOP 5</b><br>"
                f"{top5_text}<br>"
                f"<br>※ '영향받는 노인' = 손실률 × 노인 인구"
            ),
            showarrow=False,
            align="left",
            bgcolor="rgba(255,255,240,0.95)",
            bordercolor="#ccc",
            borderwidth=1,
            font=dict(size=11),
            xanchor="right", yanchor="bottom",
        )
    ],
    legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
)

out_b = OUTPUT_DIR / "07b_scatter_senior.html"
fig_b.write_html(str(out_b))
logger.info("저장: %s", out_b)

# ═══════════════════════════════════════════════════════════
# 코로플레스 C: "영향받는 노인 수" 개입 우선순위 지도
# ═══════════════════════════════════════════════════════════
logger.info("코로플레스 C 생성 (개입 우선순위 지도)…")

# shapefile 로드
SHP_PATH = SENIOR_ROOT / "data" / "raw" / "BND_ADM_DONG_PG" / "BND_ADM_DONG_PG.shp"
gdf = gpd.read_file(str(SHP_PATH))
gdf = gdf[gdf["ADM_CD"].astype(str).str.startswith("11")].copy()
gdf = gdf.to_crs("EPSG:4326")

GU_CODE_MAP = {
    "11010":"종로구","11020":"중구","11030":"용산구","11040":"성동구",
    "11050":"광진구","11060":"동대문구","11070":"중랑구","11080":"성북구",
    "11090":"강북구","11100":"도봉구","11110":"노원구","11120":"은평구",
    "11130":"서대문구","11140":"마포구","11150":"양천구","11160":"강서구",
    "11170":"구로구","11180":"금천구","11190":"영등포구","11200":"동작구",
    "11210":"관악구","11220":"서초구","11230":"강남구","11240":"송파구",
    "11250":"강동구",
}
gdf["gu_name"]   = gdf["ADM_CD"].astype(str).str[:5].map(GU_CODE_MAP).fillna("")
gdf["full_name"] = gdf["gu_name"] + " " + gdf["ADM_NM"]
gdf["dong_code"] = gdf["ADM_CD"].astype(str)

gdf = gdf.merge(
    df_merged[["full_name","loss_pct","pop_65plus","senior_ratio","affected_seniors"]],
    on="full_name", how="left"
)
gdf["affected_seniors"] = gdf["affected_seniors"].fillna(0)
gdf["loss_pct"]         = gdf["loss_pct"].fillna(df_merged["loss_pct"].mean())

# 컬러맵
p10 = float(df_merged["affected_seniors"].quantile(0.10))
p90 = float(df_merged["affected_seniors"].quantile(0.90))

colormap_c = cm.LinearColormap(
    colors=["#FFF5EB", "#FDD0A2", "#FD8D3C", "#D94801", "#7F2704"],
    vmin=p10, vmax=p90,
    caption="영향받는 노인 수 = 손실률 × 65세+ 인구 (개입 우선순위)",
)

geojson_c = json.loads(gdf[["full_name","loss_pct","pop_65plus",
                              "senior_ratio","affected_seniors","geometry"]].to_json())

m2 = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles=None)
folium.TileLayer("OpenStreetMap",      name="🗺️ 일반지도").add_to(m2)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri", name="🛰️ 위성지도",
).add_to(m2)
folium.TileLayer("CartoDB dark_matter", name="🌑 Dark").add_to(m2)

def style_c(feature):
    v = feature["properties"].get("affected_seniors") or 0
    clipped = min(max(v, p10), p90)
    return {
        "fillColor":   colormap_c(clipped),
        "color":       "rgba(60,60,60,0.3)",
        "weight":      0.6,
        "fillOpacity": 0.80,
    }

def hl_c(feature):
    return {"fillOpacity": 0.95, "weight": 2, "color": "#FFD700"}

fg_c = folium.FeatureGroup(name="개입 우선순위 (영향 노인 수)", show=True)
folium.GeoJson(
    data=geojson_c,
    style_function=style_c,
    highlight_function=hl_c,
    tooltip=folium.GeoJsonTooltip(
        fields=["full_name","affected_seniors","loss_pct","pop_65plus","senior_ratio"],
        aliases=["행정동","영향받는 노인(명)","손실률(%)","65세+ 인구","고령화율(%)"],
        localize=True, sticky=True,
        style="font-family:'AppleGothic','Malgun Gothic',sans-serif;font-size:13px;",
    ),
).add_to(fg_c)
fg_c.add_to(m2)
colormap_c.add_to(m2)

# 상위 10개 동 마커 (영향 노인 수 기준)
top10 = df_merged.nlargest(10, "affected_seniors")
fg_top = folium.FeatureGroup(name="🔴 개입 우선 상위 10개 동", show=True)
for _, row in top10.iterrows():
    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=8,
        color="#FF4500",
        weight=2,
        fill=True,
        fill_color="#FF4500",
        fill_opacity=0.9,
        tooltip=folium.Tooltip(
            f"<b>{row['full_name']}</b><br>"
            f"영향받는 노인: <b>{row['affected_seniors']:,.0f}명</b><br>"
            f"손실률: {row['loss_pct']:.1f}%  |  65세+: {row['pop_65plus']:,.0f}명",
            sticky=True,
        ),
    ).add_to(fg_top)
    folium.map.Marker(
        location=[row["lat"] + 0.003, row["lon"]],
        icon=folium.DivIcon(
            html=(
                f'<div style="font-size:9px;color:#FF4500;font-weight:bold;'
                f'text-shadow:1px 1px 2px #fff;white-space:nowrap;">'
                f'{row["full_name"]}</div>'
            ),
            icon_size=(130, 16),
        ),
    ).add_to(fg_top)
fg_top.add_to(m2)

folium.LayerControl(collapsed=False, position="topright").add_to(m2)

# 타이틀
total_affected = int(df_merged["affected_seniors"].sum())
title_c = f"""
<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);
    z-index:9999;background:rgba(10,10,20,0.92);border:1px solid #444;
    border-radius:8px;padding:10px 28px;text-align:center;
    font-family:'AppleGothic','Malgun Gothic',sans-serif;">
  <div style="font-size:16px;font-weight:bold;color:#fff;">
    보행 개입 우선순위 지도 — 영향받는 노인 수
  </div>
  <div style="font-size:11px;color:#aaa;margin-top:3px;">
    영향받는 노인 = 손실률(%) × 65세+ 인구 | 진할수록 개입 시급 |
    서울 전체: <b style="color:#FD8D3C">{total_affected:,}명</b> 영향권
  </div>
</div>
"""
m2.get_root().html.add_child(folium.Element(title_c))

out_c = OUTPUT_DIR / "07c_priority_map.html"
m2.save(str(out_c))
logger.info("저장: %s", out_c)

# ── 요약 출력 ─────────────────────────────────────────────
print(f"\n{'='*60}")
print("▶ 분석 결과 요약")
print(f"{'='*60}")
print(f"\n[상관계수]")
print(f"  네트워크 접근성(n_young) × 손실률: r={r_network:.3f}  p={p_network:.4f}")
print(f"  고령화율(%)          × 손실률: r={r_ratio:.3f}  p={p_ratio:.4f}")
print(f"  노인 절대인구        × 손실률: r={r_senior:.3f}  p={p_senior:.4f}")
print(f"\n[영향받는 노인 수 상위 10개 동]")
for _, r in df_merged.nlargest(10, "affected_seniors").iterrows():
    print(f"  {r['full_name']:<15} 손실 {r['loss_pct']:5.1f}%  "
          f"노인 {r['pop_65plus']:6,.0f}명  → 영향 {r['affected_seniors']:5,.0f}명")
print(f"\n  서울 전체 영향 노인 수 합계: {total_affected:,}명")
print(f"\n{'='*60}")
print("▶ 출력 파일")
print(f"{'='*60}")
for f in ["07a_scatter_network.html","07b_scatter_senior.html","07c_priority_map.html"]:
    print(f"  {OUTPUT_DIR/f}")
