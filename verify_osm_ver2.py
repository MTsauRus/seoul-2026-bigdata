"""
서울 지상철도 OSM v2 — 정밀 검증
==================================
v1의 문제 해결:
1. 서울 행정경계로 strict clip
2. layer 태그 (음수=지하) 활용
3. 노선명 기반 화이트리스트 (지상 운행으로 알려진 노선)
4. 한글 폰트 (Windows: Malgun Gothic)

실행: python verify_osm_v2.py
"""
import osmnx as ox
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib

# Windows 한글 폰트
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

print(">> 서울 행정경계 가져오는 중...")
seoul_boundary = ox.geocode_to_gdf("Seoul, South Korea")
seoul_poly = seoul_boundary.geometry.iloc[0]
print(f"   서울 면적: {seoul_boundary.to_crs(5179).area.iloc[0]/1e6:.0f} km²")

print("\n>> railway=rail 데이터 fetching (서울 + 주변)...")
rails = ox.features_from_place("Seoul, South Korea", tags={"railway": "rail"})
rails = rails[rails.geometry.type.isin(["LineString", "MultiLineString"])].copy()
print(f"   원본 피처: {len(rails)}개")

# === STEP 1: 서울 경계로 strict clip ===
print("\n>> 서울 경계로 클립...")
rails_clipped = gpd.clip(rails, seoul_poly)
rails_clipped = rails_clipped[rails_clipped.geometry.type.isin(["LineString", "MultiLineString"])]
rails_m = rails_clipped.to_crs(epsg=5179)
rails_m["length_m"] = rails_m.geometry.length
total_km = rails_m["length_m"].sum() / 1000
print(f"   서울 시내 railway=rail 총 연장: {total_km:.1f} km")
print(f"   (참고: 2040 계획 명시 지상철도 = 101.2km, 전체 철도는 더 많음)")

# === STEP 2: 태그 기반 분류 (개선) ===
def classify(row):
    bridge = str(row.get("bridge", "")).lower()
    tunnel = str(row.get("tunnel", "")).lower()
    layer = row.get("layer", None)
    location = str(row.get("location", "")).lower()
    
    # 명시적 터널
    if tunnel in ("yes", "building_passage", "culvert"):
        return "터널(명시)"
    if location in ("underground",):
        return "터널(명시)"
    # layer 음수
    try:
        if layer is not None and float(layer) < 0:
            return "터널(layer<0)"
    except (ValueError, TypeError):
        pass
    # 명시적 교량
    if bridge in ("yes", "viaduct"):
        return "고가(명시)"
    try:
        if layer is not None and float(layer) > 0:
            return "고가(layer>0)"
    except (ValueError, TypeError):
        pass
    return "미분류(태그없음)"

rails_m["class"] = rails_m.apply(classify, axis=1)
print("\n>> 태그 기반 분류 결과:")
summary = rails_m.groupby("class")["length_m"].sum() / 1000
print(summary.round(1).to_string())

# === STEP 3: 노선 화이트리스트로 추정 ===
# 2040 계획에 명시된 지상철도 + 알려진 지상구간 보유 노선
ABOVE_GROUND_LINES = [
    "경부선", "경원선", "경의선", "경춘선", "중앙선", 
    "경인선", "분당선", "안산선", "수인선", "용산선",
    "수색객차출발선", "장항선",
]
# 거의 100% 지하인 노선 (서울교통공사 1~9호선 본선)
UNDERGROUND_LINES = [
    "수도권 전철 1호선", "수도권 전철 2호선", "수도권 전철 3호선",
    "수도권 전철 4호선", "수도권 전철 5호선", "수도권 전철 6호선",
    "수도권 전철 7호선", "수도권 전철 8호선", "수도권 전철 9호선",
    "수도권광역급행철도", "신분당선",
]

def whitelist_class(name):
    if name is None or str(name) == "nan":
        return "이름없음"
    n = str(name)
    for w in ABOVE_GROUND_LINES:
        if w in n:
            return "화이트리스트(지상후보)"
    for u in UNDERGROUND_LINES:
        if u in n:
            return "블랙리스트(지하)"
    return "기타"

rails_m["wl_class"] = rails_m["name"].apply(whitelist_class)
print("\n>> 노선 화이트리스트 분류:")
wl_summary = rails_m.groupby("wl_class")["length_m"].sum() / 1000
print(wl_summary.round(1).to_string())

# === STEP 4: 두 분류 교차표 ===
print("\n>> 교차표 (행=화이트리스트, 열=태그분류, 단위 km):")
cross = rails_m.groupby(["wl_class", "class"])["length_m"].sum() / 1000
print(cross.round(1).to_string())

# === STEP 5: 화이트리스트 기반 노선별 ===
above = rails_m[rails_m["wl_class"] == "화이트리스트(지상후보)"]
print(f"\n>> 화이트리스트 지상후보 총 연장: {above['length_m'].sum()/1000:.1f} km")
print("   (이게 우리가 단절 분석에 쓸 핵심 데이터)")
print("\n   노선별:")
print((above.groupby("name")["length_m"].sum() / 1000).round(1).sort_values(ascending=False).to_string())

# === STEP 6: 시각화 ===
fig, axes = plt.subplots(1, 2, figsize=(20, 12))

# 좌: 태그 분류
ax = axes[0]
seoul_boundary.to_crs(5179).boundary.plot(ax=ax, color='gray', linewidth=1, alpha=0.5)
color_map = {
    "터널(명시)": "#74B9FF",
    "터널(layer<0)": "#0984E3",
    "고가(명시)": "#FDCB6E",
    "고가(layer>0)": "#F39C12",
    "미분류(태그없음)": "#E84545",
}
for cls, color in color_map.items():
    sub = rails_m[rails_m["class"] == cls]
    if len(sub):
        sub.plot(ax=ax, color=color, linewidth=1.8, 
                 label=f"{cls} ({sub['length_m'].sum()/1000:.1f}km)")
ax.set_title("v1 방식: 태그만으로 분류 (미분류 비율 큼)", fontsize=14)
ax.legend(loc='upper left', fontsize=9)
ax.set_axis_off()

# 우: 화이트리스트 분류
ax = axes[1]
seoul_boundary.to_crs(5179).boundary.plot(ax=ax, color='gray', linewidth=1, alpha=0.5)
wl_color_map = {
    "화이트리스트(지상후보)": "#E84545",
    "블랙리스트(지하)": "#74B9FF",
    "기타": "#B2BEC3",
    "이름없음": "#DFE6E9",
}
for cls, color in wl_color_map.items():
    sub = rails_m[rails_m["wl_class"] == cls]
    if len(sub):
        lw = 2.5 if cls == "화이트리스트(지상후보)" else 1.2
        sub.plot(ax=ax, color=color, linewidth=lw,
                 label=f"{cls} ({sub['length_m'].sum()/1000:.1f}km)")
ax.set_title("v2 방식: 노선명 화이트리스트 (빨강=분석 대상)", fontsize=14)
ax.legend(loc='upper left', fontsize=9)
ax.set_axis_off()

plt.suptitle("서울 지상철도 OSM 데이터 — 두 가지 분류 비교", fontsize=18, y=1.02)
plt.tight_layout()
plt.savefig("seoul_rail_v2.png", dpi=150, bbox_inches="tight")
print("\n>> seoul_rail_v2.png 저장")

# === STEP 7: 진단 출력 ===
print("\n" + "="*60)
print("🔎 다음 메시지에 이 부분 복사해서 보내줘:")
print("="*60)
print(f"서울 시내 총 railway=rail: {total_km:.1f} km")
print(f"화이트리스트(지상후보): {above['length_m'].sum()/1000:.1f} km")
print(f"  → 2040 계획 101.2km와 가까우면 OK")
print(f"  → 50km 미만이면 화이트리스트 보강 필요")
print(f"  → 200km 초과면 블랙리스트 누락 의심")
print(f"태그 미분류 비율: {(rails_m[rails_m['class']=='미분류(태그없음)']['length_m'].sum() / rails_m['length_m'].sum())*100:.0f}%")