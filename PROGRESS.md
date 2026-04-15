# 끊어진 서울 — 개발 진행 기록

> 2026 서울시 빅데이터 활용 경진대회  
> 최종 수정: 2026-04-15  
> 작성자: 성령 (개발), Claude Code (보조)

---

## 목차

1. [프로젝트 목표 요약](#1-프로젝트-목표-요약)
2. [접근 방식의 진화 — 뻘짓 포함](#2-접근-방식의-진화)
3. [코드 파일별 설명](#3-코드-파일별-설명)
4. [사용한 알고리즘 & 핵심 개념](#4-사용한-알고리즘--핵심-개념)
5. [데이터 & 산출물](#5-데이터--산출물)
6. [지금까지 발견한 버그 & 해결책](#6-지금까지-발견한-버그--해결책)
7. [향후 계획](#7-향후-계획)
8. [실행 방법](#8-실행-방법)

---

## 1. 프로젝트 목표 요약

**주제**: "끊어진 서울, 멀어진 물가 — 선형 장벽과 수변 접근성의 정량화"

서울의 지상철도(101.2km, 2040 서울플랜 명시)가 보행자 이동을 얼마나 막는지 수치로 보여주는 프로젝트.

핵심 지표는 **우회비율(Detour Ratio)**:

```
우회비율 = 실제 보행거리 / 직선거리

예시) 직선 500m → 실제 2,500m → 우회비율 5.0배
```

- 1.0배: 바로 건너갈 수 있음 (단절 없음)
- 3.0배 이상: 눈에 띄는 불편함
- 8.0배 이상: 심각한 단절 (상한값으로 고정)

---

## 2. 접근 방식의 진화

### 단계 1: 수직 샘플링 (초기 버전)

**아이디어**: 철도선을 따라 150m마다 점을 찍고, 수직 방향 250m 떨어진 두 지점 사이의 보행 거리를 비교.

```
     ← 250m → ● 철도 ● ← 250m →
               │
               샘플포인트
```

**문제점**:

- 수직으로 250m 이동한 지점이 한강 한가운데, 산속, 공원 내부에 떨어짐
- "사람이 실제로 이동하는 경로"가 아닌 임의의 좌표
- 결과값의 신뢰성 의심

**산출물**: `output/detour_map.png`, `output/detour_map_interactive.html`

---

### 단계 2: 집계구 OD쌍 (중간 버전)

**아이디어**: 통계청 집계구(~500~1000명 단위 구역) 중심점을 출발지/도착지로 사용. "직선이 철도를 가로지르는 쌍"만 유효 OD쌍으로 선정.

```
● 집계구 중심 (좌)  ──────X──────  ● 집계구 중심 (우)
                      철도 교차 확인
```

**기대효과**: 실제 거주지역 대표 → 강/산 문제 해결

**실제 문제점**:

1. 집계구 중심점이 여전히 한강변 폴리곤, 공원 폴리곤 중심에 떨어짐
2. 보행망에 snap(가장 가까운 도로 노드 찾기)할 때 150m 이내에 도로가 없으면 제외되는데, 이 기준이 너무 관대해서 강/산 포인트가 여전히 포함됨
3. **`gu_name` 전부 "서울시"로 나오는 버그** → 행정구역 코드 체계 혼동 (아래 버그 섹션 참고)

**경로 계산 방식**: OSMnx로 받은 보행 네트워크 위에서 NetworkX Dijkstra 알고리즘

**문제점**: OSMnx 보행 네트워크는 서울 실정을 반영 못함. 지하도, 육교, 아파트 단지 내 동선 누락.

**산출물**: `output/detour_od_map.png`, `output/detour_od_interactive.html`

---

### 단계 3: 버스정류장 OD쌍 + T map API (현재 버전)

**아이디어**:

- **출발/도착지**: 버스정류장 (OSM `highway=bus_stop`)
  - 버스정류장은 반드시 실제 도로 위에 있음 → 강/산 문제 해결
  - 사람이 실제로 이동 기점/종점으로 쓰는 장소
- **경로 계산**: T map 보행자 API
  - 한국 실정 반영 (지하도, 육교, 아파트 단지 경로 포함)
  - 실제 내비게이션 수준의 경로

**API 호출 한도 문제**:

- T map 무료 요금제: 일일 **1,000회** 제한
- 초기 구조 문제: 철도 샘플포인트 1,456개 × K=5 × K=5 = 이론상 36,400쌍
- 교차+거리 필터 통과율 5% 가정해도 **1,820건 초과**

**해결책 — 2단계 분리**:

```
[Phase 1] API 없이 유효 쌍 전체 수집
    - 교차 + 거리 조건만 체크
    - 같은 버스정류장 쌍이 여러 구간에서 중복 등장

[Phase 2] 중복 제거 + 300개 제한 + API 호출
    - (left_stop, right_stop) 고유 쌍만 추출
    - 300개 초과 시 균등 샘플링 (random_state=42)
    - 고유 쌍 1개 = API 1회 (절대 보장)

[Phase 3] 구간별 결과 집계
    - API 결과를 각 철도 구간 포인트에 매핑
```

**산출물**: `output/detour_od_map_v2.png`, `output/detour_od_interactive_v2.html`

---

## 3. 코드 파일별 설명

### `code/01_extract_surface.py`

**역할**: OSM에서 서울 지상철도 추출 및 검증

**처리 흐름**:

1. `osmnx.features_from_place()`로 서울 내 `railway=*` 피처 전체 다운로드
2. 지하 판정 필터 적용 (아래 조건 중 하나라도 해당 시 제거):
   - `tunnel = yes / building_passage / culvert`
   - `layer < 0` (음수 레이어 = 지하)
   - `covered = yes`
3. EPSG:5179으로 투영 후 노선별 길이 계산
4. 2040 서울플랜 공식 수치 101.2km와 오차 비교
5. 정적 지도(PNG) + 인터랙티브 지도(Folium HTML) 생성

**산출물**: `output/surface_rail_seoul.gpkg`, `output/map_static_surface_rail.png`, `output/map_interactive_surface_rail.html`

---

### `code/make_detour_map.py`

**역할**: 수직 샘플링 방식 우회비율 지도 (v1)

**처리 흐름**:

1. 지상철도 추출 (SURFACE_WHITELIST + 터널 필터)
2. 철도 주변 2km 보행망 구축 (OSMnx, 캐시)
3. 철도 따라 150m마다 샘플 → 수직 양쪽 250m 테스트 포인트
4. 각 포인트 → 보행 노드에 snap (KDTree)
5. Dijkstra 최단경로로 좌우 거리 계산 → 우회비율
6. matplotlib LineCollection으로 색상 코딩된 지도 출력

**캐시**: `cache/surface_rail.gpkg`, `cache/walk_graph.pkl`, `cache/detour_results.pkl`

---

### `code/make_detour_map_ver2.py`

**역할**: v1에 인터랙티브 기능 추가 (슬라이더 + 경로 클릭)

**v1 대비 추가 기능**:

- **우회비율 슬라이더**: 특정 배수 이상만 필터해서 보기
- **OD쌍 클릭**: 클릭 시 최악의 OD쌍 경로 시각화
  - 흰 점선: 직선 경로
  - 컬러 실선: 실제 보행 경로
  - 초록 마커: 출발지 / 빨강 마커: 도착지
- **한글 폰트 자동 감지** (macOS/Windows/Linux)
- **Leaflet.js 타이밍 버그 수정** (`window.addEventListener('load', ...)` 적용)

**캐시**: `cache/detour_results_v2.pkl`  
**산출물**: `output/detour_map_interactive_v2.html`

---

### `code/04_detour_engine_od.py`

**역할**: 집계구 OD쌍 방식 (v1, 현재 사용 안 함 — 버스정류장 ver2로 대체)

**특징**:

- 통계청 집계구 SHP + 생활인구 CSV 조인
- 집계구별 인구가중 우회비율 계산
- 행정구역명(`gu_name`) 팝업 표시

**사용 데이터**:

- `data/bnd_oa_11_2025_2Q/bnd_oa_11_2025_2Q.shp` (집계구 경계)
- `data/LOCAL_PEOPLE_20260409.csv` (서울 생활인구, 458,091행)

---

### `code/04_detour_engine_od_ver2.py` ← **현재 주력 스크립트**

**역할**: 버스정류장 OD쌍 + T map 보행자 API (최신 버전)

**핵심 함수**:

| 함수                                      | 역할                                                   |
| ----------------------------------------- | ------------------------------------------------------ |
| `load_rail()`                             | `cache/surface_rail.gpkg` 로드                         |
| `load_bus_stops(rail_gdf)`                | OSMnx로 버스정류장 다운로드 → 철도 1km 이내 최대 300개 |
| `tmap_walk_route(lat1, lon1, lat2, lon2)` | T map 보행자 API 호출 (캐시 우선)                      |
| `_collect_valid_pairs(...)`               | Phase 1: API 없이 유효 쌍 전체 수집                    |
| `compute_od_detour(...)`                  | Phase 2+3: 300개 제한 후 API 호출 + 결과 집계          |
| `make_maps(results, rail_gdf)`            | PNG + Folium HTML 출력                                 |

**캐시 파일**:

- `cache/bus_stops.gpkg`: 버스정류장 위치 (재실행 시 재사용)
- `cache/tmap_routes.pkl`: T map API 응답 캐시 (좌표 4자리 반올림 키)
- `cache/detour_od_results_v3.pkl`: 최종 결과

---

## 4. 사용한 알고리즘 & 핵심 개념

### 4-1. 지상철도 필터링

OSM 태그 기반 3가지 조건으로 지하 구간 제거:

```python
def is_underground(row):
    if tunnel in ("yes", "building_passage", "culvert"): return True
    if layer < 0: return True
    if covered == "yes": return True
    return False
```

**분당선 제거 결정**: OSM 분석 결과 서울 구간 71% `tunnel=yes`, 82% `layer<0` → 전 구간 지하 확인 → SURFACE_WHITELIST에서 제거.

### 4-2. STRtree (공간 인덱스)

"직선이 철도를 교차하는가" 판정 시 사용. 수천 개의 철도 도형을 트리로 인덱싱해서 O(log N) 검색.

```python
rail_strtree = STRtree(rail_geoms)          # 인덱스 구축 (1회)
candidates = rail_strtree.query(line_ab)    # 후보 도형만 추출
crosses = any(line_ab.crosses(rail_geoms[c]) for c in candidates)  # 정밀 판정
```

### 4-3. KDTree (최근접 탐색)

버스정류장/집계구 수천 개 중 "가장 가까운 K개"를 O(log N)으로 찾기.

```python
stops_tree = KDTree(stops_arr)              # 좌표 배열로 트리 구축
_, idxs = stops_tree.query(anchor, k=15)   # 가장 가까운 15개 인덱스 반환
```

### 4-4. T map 보행자 API

```
POST https://apis.openapi.sk.com/tmap/routes/pedestrian

⚠️ 주의: startX = 경도, startY = 위도 (X가 경도!)
응답: features[] 배열 → LineString 좌표 + totalDistance
```

**좌표 순서**: T map 응답 좌표 = `[경도, 위도]` → Folium용 `[위도, 경도]`로 반전 필요.

### 4-5. OD쌍 2단계 분리 (API 한도 대응)

```
문제: 철도 1,456 구간 × 25쌍 = 최대 36,400건 (한도 1,000건 초과)

해결:
  Phase 1 → 유효 쌍 모두 수집 (중복 포함)
  Phase 2 → (left_stop, right_stop) 중복 제거 → 300개 샘플링
  → 고유 쌍 1개 = API 1회 보장 (캐시 재사용)
```

### 4-6. Folium + Leaflet.js 인터랙션

```python
# 슬라이더 HTML 패널 → Folium에 삽입
m.get_root().html.add_child(folium.Element(slider_html))

# JavaScript 로직 (마커 필터링, 경로 표시)
m.get_root().script.add_child(folium.Element(js))
```

**타이밍 버그**: JS 실행 시점에 Leaflet map 변수가 아직 초기화 안 된 문제 → `window.addEventListener('load', ...)` 래핑으로 해결.

---

## 5. 데이터 & 산출물

### 입력 데이터

| 파일                             | 출처             | 내용                             |
| -------------------------------- | ---------------- | -------------------------------- |
| OSM (온라인)                     | OpenStreetMap    | 서울 철도, 보행망, 버스정류장    |
| `data/bnd_oa_11_2025_2Q.shp`     | 통계청           | 집계구 경계 (19,097개)           |
| `data/LOCAL_PEOPLE_20260409.csv` | 서울 데이터 허브 | 생활인구 집계구 단위 (458,091행) |

### 캐시 파일 (`cache/`)

| 파일                       | 생성 스크립트                 | 내용                                  |
| -------------------------- | ----------------------------- | ------------------------------------- |
| `surface_rail.gpkg`        | `make_detour_map_ver2.py`     | 서울 지상철도 선형 (EPSG:5179)        |
| `walk_graph.pkl`           | `make_detour_map_ver2.py`     | OSMnx 서울 보행망 NetworkX 그래프     |
| `bus_stops.gpkg`           | `04_detour_engine_od_ver2.py` | 철도 1km 이내 버스정류장 (최대 300개) |
| `tmap_routes.pkl`          | `04_detour_engine_od_ver2.py` | T map API 응답 캐시                   |
| `detour_od_results_v3.pkl` | `04_detour_engine_od_ver2.py` | 최종 우회비율 결과                    |

### 산출물 (`output/`)

| 파일                             | 내용                                           |
| -------------------------------- | ---------------------------------------------- |
| `detour_map.png`                 | 수직 샘플링 방식 우회비율 지도 (v1)            |
| `detour_map_interactive.html`    | v1 인터랙티브 지도                             |
| `detour_map_interactive_v2.html` | v2 인터랙티브 지도 (슬라이더 + 경로 클릭)      |
| `detour_od_map.png`              | 집계구 OD쌍 방식 지도 (정적)                   |
| `detour_od_map_v2.png`           | 버스정류장 OD쌍 방식 지도 (정적)               |
| `detour_od_interactive_v2.html`  | **최신** 버스정류장 OD + T map 인터랙티브 지도 |

---

## 6. 지금까지 발견한 버그 & 해결책

### 버그 1: `gu_name` 전부 "서울시"

**원인**: 집계구 코드 체계 혼동

- 잘못된 코드: `11110` (법정동코드 체계)
- 실제 데이터: `11010` (통계청 행정구역 코드)

```python
# 잘못된 SEOUL_GU 딕셔너리 (11010, 11020 ... 이 아닌 11010-style)
# ADM_CD 앞 5자리: 11010=종로구, 11020=중구 ... 11250=강동구

SEOUL_GU = {
    "11010": "종로구", "11020": "중구", "11030": "용산구",
    # ... (10 단위 증가, 11110은 노원구)
}
```

**해결**: ADM_CD 값을 직접 출력해서 실제 코드 체계 확인 후 딕셔너리 전면 수정.

### 버그 2: `01_extract_surface.py` 라인 85

**원인**: `name` 컬럼이 없을 때 `series.get().fillna()` 패턴 사용

```python
# 버그: name 컬럼 없으면 get()이 문자열 반환 → .fillna() 실패
surface_m["name"] = surface_m.get("name", "미상").fillna("미상")

# 수정
if "name" in surface_m.columns:
    surface_m["name"] = surface_m["name"].fillna("미상")
else:
    surface_m["name"] = "미상"
```

### 버그 3: Leaflet.js 흰 화면 (`addLayer` TypeError)

**원인**: Folium이 생성한 `<script>` 태그 안의 JS IIFE가 Leaflet `map_xxx` 변수 초기화 전에 실행됨.

```javascript
// 버그: 즉시 실행 → map 변수 undefined
(function() { var map = window['map_xxxxx']; map.addLayer(...); })();

// 수정: load 이벤트 이후 실행
window.addEventListener('load', function() {
    var map = window['map_xxxxx'];
    if (!map) { /* fallback */ }
    map.addLayer(...);
});
```

### 버그 4: T map API 1000건 초과 예상

**원인**: 구간마다 API 호출 → 같은 버스정류장 쌍이 여러 구간에서 중복 호출

**해결**: Phase 1(수집) / Phase 2(API 호출) 분리, `(li, ri)` 중복 제거 후 300개 제한 → 최대 300건 보장.

### 버그 5: 분당선 오분류

**현상**: 분당선이 SURFACE_WHITELIST에 있었으나 위성지도 대조 시 지상 구간 없음  
**확인**: OSM 데이터 분석 → 71% `tunnel=yes`, 82% `layer<0`  
**해결**: `SURFACE_WHITELIST`에서 `"분당선"` 제거 + `cache/surface_rail.gpkg` 삭제 후 재생성

---

## 7. 향후 계획

### 단기 (이번 주)

- [ ] `04_detour_engine_od_ver2.py` 첫 실행 완료
  - OSM 버스정류장 다운로드 (~3분)
  - T map API 300건 호출 (~2-3분)
  - `output/detour_od_interactive_v2.html` 결과 육안 검증
- [ ] 우회비율 높은 구간 Top 5 손으로 확인 (위성지도 대조)
- [ ] 서울 데이터 허브 데이터 수집 시작 (OA-21210 육교, OA-21213 지하도)

### 중기 (다음 2주)

**장벽도로 분석 (`02_extract_barrier_roads.py`)**

- OSM `highway=motorway/trunk` 추출
- 보행 횡단 간격 >500m 구간 = 장벽 판정
- 철도와 동일한 우회비율 분석 적용

**수변 접근성 분석 (`06~07`)**

- 한강, 탄천, 안양천 등 수변 진입점 추출
- 집계구별 수변까지 실제 도달 시간 vs 직선 이상 시간 비교
- "철도에 막혀 물가 못 가는 지역" 시각화

**서울 데이터 허브 활용 강화 (대회 필수)**

- OA-21210 육교 데이터: 보행 횡단점 공간 인덱싱
- OA-21213 지하도 데이터: 지하도 경유 경로 추가
- 발표자료에 "허브 데이터 활용 섹션" 구체화 필수

### 장기 (W3~W5)

**시뮬레이션 (`08_simulation.py`)**

- 우회비율 상위 5개 구간 → 가상으로 지하화(제거) 후 재계산
- Before/After 비교 카드
- "해소 인구 N명, 보행 시간 Xmin 단축" 수치 산출

**OD쌍 개선 옵션** (현재 버스정류장 방식의 한계 보완)

1. **격자 + 도로 snap**: 철도 500m 이내 50m 간격 격자 → 도로 위 포인트만 snap → 가장 체계적이나 API 많이 필요
2. **인구 상위 집계구 + 도로 snap**: centroid 대신 nearest road node 사용 → 강/산 문제 해결 + 인구 대표성 유지
3. **아파트 단지 출입구**: 주거→교통 실제 이동 패턴 반영

---

## 8. 실행 방법

### 환경 세팅

```bash
# 가상환경 (이미 bigdata 이름으로 생성됨)
bigdata/bin/pip install osmnx geopandas folium matplotlib scipy pyproj requests python-dotenv

# .env 파일 (이미 생성됨, 절대 커밋 금지)
# .env 내용: TMAP_API_KEY=<T map 앱키>
```

### 실행 순서

```bash
# Step 1. 지상철도 캐시 생성 (분당선 제외 버전)
#   → cache/surface_rail.gpkg 생성
bigdata/bin/python code/make_detour_map_ver2.py

# Step 2. 버스정류장 OD + T map 우회비율 분석 (현재 주력)
#   첫 실행: OSM 다운로드 ~3분 + API 300건 ~3분
#   재실행: 캐시 사용으로 ~30초
bigdata/bin/python code/04_detour_engine_od_ver2.py

# 결과 확인
open output/detour_od_interactive_v2.html
```

### 캐시 초기화 (재계산 필요 시)

```bash
# 지상철도 재추출 (노선 목록 변경 시)
rm cache/surface_rail.gpkg

# 버스정류장 재다운로드 (파라미터 변경 시)
rm cache/bus_stops.gpkg

# OD 결과 재계산 (API 파라미터 변경 시)
rm cache/detour_od_results_v3.pkl
# (tmap_routes.pkl은 유지 — API 재호출 방지)
```

---

## 참고: 파라미터 튜닝 가이드

`code/04_detour_engine_od_ver2.py` 상단 파라미터:

```python
BUS_STOP_BUFFER_M = 1000   # 철도 몇 m 이내 버스정류장 사용? 높이면 더 많은 정류장
MAX_STOPS         = 300    # 버스정류장 총 수 (API 한도와 연동)
MAX_OD_PAIRS      = 300    # 실제 API 호출 건수 상한 (1000/일 한도 내로 유지)
MIN_OD_DIST_M     = 500    # 너무 가까운 쌍 제외 (500m 미만)
MAX_OD_DIST_M     = 2000   # 너무 먼 쌍 제외 (2km 초과)
K_NEAREST         = 5      # 구간당 각 방향 최근접 정류장 수
RAIL_SAMPLE_M     = 200    # 철도 구간 샘플 간격 (좁힐수록 해상도↑, 쌍 후보↑)
```

**API 초과 시**: `MAX_OD_PAIRS`만 줄이면 됨 (다른 파라미터 건드릴 필요 없음).
