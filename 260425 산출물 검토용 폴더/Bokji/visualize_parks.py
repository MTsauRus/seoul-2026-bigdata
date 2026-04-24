"""
서울시 녹지·공원 접근성 시각화
================================
공원 위치 / 면적 / 구별 녹지지수 / 보행권 버퍼를 단독 파일로 출력
"""

import warnings
warnings.filterwarnings('ignore')

import io, os, re
import pandas as pd
import geopandas as gpd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.cm as cm
import koreanize_matplotlib
import folium
import branca.colormap as bc
import requests

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CRS_WGS84 = "EPSG:4326"
CRS_KOREA = "EPSG:5179"

# ── 서울 25개 자치구 목록 ────────────────────────────────────
SEOUL_GU = [
    '종로구','중구','용산구','성동구','광진구','동대문구','중랑구',
    '성북구','강북구','도봉구','노원구','은평구','서대문구','마포구',
    '양천구','강서구','구로구','금천구','영등포구','동작구','관악구',
    '서초구','강남구','송파구','강동구'
]

# ============================================================
# 데이터 로드
# ============================================================
print("데이터 로드 중...")

# 공원 데이터
parks_raw = pd.read_excel(os.path.join(BASE_DIR, "서울시 주요 공원현황(2026 상반기).xlsx"))
parks_raw.columns = [
    '연번','관리부서','전화번호','공원명','공원개요',
    '면적','개원일','주요시설','주요식물','안내도',
    '오시는길','이용시참고사항','이미지','지역','공원주소',
    'X_GRS80','Y_GRS80','X_WGS84','Y_WGS84','바로가기'
]

def parse_area(val):
    if pd.isna(val): return np.nan
    m = re.search(r'[\d,]+\.?\d*', str(val).replace(',',''))
    return float(m.group().replace(',','')) if m else np.nan

parks_raw['면적_m2'] = parks_raw['면적'].apply(parse_area)
parks_df = parks_raw[parks_raw['지역'].isin(SEOUL_GU)].copy()
parks_df = parks_df.dropna(subset=['X_WGS84','Y_WGS84','면적_m2'])
parks_df = parks_df[parks_df['X_WGS84'] > 0]

# 고령인구 데이터
elderly_raw = pd.read_csv(
    os.path.join(BASE_DIR, "고령자현황_20260421103806.csv"),
    encoding='utf-8-sig', header=None
)
elderly_raw.columns = [
    '구분1','구명','동명',
    '전체인구','전체_남','전체_여',
    '65세이상','65세이상_남','65세이상_여',
    '내국인_65','내국인_65남','내국인_65여',
    '외국인_65','외국인_65남','외국인_65여'
]
elderly_data = elderly_raw.iloc[4:].copy()
elderly_data = elderly_data[
    (elderly_data['구명'] != '소계') & (elderly_data['동명'] != '소계')
]
for c in ['전체인구','65세이상']:
    elderly_data[c] = pd.to_numeric(
        elderly_data[c].astype(str).str.replace(',',''), errors='coerce'
    )
elderly_data = elderly_data.dropna(subset=['65세이상'])

elderly_gu = elderly_data.groupby('구명').agg(
    전체인구=('전체인구','sum'),
    pop_65=('65세이상','sum')
).reset_index()
elderly_gu.rename(columns={'pop_65':'65세이상인구'}, inplace=True)
elderly_gu['고령화율'] = (elderly_gu['65세이상인구'] / elderly_gu['전체인구'] * 100).round(2)

# 서울 행정구역 GeoJSON
print("  행정구역 GeoJSON 로드...")
resp = requests.get(
    "https://raw.githubusercontent.com/southkorea/seoul-maps/"
    "master/kostat/2013/json/seoul_municipalities_geo_simple.json",
    timeout=30
)
seoul_gdf = gpd.GeoDataFrame.from_features(
    resp.json()['features'], crs=CRS_WGS84
).rename(columns={'name':'구명'})

# 구별 공원 면적 합계 / 1인당 녹지 지수
park_area_gu = parks_df.groupby('지역')['면적_m2'].agg(
    공원수=('count'),
    공원면적_m2=('sum')
).reset_index().rename(columns={'지역':'구명'})

master = elderly_gu.merge(park_area_gu, on='구명', how='left')
master['공원수']       = master['공원수'].fillna(0)
master['공원면적_m2'] = master['공원면적_m2'].fillna(0)
master['green_index']  = (master['공원면적_m2'] / master['65세이상인구']).round(2)

# 공원 GeoDataFrame
parks_gdf = gpd.GeoDataFrame(
    parks_df,
    geometry=gpd.points_from_xy(parks_df['X_WGS84'], parks_df['Y_WGS84']),
    crs=CRS_WGS84
)
parks_korea = parks_gdf.to_crs(CRS_KOREA)
seoul_korea = seoul_gdf.to_crs(CRS_KOREA)

print(f"  서울 내 공원 {len(parks_df)}개, 총면적 {parks_df['면적_m2'].sum():,.0f}㎡")

# ============================================================
# ① Folium 인터랙티브 지도
# ============================================================
print("Folium 지도 생성 중...")

m = folium.Map(location=[37.5665, 126.9780], zoom_start=11,
               tiles='CartoDB positron')

# 녹지지수 Choropleth
seoul_plot = seoul_gdf.merge(master[['구명','green_index','공원수','공원면적_m2']], on='구명', how='left')

folium.Choropleth(
    geo_data=seoul_plot.to_json(),
    data=master,
    columns=['구명','green_index'],
    key_on='feature.properties.구명',
    fill_color='Greens',
    fill_opacity=0.7,
    line_opacity=0.4,
    legend_name='1인당 녹지면적 (㎡/65세이상인구)',
    name='녹지지수 단계구분도'
).add_to(m)

# 구 경계 + 툴팁
folium.GeoJson(
    seoul_plot.to_json(),
    style_function=lambda x: {'fillColor':'transparent','color':'#444','weight':1.5},
    tooltip=folium.GeoJsonTooltip(
        fields=['구명','green_index','공원수','공원면적_m2'],
        aliases=['자치구','녹지지수(㎡/인)','공원수(개)','공원면적(㎡)'],
        localize=True
    ),
    name='구 경계'
).add_to(m)

# 공원 버블 (원 크기 = 면적 비례, 색상 = 면적 크기)
max_area = parks_df['면적_m2'].max()
colormap = bc.LinearColormap(
    ['#a8d5a2','#3a9e4f','#1a5e22'],
    vmin=parks_df['면적_m2'].min(),
    vmax=max_area,
    caption='공원 면적 (㎡)'
)
colormap.add_to(m)

park_layer = folium.FeatureGroup(name='공원 위치 (버블 크기=면적)')
for _, row in parks_df.iterrows():
    r = max(4, min(28, np.sqrt(row['면적_m2']) / 45))
    folium.CircleMarker(
        location=[row['Y_WGS84'], row['X_WGS84']],
        radius=r,
        color='#1a5e22',
        weight=1,
        fill=True,
        fill_color=colormap(row['면적_m2']),
        fill_opacity=0.75,
        tooltip=f"<b>{row['공원명']}</b><br>면적: {row['면적_m2']:,.0f}㎡<br>지역: {row['지역']}",
        popup=(
            f"<b>{row['공원명']}</b><br>"
            f"면적: {row['면적_m2']:,.0f}㎡<br>"
            f"지역: {row['지역']}<br>"
            f"주소: {row['공원주소']}"
        )
    ).add_to(park_layer)
park_layer.add_to(m)

# 400m / 800m 버퍼 레이어 (상위 15개 공원)
top15 = parks_gdf.nlargest(15, '면적_m2').to_crs(CRS_KOREA)

buf_400_layer = folium.FeatureGroup(name='공원 400m 보행권 버퍼', show=False)
buf_800_layer = folium.FeatureGroup(name='공원 800m 보행권 버퍼', show=False)

for _, row in top15.iterrows():
    buf400 = gpd.GeoDataFrame(
        geometry=[row.geometry.buffer(400)], crs=CRS_KOREA
    ).to_crs(CRS_WGS84)
    buf800 = gpd.GeoDataFrame(
        geometry=[row.geometry.buffer(800)], crs=CRS_KOREA
    ).to_crs(CRS_WGS84)

    folium.GeoJson(
        buf400.geometry.__geo_interface__,
        style_function=lambda x: {
            'fillColor':'#2ca02c','color':'#2ca02c',
            'weight':1,'fillOpacity':0.18
        },
        tooltip=f"{row['공원명']} 400m"
    ).add_to(buf_400_layer)

    folium.GeoJson(
        buf800.geometry.__geo_interface__,
        style_function=lambda x: {
            'fillColor':'#98df8a','color':'#98df8a',
            'weight':1,'fillOpacity':0.10
        },
        tooltip=f"{row['공원명']} 800m"
    ).add_to(buf_800_layer)

buf_400_layer.add_to(m)
buf_800_layer.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)

map_path = os.path.join(OUTPUT_DIR, 'park_accessibility_map.html')
m.save(map_path)
print(f"  지도 저장: {map_path}")

# ============================================================
# ② 정적 시각화 차트 (2행 2열)
# ============================================================
print("정적 차트 생성 중...")

master_s = master.sort_values('green_index', ascending=False)
# 버퍼 커버리지 계산 (구별)
from shapely.ops import unary_union

def park_coverage(parks_k, seoul_k, radius):
    res = []
    for _, gu in seoul_k.iterrows():
        parks_in_gu = parks_k[parks_k['지역'] == gu['구명']]
        if parks_in_gu.empty:
            res.append({'구명': gu['구명'], 'cov': 0.0})
            continue
        bufs = parks_in_gu.geometry.buffer(radius)
        union = unary_union(bufs.tolist())
        inter = gu.geometry.intersection(union)
        res.append({'구명': gu['구명'], 'cov': inter.area / gu.geometry.area * 100})
    return pd.DataFrame(res)

cov400 = park_coverage(parks_korea, seoul_korea, 400).rename(columns={'cov':'cov_400'})
cov800 = park_coverage(parks_korea, seoul_korea, 800).rename(columns={'cov':'cov_800'})
master_s = master_s.merge(cov400, on='구명', how='left').merge(cov800, on='구명', how='left')

fig, axes = plt.subplots(2, 2, figsize=(20, 14))
fig.suptitle('서울시 자치구별 녹지·공원 접근성 분석', fontsize=16, fontweight='bold', y=0.98)

# ── (1) 1인당 녹지면적 수평 막대 ─────────────────────────────
ax = axes[0, 0]
bars = ax.barh(
    master_s['구명'],
    master_s['green_index'],
    color=[('#1a5e22' if v >= 50 else '#3a9e4f' if v >= 20 else '#ff7f0e' if v >= 10 else '#d62728')
           for v in master_s['green_index']]
)
ax.set_title('자치구별 65세이상 1인당 녹지면적 (㎡/인)', fontsize=12, fontweight='bold')
ax.set_xlabel('1인당 녹지면적 (㎡/인)')
ax.axvline(master['green_index'].mean(), color='navy', linestyle='--',
           linewidth=1.5, label=f"서울 평균 {master['green_index'].mean():.1f}㎡/인")
ax.legend(fontsize=9)
for bar, val in zip(bars, master_s['green_index']):
    ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
            f'{val:.1f}', va='center', fontsize=8)
ax.set_xlim(0, master_s['green_index'].max() * 1.15)

# ── (2) 공원 수 vs 고령인구 버블 차트 ──────────────────────────
ax = axes[0, 1]
sc = ax.scatter(
    master_s['공원수'],
    master_s['65세이상인구'],
    c=master_s['green_index'],
    cmap='Greens',
    s=master_s['고령화율'] * 18,
    alpha=0.85,
    edgecolors='black',
    linewidths=0.5,
    vmin=0, vmax=master_s['green_index'].max()
)
for _, row in master_s.iterrows():
    ax.annotate(row['구명'], (row['공원수'], row['65세이상인구']),
                fontsize=7.5, ha='center', va='bottom')
plt.colorbar(sc, ax=ax, label='1인당 녹지면적 (㎡/인)')
ax.set_xlabel('공원 수 (개)')
ax.set_ylabel('65세이상 인구 (명)')
ax.set_title('공원 수 vs 65세이상 인구\n(원 크기: 고령화율)', fontsize=12, fontweight='bold')

# ── (3) 400m·800m 보행권 커버리지 막대 ──────────────────────
ax = axes[1, 0]
ms2 = master_s.sort_values('cov_400', ascending=True)
y    = np.arange(len(ms2))
h    = 0.35
ax.barh(y + h/2, ms2['cov_800'], h, label='800m 커버리지', color='#a8d5a2', alpha=0.85)
ax.barh(y - h/2, ms2['cov_400'], h, label='400m 커버리지', color='#1a5e22', alpha=0.85)
ax.set_yticks(y)
ax.set_yticklabels(ms2['구명'], fontsize=8.5)
ax.set_xlabel('보행권 커버리지 (%)')
ax.set_title('자치구별 공원 보행권 커버리지\n(400m ≈ 도보 10분 / 800m ≈ 도보 20분)', fontsize=12, fontweight='bold')
ax.axvline(50, color='red', linestyle='--', linewidth=1.2, alpha=0.7, label='50% 기준선')
ax.legend(fontsize=9)
ax.set_xlim(0, 105)

# ── (4) 공원면적 TOP 10 막대 ───────────────────────────────────
ax = axes[1, 1]
top10 = parks_df.nlargest(10, '면적_m2')[['공원명','지역','면적_m2']].copy()
top10['공원명_지역'] = top10.apply(lambda r: f"{r['공원명']}\n({r['지역']})", axis=1)
colors10 = plt.cm.Greens(np.linspace(0.4, 0.9, 10))[::-1]
bars10 = ax.barh(top10['공원명_지역'], top10['면적_m2'] / 10000, color=colors10)
ax.set_xlabel('면적 (만 ㎡)')
ax.set_title('면적 상위 10개 공원', fontsize=12, fontweight='bold')
for bar, val in zip(bars10, top10['면적_m2'] / 10000):
    ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
            f'{val:.1f}만㎡', va='center', fontsize=8.5)
ax.set_xlim(0, top10['면적_m2'].max() / 10000 * 1.3)
ax.invert_yaxis()

plt.tight_layout(rect=[0, 0, 1, 0.97])
chart_path = os.path.join(OUTPUT_DIR, 'park_analysis_chart.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  차트 저장: {chart_path}")

# 결과 요약 출력
print("\n" + "=" * 55)
print("▣ 서울시 공원·녹지 분석 요약")
print("=" * 55)
print(f"  분석 대상 공원 수  : {len(parks_df)}개")
print(f"  총 공원 면적       : {parks_df['면적_m2'].sum()/10000:,.1f}만㎡")
print(f"  65세이상 1인당 평균: {master['green_index'].mean():.1f}㎡/인")
top_gu    = master_s.iloc[0]
bottom_gu = master_s.iloc[-1]
print(f"\n  녹지지수 최고 자치구: {top_gu['구명']} ({top_gu['green_index']:.1f}㎡/인)")
print(f"  녹지지수 최저 자치구: {bottom_gu['구명']} ({bottom_gu['green_index']:.1f}㎡/인)")
print("\n  구별 400m 보행권 커버리지 하위 5개:")
for _, r in master_s.sort_values('cov_400').head(5).iterrows():
    print(f"    {r['구명']:6s}  {r['cov_400']:.1f}%")
print("=" * 55)
print("완료!")
