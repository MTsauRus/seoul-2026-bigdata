"""
서울시 노인여가복지시설 접근성 시각화
======================================
복지시설 분포 / 구별 복지지수 / 보행권 버퍼를 단독 파일로 출력
"""

import warnings
warnings.filterwarnings('ignore')

import io, os, re
import pandas as pd
import geopandas as gpd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import koreanize_matplotlib
import folium
import branca.colormap as bc
import requests
from shapely.ops import unary_union

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CRS_WGS84 = "EPSG:4326"
CRS_KOREA = "EPSG:5179"

# ── 자치구 좌표 (지오코딩 대신 대표 중심점 사용) ────────────
GU_CENTERS = {
    '종로구':(37.5930,126.9780),'중구':(37.5640,126.9975),
    '용산구':(37.5320,126.9900),'성동구':(37.5633,127.0369),
    '광진구':(37.5384,127.0822),'동대문구':(37.5744,127.0396),
    '중랑구':(37.6063,127.0927),'성북구':(37.5894,127.0167),
    '강북구':(37.6396,127.0257),'도봉구':(37.6688,127.0470),
    '노원구':(37.6542,127.0568),'은평구':(37.6177,126.9227),
    '서대문구':(37.5794,126.9368),'마포구':(37.5638,126.9084),
    '양천구':(37.5170,126.8664),'강서구':(37.5509,126.8496),
    '구로구':(37.4954,126.8874),'금천구':(37.4519,126.9018),
    '영등포구':(37.5264,126.8963),'동작구':(37.5124,126.9393),
    '관악구':(37.4784,126.9516),'서초구':(37.4836,127.0326),
    '강남구':(37.5172,127.0473),'송파구':(37.5145,127.1059),
    '강동구':(37.5301,127.1238),
}

# ============================================================
# 데이터 로드
# ============================================================
print("데이터 로드 중...")

# 복지시설 CSV
welfare_path = os.path.join(BASE_DIR, "서울시 사회복지시설(노인여가복지시설) 목록.csv")
with open(welfare_path, 'rb') as f:
    raw = f.read()
welfare_text = raw.decode('euc-kr')
welfare_df = pd.read_csv(io.StringIO(welfare_text))
welfare_df.columns = [
    '시설명','시설코드','시설유형','시설종류상세',
    '자치구구분','시군구코드','시군구명','시설주소',
    '전화번호','우편번호'
]
welfare_df = welfare_df[welfare_df['자치구구분'] == '자치구'].copy()
welfare_df['시설주소'] = welfare_df['시설주소'].fillna('').str.strip()
welfare_df = welfare_df[welfare_df['시설주소'] != '']

# 간략 유형 라벨
def short_type(t):
    if '경로당' in t:     return '경로당'
    if '소규모' in t:     return '경로당(소규모)'
    return '노인복지관'

welfare_df['유형_간략'] = welfare_df['시설유형'].apply(short_type)

# 고령인구
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

# 서울 행정구역
print("  행정구역 GeoJSON 로드...")
resp = requests.get(
    "https://raw.githubusercontent.com/southkorea/seoul-maps/"
    "master/kostat/2013/json/seoul_municipalities_geo_simple.json",
    timeout=30
)
seoul_gdf = gpd.GeoDataFrame.from_features(
    resp.json()['features'], crs=CRS_WGS84
).rename(columns={'name':'구명'})

# 구별 시설 집계
welfare_count = welfare_df.groupby('시군구명').agg(
    시설수=('시설명','count')
).reset_index().rename(columns={'시군구명':'구명'})

welfare_type = welfare_df.groupby(['시군구명','유형_간략']).size().unstack(fill_value=0).reset_index()
welfare_type.rename(columns={'시군구명':'구명'}, inplace=True)

master = elderly_gu.merge(welfare_count, on='구명', how='left')
master['시설수'] = master['시설수'].fillna(0)
master['welfare_index'] = (master['시설수'] / master['65세이상인구'] * 10000).round(3)
master = master.merge(welfare_type, on='구명', how='left')

# 복지시설 GeoDataFrame (구 중심점 근사)
welfare_df['lat'] = welfare_df['시군구명'].map(lambda g: GU_CENTERS.get(g, (np.nan, np.nan))[0])
welfare_df['lng'] = welfare_df['시군구명'].map(lambda g: GU_CENTERS.get(g, (np.nan, np.nan))[1])

# 구 중심점에 ±0.01도 무작위 오프셋 (같은 점 겹침 방지)
rng = np.random.default_rng(42)
welfare_df['lat'] = welfare_df['lat'] + rng.uniform(-0.018, 0.018, len(welfare_df))
welfare_df['lng'] = welfare_df['lng'] + rng.uniform(-0.018, 0.018, len(welfare_df))

welfare_gdf = gpd.GeoDataFrame(
    welfare_df,
    geometry=gpd.points_from_xy(welfare_df['lng'], welfare_df['lat']),
    crs=CRS_WGS84
)
welfare_korea = welfare_gdf.to_crs(CRS_KOREA)
seoul_korea   = seoul_gdf.to_crs(CRS_KOREA)

print(f"  복지시설 {len(welfare_df)}개 로드 완료")

# 구별 복지시설 보행권 커버리지
def welfare_coverage(welf_k, seoul_k, radius):
    res = []
    for _, gu in seoul_k.iterrows():
        welf_in = welf_k[welf_k['시군구명'] == gu['구명']]
        if welf_in.empty:
            res.append({'구명': gu['구명'], 'cov': 0.0})
            continue
        bufs  = welf_in.geometry.buffer(radius)
        union = unary_union(bufs.tolist())
        inter = gu.geometry.intersection(union)
        res.append({'구명': gu['구명'], 'cov': inter.area / gu.geometry.area * 100})
    return pd.DataFrame(res)

print("  보행권 커버리지 계산 중...")
cov400 = welfare_coverage(welfare_korea, seoul_korea, 400).rename(columns={'cov':'cov_400'})
cov800 = welfare_coverage(welfare_korea, seoul_korea, 800).rename(columns={'cov':'cov_800'})
master = master.merge(cov400, on='구명', how='left').merge(cov800, on='구명', how='left')

# ============================================================
# ① Folium 인터랙티브 지도
# ============================================================
print("Folium 지도 생성 중...")

m = folium.Map(location=[37.5665, 126.9780], zoom_start=11,
               tiles='CartoDB positron')

# 복지지수 Choropleth
seoul_plot = seoul_gdf.merge(
    master[['구명','welfare_index','시설수','65세이상인구','고령화율','cov_400']],
    on='구명', how='left'
)

folium.Choropleth(
    geo_data=seoul_plot.to_json(),
    data=master,
    columns=['구명','welfare_index'],
    key_on='feature.properties.구명',
    fill_color='Blues',
    fill_opacity=0.7,
    line_opacity=0.4,
    legend_name='복지시설 지수 (1만명당 시설 수)',
    name='복지시설 지수 단계구분도'
).add_to(m)

# 구 경계 + 툴팁
folium.GeoJson(
    seoul_plot.to_json(),
    style_function=lambda x: {'fillColor':'transparent','color':'#333','weight':1.5},
    tooltip=folium.GeoJsonTooltip(
        fields=['구명','welfare_index','시설수','65세이상인구','고령화율','cov_400'],
        aliases=['자치구','복지지수(1만명당)','시설수(개)','65세이상인구','고령화율(%)','400m커버(%)'],
        localize=True
    ),
    name='구 경계'
).add_to(m)

# 시설 타입별 색상
TYPE_COLOR = {
    '노인복지관':  '#1f77b4',
    '경로당':      '#ff7f0e',
    '경로당(소규모)': '#aec7e8'
}
TYPE_ICON = {
    '노인복지관':  'home',
    '경로당':      'user',
    '경로당(소규모)': 'leaf'
}

# 시설 마커 레이어 (유형별 분리)
for wtype, color in TYPE_COLOR.items():
    layer = folium.FeatureGroup(name=f'시설 유형: {wtype}')
    sub = welfare_df[welfare_df['유형_간략'] == wtype]
    for _, row in sub.iterrows():
        if pd.isna(row['lat']): continue
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=7 if wtype == '노인복지관' else 5,
            color=color,
            weight=1.5,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            tooltip=f"<b>{row['시설명']}</b><br>{wtype}<br>{row['시군구명']}",
            popup=(
                f"<b>{row['시설명']}</b><br>"
                f"유형: {wtype}<br>"
                f"구: {row['시군구명']}<br>"
                f"주소: {row['시설주소']}"
            )
        ).add_to(layer)
    layer.add_to(m)

# 복지시설 400m / 800m 버퍼 레이어 (노인복지관만)
welfare_wc = welfare_df[welfare_df['유형_간략'] == '노인복지관']
welfare_wc_k = welfare_gdf[welfare_gdf['유형_간략'] == '노인복지관'].to_crs(CRS_KOREA)

buf_400_layer = folium.FeatureGroup(name='노인복지관 400m 보행권 버퍼', show=False)
buf_800_layer = folium.FeatureGroup(name='노인복지관 800m 보행권 버퍼', show=False)

for _, row in welfare_wc_k.iterrows():
    for layer, radius, color, op in [
        (buf_400_layer, 400, '#1f77b4', 0.20),
        (buf_800_layer, 800, '#aec7e8', 0.12)
    ]:
        buf = gpd.GeoDataFrame(
            geometry=[row.geometry.buffer(radius)], crs=CRS_KOREA
        ).to_crs(CRS_WGS84)
        folium.GeoJson(
            buf.geometry.__geo_interface__,
            style_function=lambda x, c=color, o=op: {
                'fillColor': c, 'color': c, 'weight': 1, 'fillOpacity': o
            },
            tooltip=f"{row['시설명']} {radius}m"
        ).add_to(layer)

buf_400_layer.add_to(m)
buf_800_layer.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)

map_path = os.path.join(OUTPUT_DIR, 'welfare_accessibility_map.html')
m.save(map_path)
print(f"  지도 저장: {map_path}")

# ============================================================
# ② 정적 시각화 차트 (2행 2열)
# ============================================================
print("정적 차트 생성 중...")

master_s = master.sort_values('welfare_index', ascending=False)

fig, axes = plt.subplots(2, 2, figsize=(20, 14))
fig.suptitle('서울시 자치구별 노인여가복지시설 접근성 분석', fontsize=16, fontweight='bold', y=0.98)

# ── (1) 구별 복지시설 지수 막대 ───────────────────────────────
ax = axes[0, 0]
bars = ax.barh(
    master_s['구명'],
    master_s['welfare_index'],
    color=[('#1a3a6e' if v >= 2.0 else '#2878b8' if v >= 1.0 else '#ff7f0e' if v >= 0.5 else '#d62728')
           for v in master_s['welfare_index']]
)
mean_wi = master['welfare_index'].mean()
ax.axvline(mean_wi, color='black', linestyle='--', linewidth=1.5,
           label=f'서울 평균 {mean_wi:.2f}개소')
ax.set_title('자치구별 복지시설 지수\n(65세이상 1만명당 시설 수)', fontsize=12, fontweight='bold')
ax.set_xlabel('복지시설 지수 (개소/1만명)')
ax.legend(fontsize=9)
for bar, val in zip(bars, master_s['welfare_index']):
    ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height()/2,
            f'{val:.2f}', va='center', fontsize=8)
ax.set_xlim(0, master_s['welfare_index'].max() * 1.18)

# ── (2) 시설 수 vs 고령인구 (시설 유형별 누적 가로 막대) ────
ax = axes[0, 1]
ms_sorted = master.sort_values('65세이상인구', ascending=True)
type_cols = [c for c in ['경로당','경로당(소규모)','노인복지관'] if c in ms_sorted.columns]
palette = ['#ff7f0e','#aec7e8','#1f77b4']
left = np.zeros(len(ms_sorted))
for col, color in zip(type_cols, palette):
    vals = ms_sorted[col].fillna(0).values
    ax.barh(ms_sorted['구명'], vals, left=left, color=color, label=col, alpha=0.88)
    left += vals
ax.set_xlabel('시설 수 (개)')
ax.set_title('자치구별 유형별 복지시설 수\n(65세이상 인구 순 정렬)', fontsize=12, fontweight='bold')
ax.legend(loc='lower right', fontsize=9)
# 우측에 65세이상인구 표기
ax2 = ax.twiny()
ax2.scatter(ms_sorted['65세이상인구'], ms_sorted['구명'],
            marker='D', color='red', s=35, zorder=5, label='65세이상인구')
ax2.set_xlabel('65세이상 인구 (명)', color='red')
ax2.tick_params(axis='x', colors='red')
ax2.legend(loc='upper right', fontsize=9)

# ── (3) 400m·800m 복지시설 커버리지 ────────────────────────
ax = axes[1, 0]
ms3 = master_s.sort_values('cov_400', ascending=True)
y  = np.arange(len(ms3))
h  = 0.35
ax.barh(y + h/2, ms3['cov_800'], h, label='800m 커버리지', color='#aec7e8', alpha=0.85)
ax.barh(y - h/2, ms3['cov_400'], h, label='400m 커버리지', color='#1f77b4', alpha=0.85)
ax.set_yticks(y)
ax.set_yticklabels(ms3['구명'], fontsize=8.5)
ax.set_xlabel('보행권 커버리지 (%)')
ax.set_title('자치구별 복지시설 보행권 커버리지\n(400m ≈ 도보 10분 / 800m ≈ 도보 20분)', fontsize=12, fontweight='bold')
ax.axvline(50, color='red', linestyle='--', linewidth=1.2, alpha=0.7, label='50% 기준선')
ax.legend(fontsize=9)
ax.set_xlim(0, 105)

# ── (4) 고령화율 vs 복지지수 산점도 ─────────────────────────
ax = axes[1, 1]
sc = ax.scatter(
    master_s['고령화율'],
    master_s['welfare_index'],
    c=master_s['시설수'],
    cmap='Blues',
    s=master_s['65세이상인구'] / 4000,
    alpha=0.85,
    edgecolors='black',
    linewidths=0.5,
    vmin=0, vmax=master_s['시설수'].max()
)
for _, row in master_s.iterrows():
    ax.annotate(row['구명'], (row['고령화율'], row['welfare_index']),
                fontsize=7.5, ha='center', va='bottom')
plt.colorbar(sc, ax=ax, label='시설 수 (개)')
ax.set_xlabel('고령화율 (%)')
ax.set_ylabel('복지시설 지수 (개소/1만명)')
ax.set_title('고령화율 vs 복지시설 지수\n(원 크기: 65세이상 인구 규모)', fontsize=12, fontweight='bold')
# 사분면 구분선
ax.axvline(master['고령화율'].median(), color='gray', linestyle=':', linewidth=1.2,
           label=f"고령화율 중앙값 {master['고령화율'].median():.1f}%")
ax.axhline(master['welfare_index'].median(), color='gray', linestyle='--', linewidth=1.2,
           label=f"복지지수 중앙값 {master['welfare_index'].median():.2f}")
# 사분면 레이블
xlim, ylim = ax.get_xlim(), ax.get_ylim()
xmid = master['고령화율'].median()
ymid = master['welfare_index'].median()
ax.text(xlim[0]+0.1, ylim[1]-0.05, '낮은고령화\n높은복지', fontsize=8,
        color='green', ha='left', va='top')
ax.text(xlim[1]-0.1, ylim[1]-0.05, '높은고령화\n높은복지', fontsize=8,
        color='blue', ha='right', va='top')
ax.text(xlim[0]+0.1, ylim[0]+0.05, '낮은고령화\n낮은복지', fontsize=8,
        color='gray', ha='left', va='bottom')
ax.text(xlim[1]-0.1, ylim[0]+0.05, '높은고령화\n낮은복지', fontsize=8,
        color='red', ha='right', va='bottom', fontweight='bold')
ax.legend(fontsize=8)

plt.tight_layout(rect=[0, 0, 1, 0.97])
chart_path = os.path.join(OUTPUT_DIR, 'welfare_analysis_chart2.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  차트 저장: {chart_path}")

# 결과 요약 출력
print("\n" + "=" * 55)
print("▣ 서울시 복지시설 분석 요약")
print("=" * 55)
print(f"  분석 대상 시설 수  : {len(welfare_df)}개")
print(f"  - 노인복지관       : {(welfare_df['유형_간략']=='노인복지관').sum()}개")
print(f"  - 경로당           : {(welfare_df['유형_간략']=='경로당').sum()}개")
print(f"  - 경로당(소규모)   : {(welfare_df['유형_간략']=='경로당(소규모)').sum()}개")
print(f"  서울 평균 복지지수 : 1만명당 {master['welfare_index'].mean():.2f}개소")
ms_s = master.sort_values('welfare_index', ascending=False)
print(f"\n  복지지수 최고: {ms_s.iloc[0]['구명']} ({ms_s.iloc[0]['welfare_index']:.2f}개소/1만명)")
print(f"  복지지수 최저: {ms_s.iloc[-1]['구명']} ({ms_s.iloc[-1]['welfare_index']:.2f}개소/1만명)")
print("\n  400m 보행권 커버리지 하위 5개:")
for _, r in master.sort_values('cov_400').head(5).iterrows():
    print(f"    {r['구명']:6s}  {r['cov_400']:.1f}%  (시설수: {int(r['시설수'])}개)")
print("=" * 55)
print("완료!")
