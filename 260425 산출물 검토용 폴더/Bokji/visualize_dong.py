"""
서울시 노인복지 및 녹지 접근성 – 행정동 단위 시각화
======================================================
출력:
  output/park_dong_map.html     ← 행정동 녹지 접근성 지도
  output/welfare_dong_map.html  ← 행정동 복지시설 접근성 지도
"""

import warnings; warnings.filterwarnings('ignore')
import io, os, re, json, time
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.ops import unary_union
import folium
import branca.colormap as bc
import requests
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
CACHE_FILE = os.path.join(OUTPUT_DIR, "geocode_cache.json")

CRS_WGS84 = "EPSG:4326"
CRS_KOREA = "EPSG:5179"

# ── 행정동 이름 정규화 (CSV ↔ GeoJSON 불일치 교정) ────────────
DONG_NAME_MAP = {
    # 구분점 차이 (.→·) 및 기타 이름 차이
    '종로1.2.3.4가동':  '종로1·2·3·4가동',
    '종로5.6가동':      '종로5·6가동',
    '금호2.3가동':      '금호2·3가동',
    '상계3.4동':        '상계3·4동',
    '상계6.7동':        '상계6·7동',
    '중계2.3동':        '중계2·3동',
    '면목3.8동':        '면목3·8동',
    # 강동구 이름 차이
    '상일1동': '상일제1동',
    '상일2동': '상일제2동',
    # 동대문구 통합 처리
    '신설동':  '용신동',
    '용두동':  '용신동',
}

def norm_dong(name):
    return DONG_NAME_MAP.get(name, name)


# ============================================================
# 1. 데이터 로드
# ============================================================
print("=" * 60)
print("1. 데이터 로드")
print("=" * 60)

# ── 행정동 GeoJSON ────────────────────────────────────────────
print("  행정동 GeoJSON 다운로드 중...")
resp = requests.get(
    "https://raw.githubusercontent.com/vuski/admdongkor/master/"
    "ver20230701/HangJeongDong_ver20230701.geojson",
    timeout=60
)
dong_gdf = gpd.GeoDataFrame.from_features(resp.json()['features'], crs=CRS_WGS84)
dong_gdf = dong_gdf[dong_gdf['sido'] == '11'].copy()
dong_gdf['구명'] = dong_gdf['sggnm']
dong_gdf['동명'] = dong_gdf['adm_nm'].str.split(' ').str[-1]
dong_gdf['동_key'] = dong_gdf['구명'] + '_' + dong_gdf['동명']
print(f"  서울 행정동 {len(dong_gdf)}개 로드")

# ── 고령인구 (행정동 단위) ────────────────────────────────────
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
elderly = elderly_raw.iloc[4:].copy()
elderly = elderly[(elderly['구명'] != '소계') & (elderly['동명'] != '소계')]
for c in ['전체인구', '65세이상']:
    elderly[c] = pd.to_numeric(
        elderly[c].astype(str).str.replace(',', ''), errors='coerce'
    )
elderly = elderly.dropna(subset=['65세이상'])
elderly['동명_norm'] = elderly['동명'].apply(norm_dong)
elderly['동_key'] = elderly['구명'] + '_' + elderly['동명_norm']
elderly_dong = elderly[['동_key', '구명', '동명', '전체인구', '65세이상']].copy()
elderly_dong.rename(columns={'65세이상': '65세이상인구'}, inplace=True)
# 동_key 중복 시 합산 (신설동+용두동 → 용신동)
elderly_dong = elderly_dong.groupby('동_key').agg(
    구명=('구명', 'first'),
    동명=('동명', 'first'),
    전체인구=('전체인구', 'sum'),
    pop65=('65세이상인구', 'sum')
).reset_index()
elderly_dong.rename(columns={'pop65': '65세이상인구'}, inplace=True)
elderly_dong['고령화율'] = (elderly_dong['65세이상인구'] / elderly_dong['전체인구'] * 100).round(2)
print(f"  고령인구 행정동 {len(elderly_dong)}개 로드")

# ── 복지시설 ─────────────────────────────────────────────────
with open(os.path.join(BASE_DIR,
          "서울시 사회복지시설(노인여가복지시설) 목록.csv"), 'rb') as f:
    welfare_df = pd.read_csv(io.StringIO(f.read().decode('euc-kr')))
welfare_df.columns = [
    '시설명','시설코드','시설유형','시설종류상세',
    '자치구구분','시군구코드','시군구명','시설주소',
    '전화번호','우편번호'
]
welfare_df = welfare_df[welfare_df['자치구구분'] == '자치구'].copy()
welfare_df['시설주소'] = welfare_df['시설주소'].fillna('').str.strip()
welfare_df = welfare_df[welfare_df['시설주소'] != '']

def short_type(t):
    if '소규모' in t: return '경로당(소규모)'
    if '경로당' in t: return '경로당'
    return '노인복지관'

welfare_df['유형_간략'] = welfare_df['시설유형'].apply(short_type)
print(f"  복지시설 {len(welfare_df)}개 로드")

# ── 공원 ──────────────────────────────────────────────────────
parks_raw = pd.read_excel(
    os.path.join(BASE_DIR, "서울시 주요 공원현황(2026 상반기).xlsx")
)
parks_raw.columns = [
    '연번','관리부서','전화번호','공원명','공원개요',
    '면적','개원일','주요시설','주요식물','안내도',
    '오시는길','이용시참고사항','이미지','지역','공원주소',
    'X_GRS80','Y_GRS80','X_WGS84','Y_WGS84','바로가기'
]
SEOUL_GU = dong_gdf['구명'].unique().tolist()
def parse_area(v):
    m = re.search(r'[\d,]+\.?\d*', str(v).replace(',',''))
    return float(m.group().replace(',','')) if m else np.nan

parks_raw['면적_m2'] = parks_raw['면적'].apply(parse_area)
parks_df = parks_raw[parks_raw['지역'].isin(SEOUL_GU)].dropna(
    subset=['X_WGS84', 'Y_WGS84', '면적_m2']
).copy()
parks_df = parks_df[parks_df['X_WGS84'] > 0]
parks_gdf = gpd.GeoDataFrame(
    parks_df,
    geometry=gpd.points_from_xy(parks_df['X_WGS84'], parks_df['Y_WGS84']),
    crs=CRS_WGS84
)
print(f"  공원 {len(parks_gdf)}개 로드")


# ============================================================
# 2. 복지시설 지오코딩 (Nominatim + 캐시)
# ============================================================
print("\n" + "=" * 60)
print("2. 복지시설 지오코딩 (Nominatim)")
print("=" * 60)

cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    print(f"  캐시 로드: {len(cache)}건")

geolocator = Nominatim(user_agent="seoul_welfare_analysis_v2")
geocode     = RateLimiter(geolocator.geocode, min_delay_seconds=1.2)

lats, lngs = [], []
miss = 0
for i, row in welfare_df.iterrows():
    addr = row['시설주소']
    if addr in cache:
        lats.append(cache[addr]['lat'])
        lngs.append(cache[addr]['lng'])
        continue

    # 괄호 안 동명 + 구명 으로 단순화 시도 → 원본 주소 순으로 fallback
    def try_geocode(query):
        try:
            loc = geocode(query, language='ko', timeout=10)
            return loc
        except:
            return None

    loc = try_geocode(addr)
    if loc is None:
        # fallback: "서울특별시 XX구 YY로/길 N"  (주소 앞 부분만)
        short = re.sub(r'\s*\(.*?\)', '', addr).strip()
        loc = try_geocode(short)

    if loc:
        cache[addr] = {'lat': loc.latitude, 'lng': loc.longitude}
        lats.append(loc.latitude)
        lngs.append(loc.longitude)
    else:
        cache[addr] = {'lat': None, 'lng': None}
        lats.append(None)
        lngs.append(None)
        miss += 1
        print(f"  [실패] {addr[:60]}")

    # 진행 상황 표시
    done = i - welfare_df.index[0] + 1
    total = len(welfare_df)
    if done % 20 == 0 or done == total:
        print(f"  진행: {done}/{total}  실패: {miss}")

with open(CACHE_FILE, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

welfare_df = welfare_df.copy()
welfare_df['lat'] = lats
welfare_df['lng'] = lngs
welfare_ok = welfare_df.dropna(subset=['lat', 'lng']).copy()
welfare_gdf = gpd.GeoDataFrame(
    welfare_ok,
    geometry=gpd.points_from_xy(welfare_ok['lng'], welfare_ok['lat']),
    crs=CRS_WGS84
)
print(f"  지오코딩 완료: {len(welfare_gdf)}/{len(welfare_df)}개 성공")


# ============================================================
# 3. 공간 분석 – 행정동 단위 집계
# ============================================================
print("\n" + "=" * 60)
print("3. 행정동 단위 공간 집계")
print("=" * 60)

dong_korea   = dong_gdf.to_crs(CRS_KOREA)
parks_korea  = parks_gdf.to_crs(CRS_KOREA)
welfare_korea = welfare_gdf.to_crs(CRS_KOREA)

# ── 공원 → 행정동 spatial join ────────────────────────────────
parks_join = gpd.sjoin(
    parks_korea[['공원명', '지역', '면적_m2', 'geometry']],
    dong_korea[['동_key', '구명', '동명', 'geometry']],
    how='left', predicate='within'
).rename(columns={'index_right': 'dong_idx'})

park_dong = parks_join.groupby('동_key').agg(
    공원수=('공원명', 'count'),
    공원면적_m2=('면적_m2', 'sum')
).reset_index()
print(f"  공원-행정동 join: {len(parks_join[parks_join['동_key'].notna()])}개 매칭")

# ── 복지시설 → 행정동 spatial join ──────────────────────────
welfare_join = gpd.sjoin(
    welfare_korea[['시설명', '시설유형', '유형_간략', '시군구명', 'geometry']],
    dong_korea[['동_key', '구명', '동명', 'geometry']],
    how='left', predicate='within'
).rename(columns={'index_right': 'dong_idx'})

welfare_dong = welfare_join.groupby('동_key').agg(
    시설수=('시설명', 'count'),
    노인복지관=('유형_간략', lambda x: (x == '노인복지관').sum()),
    경로당=('유형_간략', lambda x: (x == '경로당').sum()),
    경로당소규모=('유형_간략', lambda x: (x == '경로당(소규모)').sum()),
).reset_index()
print(f"  복지시설-행정동 join: {len(welfare_join[welfare_join['동_key'].notna()])}개 매칭")

# ── 보행권 커버리지 (400m / 800m) ────────────────────────────
def calc_coverage(facility_gdf_k, dong_k, radius):
    """각 행정동에서 시설 버퍼가 덮는 비율(%)"""
    rows = []
    for _, d in dong_k.iterrows():
        fac = facility_gdf_k[
            facility_gdf_k.geometry.intersects(d.geometry.buffer(radius + 10))
        ]
        if fac.empty:
            rows.append({'동_key': d['동_key'], f'cov_{radius}': 0.0})
            continue
        bufs  = fac.geometry.buffer(radius)
        union = unary_union(bufs.tolist())
        inter = d.geometry.intersection(union)
        rows.append({'동_key': d['동_key'],
                     f'cov_{radius}': inter.area / d.geometry.area * 100})
    return pd.DataFrame(rows)

print("  공원 보행권 커버리지 계산 중...")
park_cov400 = calc_coverage(parks_korea, dong_korea, 400)
park_cov800 = calc_coverage(parks_korea, dong_korea, 800)

print("  복지시설 보행권 커버리지 계산 중...")
welf_cov400 = calc_coverage(welfare_korea, dong_korea, 400)
welf_cov800 = calc_coverage(welfare_korea, dong_korea, 800)

# ── 마스터 데이터프레임 ───────────────────────────────────────
master = (
    dong_gdf[['동_key', '구명', '동명', 'geometry']]
    .merge(elderly_dong[['동_key', '전체인구', '65세이상인구', '고령화율']], on='동_key', how='left')
    .merge(park_dong, on='동_key', how='left')
    .merge(welfare_dong, on='동_key', how='left')
    .merge(park_cov400, on='동_key', how='left')
    .merge(park_cov800, on='동_key', how='left')
    .merge(welf_cov400.rename(columns={'cov_400': 'welf_cov_400'}), on='동_key', how='left')
    .merge(welf_cov800.rename(columns={'cov_800': 'welf_cov_800'}), on='동_key', how='left')
)

# 결측치 채우기
fill0 = ['공원수','공원면적_m2','시설수','노인복지관','경로당','경로당소규모',
         'cov_400','cov_800','welf_cov_400','welf_cov_800']
for c in fill0:
    if c in master.columns:
        master[c] = master[c].fillna(0)
master['65세이상인구'] = master['65세이상인구'].fillna(0)

# 지수 계산
master['green_index']   = np.where(
    master['65세이상인구'] > 0,
    (master['공원면적_m2'] / master['65세이상인구']).round(2), 0
)
master['welfare_index'] = np.where(
    master['65세이상인구'] > 0,
    (master['시설수'] / master['65세이상인구'] * 10000).round(3), 0
)

master_gdf = gpd.GeoDataFrame(master, geometry='geometry', crs=CRS_WGS84)
print(f"  마스터 GDF 완성: {len(master_gdf)}개 행정동")


# ============================================================
# 4-A. 공원·녹지 접근성 지도 (행정동 단위)
# ============================================================
print("\n" + "=" * 60)
print("4-A. 공원·녹지 접근성 지도 생성")
print("=" * 60)

m_park = folium.Map(location=[37.5665, 126.9780], zoom_start=11,
                    tiles='CartoDB positron')

# 녹지 보행권 커버리지(400m) Choropleth ──────────────────────
# 데이터가 없는 동(65세이상=0) 구분
master_gdf['cov_400_disp'] = master_gdf['cov_400'].fillna(0)

colormap_green = bc.LinearColormap(
    ['#f7fcf5','#74c476','#006d2c'],
    vmin=0, vmax=100,
    caption='공원 400m 보행권 커버리지 (%)'
)
colormap_green.add_to(m_park)

style_park = folium.GeoJson(
    master_gdf[['동_key','구명','동명','cov_400_disp','cov_800',
                '공원수','공원면적_m2','green_index','65세이상인구','geometry']].to_json(),
    style_function=lambda feat: {
        'fillColor': colormap_green(
            feat['properties'].get('cov_400_disp') or 0
        ),
        'color': '#555',
        'weight': 0.6,
        'fillOpacity': 0.75
    },
    tooltip=folium.GeoJsonTooltip(
        fields=['구명','동명','cov_400_disp','cov_800',
                '공원수','공원면적_m2','green_index','65세이상인구'],
        aliases=['자치구','행정동','400m커버(%)','800m커버(%)',
                 '공원수(개)','공원면적(㎡)','녹지지수(㎡/인)','65세이상인구'],
        localize=True
    ),
    name='행정동 녹지 커버리지 (Choropleth)'
)
style_park.add_to(m_park)

# 공원 마커 ───────────────────────────────────────────────────
park_layer = folium.FeatureGroup(name='공원 위치 (버블=면적)')
for _, row in parks_df.iterrows():
    r = max(4, min(25, np.sqrt(row['면적_m2']) / 50))
    folium.CircleMarker(
        location=[row['Y_WGS84'], row['X_WGS84']],
        radius=r,
        color='#1a5e22', weight=1,
        fill=True, fill_color='#2ca02c', fill_opacity=0.75,
        tooltip=f"<b>{row['공원명']}</b><br>면적: {row['면적_m2']:,.0f}㎡",
        popup=(f"<b>{row['공원명']}</b><br>"
               f"면적: {row['면적_m2']:,.0f}㎡<br>"
               f"지역: {row['지역']}<br>"
               f"주소: {row['공원주소']}")
    ).add_to(park_layer)
park_layer.add_to(m_park)

# 400m / 800m 버퍼 (면적 상위 10개 공원) ─────────────────────
buf400_layer = folium.FeatureGroup(name='공원 400m 버퍼 (상위10)', show=False)
buf800_layer = folium.FeatureGroup(name='공원 800m 버퍼 (상위10)', show=False)
top10_parks  = parks_gdf.nlargest(10, '면적_m2').to_crs(CRS_KOREA)

for _, row in top10_parks.iterrows():
    for lyr, rad, col, op in [
        (buf400_layer, 400, '#2ca02c', 0.20),
        (buf800_layer, 800, '#98df8a', 0.12)
    ]:
        buf = gpd.GeoDataFrame(
            geometry=[row.geometry.buffer(rad)], crs=CRS_KOREA
        ).to_crs(CRS_WGS84)
        folium.GeoJson(
            buf.geometry.__geo_interface__,
            style_function=lambda x, c=col, o=op: {
                'fillColor': c, 'color': c, 'weight': 1, 'fillOpacity': o
            },
            tooltip=f"{row['공원명']} {rad}m"
        ).add_to(lyr)

buf400_layer.add_to(m_park)
buf800_layer.add_to(m_park)
folium.LayerControl(collapsed=False).add_to(m_park)

park_map_path = os.path.join(OUTPUT_DIR, 'park_dong_map.html')
m_park.save(park_map_path)
print(f"  공원 지도 저장: {park_map_path}")


# ============================================================
# 4-B. 복지시설 접근성 지도 (행정동 단위)
# ============================================================
print("\n" + "=" * 60)
print("4-B. 복지시설 접근성 지도 생성")
print("=" * 60)

m_welf = folium.Map(location=[37.5665, 126.9780], zoom_start=11,
                    tiles='CartoDB positron')

# 복지시설 지수 Choropleth ─────────────────────────────────────
colormap_blue = bc.LinearColormap(
    ['#f7fbff','#6baed6','#08306b'],
    vmin=0, vmax=master_gdf['welfare_index'].quantile(0.95),
    caption='복지시설 지수 (65세이상 1만명당 시설 수)'
)
colormap_blue.add_to(m_welf)

master_gdf['welf_disp'] = master_gdf['welfare_index'].clip(
    upper=master_gdf['welfare_index'].quantile(0.95)
)

style_welf = folium.GeoJson(
    master_gdf[['동_key','구명','동명','welfare_index','welf_disp',
                '시설수','노인복지관','경로당','경로당소규모',
                'welf_cov_400','welf_cov_800','65세이상인구','고령화율',
                'geometry']].to_json(),
    style_function=lambda feat: {
        'fillColor': colormap_blue(
            feat['properties'].get('welf_disp') or 0
        ),
        'color': '#555',
        'weight': 0.6,
        'fillOpacity': 0.75
    },
    tooltip=folium.GeoJsonTooltip(
        fields=['구명','동명','welfare_index','시설수',
                '노인복지관','경로당','경로당소규모',
                'welf_cov_400','welf_cov_800','65세이상인구','고령화율'],
        aliases=['자치구','행정동','복지지수(1만명당)','총시설수',
                 '노인복지관','경로당','경로당(소규모)',
                 '400m커버(%)','800m커버(%)','65세이상인구','고령화율(%)'],
        localize=True
    ),
    name='행정동 복지시설 지수 (Choropleth)'
)
style_welf.add_to(m_welf)

# 시설 유형별 마커 ─────────────────────────────────────────────
TYPE_STYLE = {
    '노인복지관':     {'color': '#1f77b4', 'radius': 9,  'icon': '🏛'},
    '경로당':         {'color': '#ff7f0e', 'radius': 6,  'icon': '🏠'},
    '경로당(소규모)': {'color': '#aec7e8', 'radius': 5,  'icon': '🍃'},
}
for wtype, style in TYPE_STYLE.items():
    layer = folium.FeatureGroup(name=f'시설: {wtype}')
    sub = welfare_gdf[welfare_gdf['유형_간략'] == wtype]
    for _, row in sub.iterrows():
        if row.geometry is None: continue
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=style['radius'],
            color=style['color'], weight=1.5,
            fill=True, fill_color=style['color'], fill_opacity=0.85,
            tooltip=f"<b>{row['시설명']}</b><br>{wtype}<br>{row['시군구명']}",
            popup=(f"<b>{row['시설명']}</b><br>"
                   f"유형: {wtype}<br>"
                   f"구: {row['시군구명']}<br>"
                   f"주소: {row['시설주소']}")
        ).add_to(layer)
    layer.add_to(m_welf)

# 노인복지관 400m / 800m 버퍼 ─────────────────────────────────
wc_layer_400 = folium.FeatureGroup(name='노인복지관 400m 버퍼', show=False)
wc_layer_800 = folium.FeatureGroup(name='노인복지관 800m 버퍼', show=False)
wc_korea = welfare_gdf[welfare_gdf['유형_간략'] == '노인복지관'].to_crs(CRS_KOREA)

for _, row in wc_korea.iterrows():
    for lyr, rad, col, op in [
        (wc_layer_400, 400, '#1f77b4', 0.18),
        (wc_layer_800, 800, '#aec7e8', 0.10)
    ]:
        buf = gpd.GeoDataFrame(
            geometry=[row.geometry.buffer(rad)], crs=CRS_KOREA
        ).to_crs(CRS_WGS84)
        folium.GeoJson(
            buf.geometry.__geo_interface__,
            style_function=lambda x, c=col, o=op: {
                'fillColor': c, 'color': c, 'weight': 1, 'fillOpacity': o
            },
            tooltip=f"{row['시설명']} {rad}m"
        ).add_to(lyr)

wc_layer_400.add_to(m_welf)
wc_layer_800.add_to(m_welf)
folium.LayerControl(collapsed=False).add_to(m_welf)

welf_map_path = os.path.join(OUTPUT_DIR, 'welfare_dong_map.html')
m_welf.save(welf_map_path)
print(f"  복지 지도 저장: {welf_map_path}")


# ============================================================
# 5. 요약 리포트 출력
# ============================================================
print("\n" + "=" * 60)
print("5. 행정동 단위 분석 요약")
print("=" * 60)

m_valid = master_gdf[master_gdf['65세이상인구'] > 0].copy()

# 녹지 사각지대 (400m 커버리지 0%, 65세이상인구 >0)
blind_park = m_valid[m_valid['cov_400'] == 0]
print(f"\n  ▣ 공원 400m 보행권 완전 사각지대: {len(blind_park)}개 행정동")
for _, r in blind_park.nlargest(5, '65세이상인구').iterrows():
    print(f"    - {r['구명']} {r['동명']}: 65세이상 {r['65세이상인구']:.0f}명")

# 복지시설 없는 행정동
blind_welf = m_valid[m_valid['시설수'] == 0]
print(f"\n  ▣ 복지시설 0개 행정동: {len(blind_welf)}개")
for _, r in blind_welf.nlargest(5, '65세이상인구').iterrows():
    print(f"    - {r['구명']} {r['동명']}: 65세이상 {r['65세이상인구']:.0f}명")

# 고령화율 상위 10개 동
print(f"\n  ▣ 고령화율 상위 10개 행정동:")
for _, r in m_valid.nlargest(10, '고령화율').iterrows():
    print(f"    {r['구명']:7s} {r['동명']:12s}  "
          f"고령화율 {r['고령화율']:.1f}%  "
          f"복지지수 {r['welfare_index']:.2f}  "
          f"공원커버 {r['cov_400']:.1f}%")

print("\n" + "=" * 60)
print("완료!")
print(f"  park_dong_map.html    → {park_map_path}")
print(f"  welfare_dong_map.html → {welf_map_path}")
print("=" * 60)
