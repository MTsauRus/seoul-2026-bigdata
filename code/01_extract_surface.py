"""
01_extract_surface_rail.py
서울시 지상철도 추출 및 검증 스크립트

목적:
  1. OSM에서 서울시 전역의 철도 데이터를 받아온다
  2. 지하 구간(터널/복개)을 제거해 '지상철도'만 남긴다
  3. 2040 서울플랜 공식 수치(101.2km)와 비교해 검증
  4. 정적 지도(matplotlib) + 인터랙티브 지도(Folium) 생성 → 육안 검증
  5. 다음 단계(우회비 분석)에서 재사용할 수 있게 GeoPackage로 저장

사전 설치:
  pip install osmnx geopandas folium matplotlib contextily

[성령 학습 포인트]
- osmnx: OpenStreetMap에서 지리 데이터를 파이썬으로 받아오는 라이브러리
- geopandas: pandas + 지리정보(geometry 컬럼) = GeoDataFrame
- CRS(좌표계): EPSG:4326 = 위경도(각도), EPSG:5179 = 한국 표준 미터 좌표
  거리 계산은 반드시 5179에서. 지도 시각화는 주로 4326에서.
"""

import osmnx as ox
import geopandas as gpd
import matplotlib.pyplot as plt
import folium
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 0. 설정
# ─────────────────────────────────────────────────────────────
PLACE = "Seoul, South Korea"
OUT_DIR = Path("output"); OUT_DIR.mkdir(exist_ok=True)
OFFICIAL_KM = 101.2  # 2040 서울플랜 공식 지상철도 연장

# ─────────────────────────────────────────────────────────────
# 1. 서울 경계 + 철도 raw 다운로드
# ─────────────────────────────────────────────────────────────
print("[1/5] 서울 경계 및 철도 데이터 다운로드 중...")

# 서울시 행정경계 폴리곤 (EPSG:4326, 위경도)
seoul = ox.geocode_to_gdf(PLACE)

# railway=* 태그가 붙은 모든 피처를 받아옴
# features_from_place는 해당 지역 내 OSM 피처를 GeoDataFrame으로 반환
rail_tags = {"railway": ["rail", "light_rail", "subway", "monorail", "narrow_gauge"]}
rail_raw = ox.features_from_place(PLACE, tags=rail_tags)

# LineString/MultiLineString(선형) 피처만 남김 (역 포인트, 플랫폼 폴리곤 제거)
rail_raw = rail_raw[rail_raw.geometry.type.isin(["LineString", "MultiLineString"])].copy()
print(f"  raw 철도 피처 수: {len(rail_raw)}")

# ─────────────────────────────────────────────────────────────
# 2. 지하 구간 제거 → 지상만 남기기
# ─────────────────────────────────────────────────────────────
print("[2/5] 지하 구간 필터링...")

def is_underground(row):
    """지하 판정: tunnel 태그, layer 음수, covered 태그 셋 중 하나라도 걸리면 지하"""
    # .get(key, default)으로 안전하게 접근 (태그 없을 수 있음)
    if str(row.get("tunnel", "")).lower() in ("yes", "building_passage", "culvert"):
        return True
    try:
        if int(row.get("layer", 0)) < 0:
            return True
    except (ValueError, TypeError):
        pass  # layer가 숫자가 아니면 무시
    if str(row.get("covered", "")).lower() == "yes":
        return True
    return False

# apply: 각 행에 함수를 적용해 True/False 시리즈 생성 → ~로 반전(지상만)
surface = rail_raw[~rail_raw.apply(is_underground, axis=1)].copy()
print(f"  지상 철도 피처 수: {len(surface)} (지하 {len(rail_raw)-len(surface)}개 제거)")

# ─────────────────────────────────────────────────────────────
# 3. 거리 계산용 투영 + 노선별 총연장
# ─────────────────────────────────────────────────────────────
print("[3/5] EPSG:5179 투영 후 길이 계산...")

# to_crs: 좌표계 변환. 5179는 한국 표준 미터 단위라 .length가 곧 미터
surface_m = surface.to_crs(epsg=5179)

# name 태그(노선명)별로 묶어서 길이 합산
# name이 없는 조각은 "미상"으로 표시
if "name" in surface_m.columns:
    surface_m["name"] = surface_m["name"].fillna("미상")
else:
    surface_m["name"] = "미상"
by_line = (
    surface_m.assign(length_m=surface_m.geometry.length)
    .groupby("name")["length_m"].sum()
    .div(1000)  # m → km
    .sort_values(ascending=False)
)

total_km = by_line.sum()
print(f"\n  === 노선별 지상 연장 (상위 15개) ===")
print(by_line.head(15).round(2).to_string())
print(f"\n  총 지상철도 연장: {total_km:.2f} km")
print(f"  공식 수치(2040플랜): {OFFICIAL_KM} km")
print(f"  오차: {abs(total_km - OFFICIAL_KM):.2f} km ({abs(total_km-OFFICIAL_KM)/OFFICIAL_KM*100:.1f}%)")

# [검증 포인트 1] 노선명 리스트를 네가 직접 훑어봐:
#   - "신분당선"이 "분당선"에 섞여있는지 (substring 버그 체크)
#   - 이름 없는 "미상" 구간 비율이 과하게 크진 않은지
#   - 경부선/경인선/경의중앙선/경춘선/중앙선/수인분당선/1호선 등 상식적 노선이 다 보이는지

# ─────────────────────────────────────────────────────────────
# 4. 정적 지도 (matplotlib) — 보고서용
# ─────────────────────────────────────────────────────────────
print("[4/5] 정적 지도 렌더링...")

fig, ax = plt.subplots(figsize=(12, 12))
seoul.to_crs(5179).boundary.plot(ax=ax, color="black", linewidth=0.8)
surface_m.plot(ax=ax, color="crimson", linewidth=1.5)
ax.set_title(f"Seoul Surface Railways\n{total_km:.1f} km (official: {OFFICIAL_KM} km)",
             fontsize=14)
ax.set_axis_off()
plt.tight_layout()
plt.savefig(OUT_DIR / "map_static_surface_rail.png", dpi=200, bbox_inches="tight")
plt.close()

# ─────────────────────────────────────────────────────────────
# 5. 인터랙티브 지도 (Folium) — 육안 검증용 ★핵심★
# ─────────────────────────────────────────────────────────────
print("[5/5] Folium 인터랙티브 지도 생성...")

# Folium은 위경도(4326)를 씀
surface_wgs = surface.to_crs(4326)

m = folium.Map(location=[37.5665, 126.9780], zoom_start=11, tiles="CartoDB positron")

# 각 라인을 Folium에 추가 + 클릭 시 노선명 팝업
# 이렇게 하면 네가 지도 확대해서 실제 위성사진/도로와 대조 가능
for _, row in surface_wgs.iterrows():
    geom = row.geometry
    # MultiLineString은 여러 LineString으로 풀어서 처리
    lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
    for line in lines:
        # Folium은 (lat, lon) 순서, shapely는 (x=lon, y=lat) 순서 → 뒤집기
        coords = [(pt[1], pt[0]) for pt in line.coords]
        folium.PolyLine(
            coords, color="red", weight=3, opacity=0.8,
            popup=f"{row.get('name','미상')} | tunnel={row.get('tunnel','-')}"
        ).add_to(m)

# 배경 레이어 추가 (위성사진으로 실제 철길 비교 가능)
folium.TileLayer("OpenStreetMap", name="OSM").add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri", name="위성사진"
).add_to(m)
folium.LayerControl().add_to(m)

m.save(OUT_DIR / "map_interactive_surface_rail.html")

# ─────────────────────────────────────────────────────────────
# 6. 다음 단계용 저장 (3번 작업에서 재사용)
# ─────────────────────────────────────────────────────────────
# GeoPackage = 지리데이터용 SQLite. shapefile보다 현대적이고 한글 속성 잘 보존됨
surface_m[["name", "geometry"]].to_file(
    OUT_DIR / "surface_rail_seoul.gpkg", driver="GPKG"
)
by_line.to_csv(OUT_DIR / "surface_rail_by_line.csv", encoding="utf-8-sig")

print("\n✅ 완료")
print(f"  - {OUT_DIR}/map_static_surface_rail.png  (정적 지도)")
print(f"  - {OUT_DIR}/map_interactive_surface_rail.html  ← 브라우저로 열어서 육안 검증!")
print(f"  - {OUT_DIR}/surface_rail_seoul.gpkg  (다음 단계 입력)")
print(f"  - {OUT_DIR}/surface_rail_by_line.csv  (노선별 길이표)")