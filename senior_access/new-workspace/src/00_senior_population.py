"""
00_senior_population.py  (v2 — 동별 집계 long-format CSV 처리)
--------------------------------------------------------------
서울시 주민등록인구 동별집계 CSV에서 65세+ 인구를 동(洞) 단위로 집계하고,
가장 노인 인구가 많은 동을 선정합니다.

데이터 구조 (long-format):
  동별 | 각세별 | 항목 | 단위 | 2025.4/4
  ---  | 0세  |  …  |  …  | 43645
  …

출력:
  ../outputs/senior_population_map.html  — 구별 65세+ 인구 코로플레스
  콘솔: 동별 상위 순위 및 선정 이유
"""

from pathlib import Path
import pandas as pd
import json
import urllib.request
import plotly.graph_objects as go

# ── 경로 설정 ────────────────────────────────────────────
SENIOR_ROOT = Path(__file__).resolve().parents[2]
CSV_DONG    = SENIOR_ROOT / "data" / "raw" / "seoul_data_hub" / "서울시주민등록인구_동별집계.csv"
CSV_GU      = SENIOR_ROOT / "data" / "raw" / "seoul_data_hub" / "서울시주민등록인구_구별집계.csv"
OUTPUT_DIR  = Path(__file__).resolve().parents[1] / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# 서울 25개 구 이름 (필터용)
GU_NAMES = {
    "종로구","중구","용산구","성동구","광진구","동대문구","중랑구","성북구",
    "강북구","도봉구","노원구","은평구","서대문구","마포구","양천구","강서구",
    "구로구","금천구","영등포구","동작구","관악구","서초구","강남구","송파구","강동구",
}

# ── 1. 동별 long-format CSV 로드 ─────────────────────────
df_raw = pd.read_csv(CSV_DONG, encoding="utf-8-sig", header=None,
                     on_bad_lines="skip", engine="python")
df_raw.columns = ["dong", "age", "item", "unit", "pop", "extra"]

# 헤더 행(row 0) 제거
df = df_raw[df_raw["dong"] != "동별"].copy()
df["pop"] = pd.to_numeric(df["pop"], errors="coerce").fillna(0)

# ── 2. 동(洞) 단위 필터링 ────────────────────────────────
# '합계' 행과 구 이름 행 제거 → 실제 동만 남김
is_summary = df["dong"].isin({"합계"} | GU_NAMES)
df_dong = df[~is_summary].copy()

# ── 3. 65세+ 행 필터링 ──────────────────────────────────
# 나이 값: "65세", "66세", ..., "100세이상"
def is_senior_age(age_str):
    if not isinstance(age_str, str):
        return False
    if age_str == "100세이상":
        return True
    if age_str.endswith("세"):
        try:
            return int(age_str.replace("세", "")) >= 65
        except ValueError:
            return False
    return False

senior_mask = df_dong["age"].apply(is_senior_age)
df_senior = df_dong[senior_mask].copy()

# ── 4. 동별 65세+ 합산 ───────────────────────────────────
dong_senior = (
    df_senior.groupby("dong")["pop"]
    .sum()
    .reset_index()
    .rename(columns={"pop": "pop_65plus"})
)

# 전체 인구 합산
dong_total = (
    df_dong[df_dong["age"] == "합계"]
    .groupby("dong")["pop"]
    .sum()
    .reset_index()
    .rename(columns={"pop": "pop_total"})
)

df_result = pd.merge(dong_senior, dong_total, on="dong", how="left")
df_result["senior_ratio"] = (
    df_result["pop_65plus"] / df_result["pop_total"] * 100
).round(1)
df_result = df_result.sort_values("pop_65plus", ascending=False).reset_index(drop=True)

# ── 5. 동이 속한 구 정보 추가 ────────────────────────────
# 원본에서 구-동 순서 관계를 추출
gu_order = []
current_gu = None
for _, row in df_raw.iterrows():
    if row["dong"] in GU_NAMES:
        current_gu = row["dong"]
    elif row["dong"] not in {"합계", "동별"} and row["age"] == "합계":
        gu_order.append({"dong": row["dong"], "gu": current_gu})

df_gu_map = pd.DataFrame(gu_order).drop_duplicates("dong")
df_result = pd.merge(df_result, df_gu_map, on="dong", how="left")

print("=" * 65)
print("▶ 서울시 동별 65세+ 인구 상위 20위 (2025년 4분기 주민등록인구)")
print("=" * 65)
for i, row in df_result.head(20).iterrows():
    print(f"  {i+1:2d}. {row['gu']:<5} {row['dong']:<12}  "
          f"65세+ {row['pop_65plus']:>6,.0f}명  고령화율 {row['senior_ratio']:>5.1f}%")

top_dong = df_result.iloc[0]
print(f"\n✅ 선정: [{top_dong['gu']} {top_dong['dong']}]  "
      f"65세+ {top_dong['pop_65plus']:,.0f}명 (서울 전체 1위)")

# ── 6. 구별 집계 (코로플레스용) ──────────────────────────
df_gu_agg = (
    df_result.groupby("gu")["pop_65plus"]
    .sum()
    .reset_index()
    .rename(columns={"gu": "gu_name"})
    .sort_values("pop_65plus", ascending=False)
    .reset_index(drop=True)
)

# 구별 총 인구는 구별 집계 CSV에서 가져옴
try:
    df_gu_raw = pd.read_csv(CSV_GU, encoding="utf-8-sig", header=None)
    df_gu_pop = df_gu_raw.iloc[3:].copy()
    df_gu_pop.columns = (
        ["구분1", "구분2", "소계"] + [f"age_{i}" for i in range(100)] + ["age_100plus"]
    )
    df_gu_pop["pop_total"] = pd.to_numeric(df_gu_pop["소계"], errors="coerce").fillna(0)
    gu_total_map = dict(zip(df_gu_pop["구분2"], df_gu_pop["pop_total"]))
    df_gu_agg["pop_total"] = df_gu_agg["gu_name"].map(gu_total_map).fillna(0)
    df_gu_agg["senior_ratio"] = (
        df_gu_agg["pop_65plus"] / df_gu_agg["pop_total"] * 100
    ).round(1)
except Exception:
    df_gu_agg["senior_ratio"] = 0.0

# ── 7. 서울 구 경계 GeoJSON 다운로드 ────────────────────
GEOJSON_URL   = (
    "https://raw.githubusercontent.com/southkorea/seoul-maps/master"
    "/kostat/2013/json/seoul_municipalities_geo_simple.json"
)
LOCAL_GEOJSON = OUTPUT_DIR / "seoul_gu.geojson"

if not LOCAL_GEOJSON.exists():
    print("\n📥 서울 구 경계 GeoJSON 다운로드 중...")
    try:
        urllib.request.urlretrieve(GEOJSON_URL, LOCAL_GEOJSON)
        print("   완료")
    except Exception as e:
        print(f"   실패: {e}")
        LOCAL_GEOJSON = None

# ── 8. Plotly 코로플레스 ─────────────────────────────────
if LOCAL_GEOJSON and LOCAL_GEOJSON.exists():
    with open(LOCAL_GEOJSON, encoding="utf-8") as f:
        geojson = json.load(f)

    fig = go.Figure(
        go.Choroplethmapbox(
            geojson=geojson,
            locations=df_gu_agg["gu_name"],
            featureidkey="properties.name",
            z=df_gu_agg["pop_65plus"],
            colorscale="Reds",
            zmin=0,
            zmax=df_gu_agg["pop_65plus"].max(),
            marker_opacity=0.75,
            marker_line_width=0.8,
            marker_line_color="white",
            colorbar=dict(
                title=dict(text="65세+ 인구 (명)", font=dict(size=13)),
                thickness=14,
                len=0.55,
            ),
            customdata=df_gu_agg[["senior_ratio"]].values,
            hovertemplate=(
                "<b>%{location}</b><br>"
                "65세+ 인구: %{z:,.0f}명<br>"
                "고령화율: %{customdata[0]:.1f}%"
                "<extra></extra>"
            ),
        )
    )

    # 송파구(1위) 강조 마커
    fig.add_trace(go.Scattermapbox(
        lat=[37.5145], lon=[127.1058],
        mode="markers+text",
        marker=dict(size=18, color="darkred", symbol="star"),
        text=["★ 1위"],
        textposition="top center",
        textfont=dict(size=12, color="darkred"),
        hoverinfo="skip",
        showlegend=False,
    ))

    fig.update_layout(
        mapbox=dict(
            style="carto-positron",
            center=dict(lat=37.5665, lon=126.9780),
            zoom=10.3,
        ),
        title=dict(
            text=(
                "<b>서울시 구별 65세 이상 인구 분포</b>"
                "<br><sub>2025년 4분기 주민등록인구 기준  |  ★ = 노인 인구 최다 (송파구)</sub>"
            ),
            x=0.5,
            font=dict(size=16),
        ),
        font=dict(family="AppleGothic, Malgun Gothic, sans-serif"),
        height=680,
        margin=dict(l=0, r=0, t=80, b=0),
    )

    out_path = OUTPUT_DIR / "senior_population_map.html"
    fig.write_html(str(out_path))
    print(f"\n📄 출력 → {out_path}")

print("\n상위 3개 동:")
for _, row in df_result.head(3).iterrows():
    print(f"  {row['gu']} {row['dong']}: {row['pop_65plus']:,.0f}명")
