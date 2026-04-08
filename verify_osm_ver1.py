"""
서울 지상철도 OSM 데이터 품질 검증 (5분 스크립트)
====================================================
로컬 PC에서 실행 — 네트워크 필요.

설치:
    pip install osmnx geopandas matplotlib

실행:
    python verify_osm_seoul_rail.py

확인 사항:
1. 서울에 등록된 railway=rail 구간 총 길이/개수
2. bridge / tunnel 태그가 명시된 비율
3. "지상철도"로 분류 가능한 구간 비율 (≈ 100km 근처여야 함, 2040 계획에서 101.2km라고 명시)
4. 노선별(name 태그) 분포
5. 결과를 PNG로 저장
"""
import osmnx as ox
import geopandas as gpd
import matplotlib.pyplot as plt

print(">> 서울 OSM railway=rail 데이터 fetching...")
# Overpass API로 서울 시 경계 안의 모든 철도 추출
tags = {"railway": "rail"}
rails = ox.features_from_place("Seoul, South Korea", tags=tags)

# LineString만
rails = rails[rails.geometry.type.isin(["LineString", "MultiLineString"])].copy()
print(f"총 railway=rail 피처: {len(rails)}개")

# 좌표계를 미터 단위(EPSG:5179)로 변환해서 길이 계산
rails_m = rails.to_crs(epsg=5179)
rails_m["length_m"] = rails_m.geometry.length
total_km = rails_m["length_m"].sum() / 1000
print(f"총 연장: {total_km:.1f} km")

# bridge / tunnel 태그 분석
def classify(row):
    bridge = str(row.get("bridge", "no")).lower()
    tunnel = str(row.get("tunnel", "no")).lower()
    if bridge in ("yes", "viaduct"):
        return "교량(고가)"
    if tunnel in ("yes",):
        return "터널(지하)"
    return "지상(평지)"

rails_m["class"] = rails_m.apply(classify, axis=1)
summary = rails_m.groupby("class")["length_m"].sum() / 1000
print("\n구분별 연장 (km):")
print(summary.round(1))

above_ground = rails_m[rails_m["class"].isin(["지상(평지)", "교량(고가)"])]
print(f"\n>> 단절 분석 대상 (지상 + 고가): {above_ground['length_m'].sum()/1000:.1f} km")
print(f"   2040 계획 명시값과 비교: 101.2 km (국철 71.6 + 도시철도 29.6)")

# 노선별
if "name" in rails_m.columns:
    by_line = rails_m.groupby("name")["length_m"].sum().sort_values(ascending=False) / 1000
    print("\n노선별 Top 15 (km):")
    print(by_line.head(15).round(1))

# 누락 태깅 비율
missing = rails_m[(rails_m.get("bridge").isna()) & (rails_m.get("tunnel").isna())]
print(f"\nbridge/tunnel 태그 모두 누락: {len(missing)}/{len(rails_m)} ({len(missing)/len(rails_m)*100:.0f}%)")
print("(누락 = 사실상 '지상' 으로 추정되지만 수동 검증 필요)")

# 시각화: 분류별 색깔
fig, ax = plt.subplots(figsize=(12, 12))
colors = {"지상(평지)": "#E84545", "교량(고가)": "#FF9F43", "터널(지하)": "#74B9FF"}
for cls, color in colors.items():
    sub = rails_m[rails_m["class"] == cls]
    if len(sub):
        sub.plot(ax=ax, color=color, linewidth=1.5, label=f"{cls} ({sub['length_m'].sum()/1000:.1f}km)")
ax.set_title("서울 OSM railway=rail 분류", fontsize=16)
ax.legend(fontsize=12)
ax.set_axis_off()
plt.savefig("seoul_rail_verification.png", dpi=150, bbox_inches="tight")
print("\n>> seoul_rail_verification.png 저장 완료")
print("   이 PNG를 위성지도와 대조해서 누락/오분류 구간 수동 체크할 것")