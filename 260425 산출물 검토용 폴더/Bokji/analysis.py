"""
서울시 노인 생활복지 및 녹지 접근성 분석 파이프라인
=======================================================
instruction.md의 Step 1~6 구현
"""

# ============================================================
# Step 1: 환경 설정 및 라이브러리 로드
# ============================================================
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import koreanize_matplotlib          # 한글 폰트 자동 설정
import requests
import json
import re
import time
import os
import io

print("=" * 60)
print("Step 1: 라이브러리 로드 완료")
print(f"  - geopandas: {gpd.__version__}")
print(f"  - folium: {folium.__version__}")
print(f"  - matplotlib: {matplotlib.__version__}")
print("=" * 60)

# 작업 디렉토리 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 좌표계 설정
CRS_WGS84  = "EPSG:4326"
CRS_KOREA  = "EPSG:5179"   # Korea 2000 / Central Belt (거리 계산 m 단위)


# ============================================================
# Step 2: 데이터 로드 및 전처리
# ============================================================
print("\nStep 2: 데이터 로드 및 전처리 시작")

# ── 2-1. 복지시설 데이터 ──────────────────────────────────────
welfare_path = os.path.join(BASE_DIR, "서울시 사회복지시설(노인여가복지시설) 목록.csv")
with open(welfare_path, 'rb') as f:
    raw = f.read()
welfare_text = raw.decode('euc-kr')

welfare_df = pd.read_csv(io.StringIO(welfare_text))
welfare_df.columns = [
    '시설명', '시설코드', '시설유형', '시설종류상세',
    '자치구구분', '시군구코드', '시군구명', '시설주소',
    '전화번호', '우편번호'
]
# 서울시 자치구만 필터 (자치구 = 자치구)
welfare_df = welfare_df[welfare_df['자치구구분'] == '자치구'].copy()
welfare_df['시설주소'] = welfare_df['시설주소'].fillna('').str.strip()
welfare_df = welfare_df[welfare_df['시설주소'] != '']
print(f"  복지시설 총 {len(welfare_df)}개 로드 완료")
print(f"  시설유형 분포:\n{welfare_df['시설유형'].value_counts().to_string()}")

# ── 2-2. 공원 데이터 ─────────────────────────────────────────
parks_path = os.path.join(BASE_DIR, "서울시 주요 공원현황(2026 상반기).xlsx")
parks_raw = pd.read_excel(parks_path)
parks_raw.columns = [
    '연번', '관리부서', '전화번호', '공원명', '공원개요',
    '면적', '개원일', '주요시설', '주요식물', '안내도',
    '오시는길', '이용시참고사항', '이미지', '지역', '공원주소',
    'X_GRS80', 'Y_GRS80', 'X_WGS84', 'Y_WGS84', '바로가기'
]

# 면적 파싱 (첫 번째 숫자 추출, ㎡ or m² 단위)
def parse_area(val):
    if pd.isna(val):
        return np.nan
    s = str(val)
    m = re.search(r'[\d,]+\.?\d*', s.replace(',', ''))
    if m:
        return float(m.group().replace(',', ''))
    return np.nan

parks_raw['면적_m2'] = parks_raw['면적'].apply(parse_area)

# 서울 내 공원만 (지역 컬럼이 서울 자치구명인 경우)
seoul_gu_list = [
    '종로구','중구','용산구','성동구','광진구','동대문구','중랑구',
    '성북구','강북구','도봉구','노원구','은평구','서대문구','마포구',
    '양천구','강서구','구로구','금천구','영등포구','동작구','관악구',
    '서초구','강남구','송파구','강동구'
]
parks_df = parks_raw[parks_raw['지역'].isin(seoul_gu_list)].copy()
parks_df = parks_df.dropna(subset=['X_WGS84', 'Y_WGS84', '면적_m2'])
parks_df = parks_df[parks_df['X_WGS84'] > 0]
print(f"\n  서울 내 공원 {len(parks_df)}개 로드 완료")
print(f"  총 공원 면적: {parks_df['면적_m2'].sum():,.0f} ㎡")

# ── 2-3. 고령인구 데이터 ─────────────────────────────────────
elderly_path = os.path.join(BASE_DIR, "고령자현황_20260421103806.csv")
elderly_raw = pd.read_csv(elderly_path, encoding='utf-8-sig', header=None)

# 컬럼명 수동 지정 (4줄 헤더 구조)
# col0=동별1, col1=동별2(구), col2=동별3(동), col3=전체인구, col6=65세이상
elderly_raw.columns = [
    '구분1','구명','동명',
    '전체인구','전체_남','전체_여',
    '65세이상','65세이상_남','65세이상_여',
    '내국인_65','내국인_65남','내국인_65여',
    '외국인_65','외국인_65남','외국인_65여'
]

# 4행 헤더 제거 후 데이터 행만 추출
elderly_data = elderly_raw.iloc[4:].copy()
elderly_data = elderly_data[elderly_data['구명'] != '소계']
elderly_data = elderly_data[elderly_data['동명'] != '소계']

# 숫자 변환
for col in ['전체인구','65세이상']:
    elderly_data[col] = pd.to_numeric(elderly_data[col].astype(str).str.replace(',',''), errors='coerce')

elderly_data = elderly_data.dropna(subset=['65세이상'])

# 자치구별 집계 (동 단위 → 구 단위)
elderly_gu = elderly_data.groupby('구명').agg(
    전체인구=('전체인구', 'sum'),
    pop_65=('65세이상', 'sum')
).reset_index()
elderly_gu.rename(columns={'pop_65': '65세이상인구'}, inplace=True)
elderly_gu['고령화율'] = (elderly_gu['65세이상인구'] / elderly_gu['전체인구'] * 100).round(2)

print(f"\n  고령인구 데이터 로드: {len(elderly_gu)}개 자치구")
print(f"  서울 전체 65세이상: {elderly_gu['65세이상인구'].sum():,}명")

# ── 2-4. 서울시 행정구역 GeoJSON 로드 ────────────────────────
geojson_url = (
    "https://raw.githubusercontent.com/southkorea/seoul-maps/"
    "master/kostat/2013/json/seoul_municipalities_geo_simple.json"
)
print(f"\n  서울 행정구역 GeoJSON 다운로드 중...")
resp = requests.get(geojson_url, timeout=30)
geojson_data = resp.json()

# GeoDataFrame 생성
seoul_gdf = gpd.GeoDataFrame.from_features(geojson_data['features'], crs=CRS_WGS84)
seoul_gdf.rename(columns={'name': '구명'}, inplace=True)

# 구명 인코딩 수정 (unicode escape → 정상 한글)
# GeoJSON의 name이 이미 유니코드이므로 OK
print(f"  행정구역 GeoDF: {len(seoul_gdf)}개 구 로드")

# ── 2-5. GeoDataFrame 생성 (복지시설 / 공원) ─────────────────
# 공원 GeoDataFrame (좌표 이미 보유)
parks_gdf = gpd.GeoDataFrame(
    parks_df,
    geometry=gpd.points_from_xy(parks_df['X_WGS84'], parks_df['Y_WGS84']),
    crs=CRS_WGS84
)

# 복지시설: 구 centroid 사용 (실주소 지오코딩 대신 구 중심점 근사)
# – 실제 프로덕션에서는 Nominatim/카카오 API로 주소 변환 권장 –
seoul_gdf_korea = seoul_gdf.to_crs(CRS_KOREA)
gu_centroids = seoul_gdf_korea.copy()
gu_centroids['centroid'] = gu_centroids.geometry.centroid
gu_centroids = gu_centroids[['구명', 'centroid']].rename(columns={'centroid': 'geometry'})
gu_centroids = gpd.GeoDataFrame(gu_centroids, geometry='geometry', crs=CRS_KOREA)

welfare_merged = welfare_df.merge(
    gu_centroids[['구명', 'geometry']].rename(columns={'구명': '시군구명'}),
    on='시군구명', how='left'
)
welfare_gdf = gpd.GeoDataFrame(welfare_merged, geometry='geometry', crs=CRS_KOREA)
welfare_gdf_wgs = welfare_gdf.to_crs(CRS_WGS84)

print(f"\n  복지시설 GeoDataFrame 생성: {len(welfare_gdf)}개 (구 중심점 근사)")
print(f"  공원 GeoDataFrame 생성: {len(parks_gdf)}개 (실좌표)")
print("Step 2 완료")


# ============================================================
# Step 3: 공간 접근성 분석
# ============================================================
print("\nStep 3: 공간 접근성 분석 시작")

# EPSG:5179 변환
parks_korea  = parks_gdf.to_crs(CRS_KOREA)
welfare_korea = welfare_gdf   # 이미 5179

# ── 3-1. 버퍼 생성 (400m / 800m) ─────────────────────────────
parks_korea['buffer_400']  = parks_korea.geometry.buffer(400)
parks_korea['buffer_800']  = parks_korea.geometry.buffer(800)
welfare_korea['buffer_400'] = welfare_korea.geometry.buffer(400)
welfare_korea['buffer_800'] = welfare_korea.geometry.buffer(800)

# ── 3-2. 구별 공원 버퍼 합집합 ───────────────────────────────
park_buf_400 = gpd.GeoDataFrame(
    parks_korea[['지역']].copy(),
    geometry=parks_korea['buffer_400'],
    crs=CRS_KOREA
).rename(columns={'지역': '구명'})

park_buf_800 = gpd.GeoDataFrame(
    parks_korea[['지역']].copy(),
    geometry=parks_korea['buffer_800'],
    crs=CRS_KOREA
).rename(columns={'지역': '구명'})

# 구별 공원 버퍼 coverage (버퍼 합집합 면적 / 구 면적 * 100)
seoul_korea = seoul_gdf.to_crs(CRS_KOREA).copy()

def buf_coverage_by_gu(buf_gdf, gu_gdf):
    """구별 버퍼 커버리지 비율(%) 계산"""
    results = []
    for _, gu_row in gu_gdf.iterrows():
        gu_name  = gu_row['구명']
        gu_geom  = gu_row['geometry']
        gu_area  = gu_geom.area
        bufs = buf_gdf[buf_gdf['구명'] == gu_name]['geometry']
        if len(bufs) == 0:
            results.append({'구명': gu_name, '커버리지': 0.0})
            continue
        from shapely.ops import unary_union
        union = unary_union(bufs.tolist())
        intersect = gu_geom.intersection(union)
        results.append({'구명': gu_name, '커버리지': intersect.area / gu_area * 100})
    return pd.DataFrame(results)

cov_400 = buf_coverage_by_gu(park_buf_400, seoul_korea)
cov_800 = buf_coverage_by_gu(park_buf_800, seoul_korea)
cov_400.rename(columns={'커버리지': '공원커버리지_400m'}, inplace=True)
cov_800.rename(columns={'커버리지': '공원커버리지_800m'}, inplace=True)

print("  공원 버퍼 커버리지 계산 완료")

# ── 3-3. 복지시설 구별 집계 ──────────────────────────────────
welfare_count = welfare_df.groupby('시군구명').agg(
    시설수=('시설명','count')
).reset_index().rename(columns={'시군구명':'구명'})

print("Step 3 완료")


# ============================================================
# Step 4: 평가지표 및 스코어링
# ============================================================
print("\nStep 4: 평가지표 산출 시작")

# 구별 공원 면적 합계 (지역 컬럼 기준)
park_area_gu = parks_df.groupby('지역')['면적_m2'].sum().reset_index()
park_area_gu.rename(columns={'지역': '구명', '면적_m2': '공원면적_m2'}, inplace=True)

# 마스터 데이터프레임 병합
master = (
    elderly_gu
    .merge(welfare_count, on='구명', how='left')
    .merge(park_area_gu, on='구명', how='left')
    .merge(cov_400, on='구명', how='left')
    .merge(cov_800, on='구명', how='left')
)
master['시설수'] = master['시설수'].fillna(0)
master['공원면적_m2'] = master['공원면적_m2'].fillna(0)
master['공원커버리지_400m'] = master['공원커버리지_400m'].fillna(0)
master['공원커버리지_800m'] = master['공원커버리지_800m'].fillna(0)

# ── 4-1. Welfare Index ──────────────────────────────────────
# 시설 수 / 65세이상 인구 (1만명당 시설 수)
master['welfare_index'] = master['시설수'] / master['65세이상인구'] * 10000

# ── 4-2. Green Index ────────────────────────────────────────
# 65세이상 1인당 공원 면적 (㎡/인)
master['green_index'] = master['공원면적_m2'] / master['65세이상인구']

# ── 4-3. Vulnerability Score (Min-Max 정규화 후 가중 합산) ──
def minmax(series):
    mn, mx = series.min(), series.max()
    return (series - mn) / (mx - mn) if mx > mn else series * 0

# 지표 정규화 (낮을수록 취약 → 역수 정규화)
master['norm_welfare']    = minmax(master['welfare_index'])      # 높을수록 좋음
master['norm_green']      = minmax(master['green_index'])        # 높을수록 좋음
master['norm_aging_rate'] = minmax(master['고령화율'])           # 높을수록 취약
master['norm_cov_400']    = minmax(master['공원커버리지_400m'])  # 높을수록 좋음

# 결핍 지수 = 낮은 복지 + 낮은 녹지 + 높은 고령화율
# 가중치: 복지시설 40% + 녹지 30% + 고령화율 30%
master['vulnerability_score'] = (
    (1 - master['norm_welfare'])    * 0.40 +
    (1 - master['norm_green'])      * 0.30 +
    master['norm_aging_rate']       * 0.30
).round(4)

master_sorted = master.sort_values('vulnerability_score', ascending=False)

print("  평가지표 산출 완료")
print(master_sorted[['구명','시설수','65세이상인구','welfare_index','green_index','vulnerability_score']].to_string(index=False))
print("Step 4 완료")


# ============================================================
# Step 5: 데이터 시각화
# ============================================================
print("\nStep 5: 시각화 시작")

# ── 5-1. Folium 인터랙티브 지도 ──────────────────────────────
m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles='CartoDB positron')

# GeoJSON 병합 (vuln score)
seoul_plot = seoul_gdf.merge(
    master[['구명','vulnerability_score','welfare_index','green_index','65세이상인구','시설수']],
    on='구명', how='left'
)
geojson_str = seoul_plot.to_json()

# Choropleth (복지 결핍 지수)
folium.Choropleth(
    geo_data=geojson_str,
    data=master,
    columns=['구명', 'vulnerability_score'],
    key_on='feature.properties.구명',
    fill_color='YlOrRd',
    fill_opacity=0.7,
    line_opacity=0.5,
    legend_name='생활권 복지 결핍 지수 (높을수록 취약)',
    name='복지 결핍 지수 (Choropleth)',
    nan_fill_color='white'
).add_to(m)

# 구 경계 + 툴팁
style_fn = lambda x: {
    'fillColor': 'transparent',
    'color': '#555',
    'weight': 1.5
}
tooltip = folium.GeoJsonTooltip(
    fields=['구명', 'vulnerability_score', 'welfare_index', 'green_index', '65세이상인구', '시설수'],
    aliases=['자치구', '결핍지수', '복지지수(1만명당)', '녹지지수(㎡/인)', '65세이상인구', '복지시설수'],
    localize=True
)
folium.GeoJson(
    geojson_str,
    style_function=style_fn,
    tooltip=tooltip,
    name='구 경계'
).add_to(m)

# 공원 위치 (버블 차트: 면적 비례)
park_cluster = MarkerCluster(name='공원 위치').add_to(m)
for _, row in parks_df.iterrows():
    if pd.isna(row['X_WGS84']) or pd.isna(row['Y_WGS84']):
        continue
    radius = max(5, min(20, np.sqrt(row['면적_m2']) / 50))
    folium.CircleMarker(
        location=[row['Y_WGS84'], row['X_WGS84']],
        radius=radius,
        color='green',
        fill=True,
        fill_color='#2ca02c',
        fill_opacity=0.6,
        popup=f"<b>{row['공원명']}</b><br>면적: {row['면적_m2']:,.0f}㎡<br>지역: {row['지역']}",
        tooltip=row['공원명']
    ).add_to(park_cluster)

# 복지시설 위치 (구 중심점 집계 마커)
welfare_cluster = MarkerCluster(name='복지시설 위치').add_to(m)
for _, row in welfare_gdf_wgs.iterrows():
    if row.geometry is None:
        continue
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5,
        color='blue',
        fill=True,
        fill_color='#1f77b4',
        fill_opacity=0.5,
        popup=f"<b>{row['시설명']}</b><br>{row['시설유형']}<br>{row['시군구명']}",
        tooltip=row['시설명']
    ).add_to(welfare_cluster)

# 공원 800m 버퍼 레이어 (상위 10개만 표시)
buf_layer = folium.FeatureGroup(name='공원 800m 보행권 버퍼', show=False)
top_parks = parks_gdf.nlargest(10, '면적_m2')
top_parks_korea = top_parks.to_crs(CRS_KOREA)
top_parks_korea['buf800'] = top_parks_korea.geometry.buffer(800)
top_parks_buf_wgs = gpd.GeoDataFrame(
    top_parks_korea[['공원명']],
    geometry=top_parks_korea['buf800'],
    crs=CRS_KOREA
).to_crs(CRS_WGS84)

for _, row in top_parks_buf_wgs.iterrows():
    folium.GeoJson(
        row.geometry.__geo_interface__,
        style_function=lambda x: {
            'fillColor': '#2ca02c',
            'color': '#2ca02c',
            'weight': 1,
            'fillOpacity': 0.15
        },
        tooltip=f"{row['공원명']} 800m 버퍼"
    ).add_to(buf_layer)
buf_layer.add_to(m)

folium.LayerControl().add_to(m)

map_path = os.path.join(OUTPUT_DIR, 'seoul_welfare_map.html')
m.save(map_path)
print(f"  Folium 지도 저장: {map_path}")

# ── 5-2. 통계 차트 ───────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(18, 7))
fig.suptitle('서울시 자치구별 노인 복지·녹지 접근성 분석', fontsize=15, fontweight='bold')

# 막대 그래프: 자치구별 보행권 복지 결핍 지수
sorted_bar = master_sorted[['구명','vulnerability_score']].head(25)
colors = ['#d62728' if v > 0.6 else '#ff7f0e' if v > 0.4 else '#2ca02c'
          for v in sorted_bar['vulnerability_score']]
axes[0].barh(sorted_bar['구명'][::-1], sorted_bar['vulnerability_score'][::-1], color=colors[::-1])
axes[0].set_title('자치구별 생활권 복지 결핍 지수\n(높을수록 복지 취약)', fontsize=12)
axes[0].set_xlabel('결핍 지수 (0~1)')
axes[0].axvline(x=0.6, color='red', linestyle='--', alpha=0.7, label='고위험 (0.6)')
axes[0].axvline(x=0.4, color='orange', linestyle='--', alpha=0.7, label='중위험 (0.4)')
axes[0].legend()
axes[0].set_xlim(0, 1)

# 산점도: 65세이상 인구 vs welfare_index (시설 접근성)
sc = axes[1].scatter(
    master['welfare_index'],
    master['65세이상인구'],
    c=master['vulnerability_score'],
    cmap='YlOrRd',
    s=master['고령화율'] * 15,
    alpha=0.8,
    edgecolors='black',
    linewidths=0.5
)
for _, row in master.iterrows():
    axes[1].annotate(
        row['구명'],
        (row['welfare_index'], row['65세이상인구']),
        fontsize=7, ha='center', va='bottom'
    )
plt.colorbar(sc, ax=axes[1], label='결핍 지수')
axes[1].set_xlabel('복지시설 지수 (1만명당 시설 수)')
axes[1].set_ylabel('65세이상 인구 (명)')
axes[1].set_title('65세이상 인구 vs 복지시설 지수\n(원 크기: 고령화율, 색상: 결핍지수)', fontsize=12)

plt.tight_layout()
chart_path = os.path.join(OUTPUT_DIR, 'welfare_analysis_chart.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  통계 차트 저장: {chart_path}")

# ── 5-3. 복지지수 vs 녹지지수 2D 분포 ───────────────────────
fig2, ax2 = plt.subplots(figsize=(10, 8))
sc2 = ax2.scatter(
    master['welfare_index'],
    master['green_index'],
    c=master['vulnerability_score'],
    cmap='YlOrRd',
    s=120,
    alpha=0.85,
    edgecolors='black',
    linewidths=0.6
)
for _, row in master.iterrows():
    ax2.annotate(row['구명'], (row['welfare_index'], row['green_index']),
                 fontsize=8, ha='center', va='bottom')
plt.colorbar(sc2, ax=ax2, label='결핍 지수')
ax2.axvline(x=master['welfare_index'].median(), color='blue',
            linestyle='--', alpha=0.5, label='복지지수 중앙값')
ax2.axhline(y=master['green_index'].median(), color='green',
            linestyle='--', alpha=0.5, label='녹지지수 중앙값')
ax2.set_xlabel('복지시설 지수 (1만명당 시설 수)')
ax2.set_ylabel('녹지 지수 (1인당 공원 면적, ㎡/인)')
ax2.set_title('복지시설 지수 vs 녹지 지수 분포\n(색상: 복지 결핍 지수)', fontsize=12)
ax2.legend()
chart2_path = os.path.join(OUTPUT_DIR, 'welfare_green_scatter.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  산점도 차트 저장: {chart2_path}")

print("Step 5 완료")


# ============================================================
# Step 6: 최종 리포트 출력 및 CSV 저장
# ============================================================
print("\nStep 6: 최종 리포트 생성")

# TOP 5 복지시설 확충 시급 행정구
top5 = master_sorted.head(5)[
    ['구명','vulnerability_score','시설수','65세이상인구',
     'welfare_index','green_index','고령화율','공원커버리지_400m']
].reset_index(drop=True)

print("\n" + "=" * 70)
print("▣ 복지시설 확충이 가장 시급한 자치구 TOP 5")
print("=" * 70)
for rank, row in top5.iterrows():
    print(f"\n  [{rank+1}위] {row['구명']}")
    print(f"    - 결핍 지수       : {row['vulnerability_score']:.4f}")
    print(f"    - 65세이상 인구   : {row['65세이상인구']:,.0f}명  "
          f"(고령화율 {row['고령화율']:.1f}%)")
    print(f"    - 복지시설 수     : {row['시설수']:.0f}개")
    print(f"    - 복지지수(1만명당): {row['welfare_index']:.2f}개소")
    print(f"    - 녹지지수(1인당) : {row['green_index']:.1f} ㎡/인")
    print(f"    - 공원 400m 커버  : {row['공원커버리지_400m']:.1f}%")

print("\n" + "=" * 70)
print("▣ 분석 결과 요약")
print("=" * 70)
total_facilities = int(master['시설수'].sum())
total_elderly = int(master['65세이상인구'].sum())
print(f"  서울 전체 노인여가복지시설 : {total_facilities}개소")
print(f"  서울 전체 65세이상 인구   : {total_elderly:,}명")
print(f"  서울 평균 고령화율        : {master['고령화율'].mean():.1f}%")
print(f"  서울 평균 복지지수(1만명당): {master['welfare_index'].mean():.2f}개소")
print(f"  서울 평균 녹지지수(1인당) : {master['green_index'].mean():.1f}㎡/인")

# ── CSV 저장 ────────────────────────────────────────────────
result_path = os.path.join(OUTPUT_DIR, 'district_welfare_analysis.csv')
master_sorted.to_csv(result_path, index=False, encoding='utf-8-sig')
print(f"\n  분석 결과 CSV 저장: {result_path}")

top5_path = os.path.join(OUTPUT_DIR, 'top5_urgent_districts.csv')
top5.to_csv(top5_path, index=False, encoding='utf-8-sig')
print(f"  TOP5 리포트 CSV 저장: {top5_path}")

print("\n" + "=" * 60)
print("전체 분석 파이프라인 완료")
print(f"결과물 디렉토리: {OUTPUT_DIR}")
print("  - seoul_welfare_map.html       (인터랙티브 지도)")
print("  - welfare_analysis_chart.png   (막대 + 산점도 차트)")
print("  - welfare_green_scatter.png    (2D 지수 분포도)")
print("  - district_welfare_analysis.csv (전체 분석 결과)")
print("  - top5_urgent_districts.csv    (TOP5 시급 자치구)")
print("=" * 60)
