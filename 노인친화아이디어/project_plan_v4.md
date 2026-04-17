# 프로젝트 v4 — "분(分)의 격차"

## 진단에서 처방까지 — 어르신 시간 격차 측정 및 정책 시뮬레이션

> **문서 목적**: (1) 클로드 코드용 기술 명세서, (2) 팀원 발표·협업 기획서.
> **v3 → v4 핵심 변화**: 수요 가중 결합, 간이 입지 최적화 모듈, 시뮬레이션 정적 시각화 추가.

---

## 0. 차별화 선언 (v4의 정체성)

### 0-1. 우리가 **하지 않는** 것 (명시적 기각 항목)

| 흔한 접근                                                 | 왜 안 하는가                                                            |
| --------------------------------------------------------- | ----------------------------------------------------------------------- |
| 도보 N분 시설 커버리지를 메인 지표로 쓰기                 | 모든 시민을 같은 보행속도로 가정. 노인 진단의 핵심을 놓침               |
| 행정동 코로플레스 = 메인 시각화                           | 공간 분포만. 시간 차원 빠짐                                             |
| **2x2 수요-공급 산점도 매트릭스를 메인으로**              | **2025 우승작 핵심 시각화. 메인 채택 시 카피 문제**                     |
| **7대 도메인(의료·교통·복지·인프라·안전·기후·인구) 분류** | **2025 우승작·v1 잔재. 시간축 5개로 차별화 유지**                       |
| **K-means로 행정동을 A/B/C/D 4유형 분류**                 | **2025 우승작과 동일 구조. 시간 결합 유형으로 대체**                    |
| **인터랙티브 웹 대시보드 (클릭 시 실시간 재계산)**        | **시각화 부문이지 개발 부문 아님. 시간 부담. 정적 시뮬레이션으로 충분** |
| 시설 수·종류 다양성 점수화                                | 운영시간을 무시하면 의미 없음                                           |

### 0-2. 우리가 **하는** 것 — 시간축 + 수요 가중 + 처방

| v3에서 v4로                          | 변경 내용                                                                                             |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| 분석 객체 회전                       | 행정동(공간) → **노인 1인의 일상 시간 + 위기 시각** (유지)                                            |
| **수요 결합 (v4 신규)**              | 모든 격차 지표에 65세+ 또는 독거노인 인구 가중 결합 → "분 단위 격차" + "영향받는 노인 인원" 동시 산출 |
| **처방 모듈 추가 (v4 신규)**         | TB6: 정적 시뮬레이션 — 동별 가상 시설 1개 추가 시 격차 감소량 사전 계산 결과를 Before/After 시각화    |
| **시간축 결합 클러스터링 (v4 신규)** | "응급은 양호+위기 시각 사각" 같은 시간 차원 결합 패턴으로 군집화. 4유형 아님.                         |
| **정책 어휘 강화**                   | "유니버설 디자인 보정 도구", "생활밀착형 행정모델 정합" 등 서울시 정책 언어 명시 채용                 |

### 0-3. 한 줄 정의

> **2040 서울도시기본계획이 약속한 "보행 30분 자족 생활권"은 표준 시민의 시간이다. 노인의 시간으로 환산하면 그 약속은 60분이 되고, 위기 시각에는 영(零)이 된다. 본 프로젝트는 그 격차를 분(分)·인원으로 측정하고, 시설 1개 추가의 정책 효과를 계산한다.**

---

## 1. 핵심 문제의식 (1페이지 발표용)

### 1-1. 2040 계획의 보이지 않는 가정

2040 서울도시기본계획은 "도보 30분 자족적 생활권"을 핵심 비전으로 제시한다(p.46). 그러나 이 30분은 **표준 시민의 보행속도(약 4 km/h, 1.1 m/s)** 를 가정한다. 같은 계획서는 시 인구의 19%(2025)가 65세 이상이며 2040년에는 32%에 이를 것이라고도 명시한다(p.27). 약속된 시간과 그 약속을 받을 시민의 시간이 일치하지 않는다.

### 1-2. 노인의 시간은 어떻게 다른가 (출처 있는 수치)

| 차원                    | 표준 시민 | 65~74세  | 75~84세  | 85세+    |
| ----------------------- | --------- | -------- | -------- | -------- |
| 보행속도 (m/s)          | 1.1 ~ 1.4 | 0.95     | 0.78     | 0.58     |
| 도보 30분 도달 거리 (m) | 약 2,000  | 약 1,710 | 약 1,400 | 약 1,040 |
| 1 km 도달 시간 (분)     | 12.5      | 17.5     | 21.4     | 28.7     |

> 출처: Bohannon (1997) "Comfortable and maximum walking speed of adults aged 20-79"; Studenski et al. (2011) JAMA. 한국 노인 평균 0.78 m/s 채택.

→ **계획의 30분 약속은 65~74세에게는 약 35분, 75세 이상에게는 약 45분, 85세 이상에게는 약 60분**.

### 1-3. 시간은 보행만의 문제가 아니다

| 시간 차원         | 표준 시민에겐 무관 | 노인에겐 결정적                                  |
| ----------------- | ------------------ | ------------------------------------------------ |
| **응급 골든타임** | 평소 의료 접근성   | 낙상 1시간, 열사병 30분, 뇌졸중 4.5시간 골든타임 |
| **시설 운영시간** | 9-18시면 충분      | 야간·새벽 응급, 주말 외로움 시간                 |
| **위기 시각**     | 평균 분석          | 폭염 정오, 한파 새벽 결정적                      |
| **외로움 시간대** | 평균 사회 접촉     | 일요일, 명절, 야간이 위험 시각                   |

### 1-4. 공간 평등 ≠ 시간 평등

> **물리적 공간은 평등하지만, 생물학적 시간은 불평등하다. 정책의 표준이 누군가에게는 배제의 기준이 된다.**
>
> 본 진단은 2040 도시기본계획을 부정하지 않는다. 오히려 그 계획이 **유니버설 디자인(Universal Design)** 을 획득하기 위해 필요한 **개인화된 시간 보정 도구**다.

---

## 2. 핵심 메시지 4개 (발표 결론으로 이어질 메시지)

### M1. 약속된 30분, 실제 60분 (진단)

청년 보행 30분권과 노인 보행 30분권의 면적 격차를 동 단위로 측정. **단순 면적 비교가 아니라 그 격차에 거주하는 노인 인원**까지 동시 산출.

### M2. 시설은 살아있나 (운영시간 진단)

노인이 가장 필요한 시간(야간 응급, 주말 외로움, 폭염 정오)에 보건소·복지관·쉼터의 몇 %가 작동하는지 측정. "주간 평균"이 가린 운영시간 사각.

### M3. 골든타임의 외곽 (응급 진단)

119 출동 + 응급실 도달 시간 합산이 골든타임을 초과하는 동의 65세 이상 인구. "응급의 외곽"에 서울 노인 몇 %가 살고 있나.

### M4. 시설 1개의 가치 (처방·v4 신규)

TB1~TB5 진단 결과 기반으로 그리드 후보지에 가상 시설 1개 추가 시 격차 감소량 사전 계산. **"X동 좌표 (Y, Z)에 야간 약국 1개 추가 → 격차 영향 노인 N명 → M명으로 감소"** 같은 처방형 결론.

---

## 3. 분석 프레임 — 6개 모듈 (v3 5개 + v4 신규 1개)

> 데이터셋, 파생 변수, 시각화는 **모두 시간 단위(분, 시각, 시간대) 또는 인원 단위(명)** 로 정렬. z-score 합성이 아닌 **분(分)·인원 격차** 단위로 발표.

---

### TB1. 보행 시간 격차 (Walking Time Gap) — v4 수요 가중 강화

**측정 대상**:

- (v3) 청년 30분권 면적 vs 노인 30분권 면적 격차
- **(v4 신규) 그 격차에 거주하는 65세+ 인구 인원**

**데이터**:
| # | 데이터 | ID | 출처 |
|---|--------|-----|------|
| 1 | 행정동 경계 shapefile | — | 통계청 SGIS |
| 2 | OSM 보행 가능 도로망 (서울) | — | OpenStreetMap |
| 3 | 65세+ 인구 (동별) | 통계청 KOSIS | — |
| 4 | 75세+ 인구 (동별) | 통계청 KOSIS | — |
| 5 | 행정동별 인구밀도 | (3에서 도출) | — |
| **6** | **격자(500m grid) 인구 분포 (보간)** | **(3,4 + shapefile에서 도출)** | **— (v4 신규: 인원 가중 위해 필요)** |

**핵심 산출 로직** (v4 수정):

```python
import osmnx as ox
import networkx as nx
from shapely.ops import unary_union

G = ox.graph_from_place('Seoul, South Korea', network_type='walk')

SPEED_YOUNG = 1.20  # m/s
SPEED_75 = 0.78     # m/s

def isochrone_polygon(G, center_node, speed_mps, time_min):
    travel_time = nx.single_source_dijkstra_path_length(
        G, center_node, cutoff=time_min*60,
        weight=lambda u,v,d: d['length']/speed_mps)
    nodes_geom = [Point(G.nodes[n]['x'], G.nodes[n]['y']) for n in travel_time]
    return alpha_shape(nodes_geom, alpha=0.005)

# (v4 신규) 500m 격자 인구 분포 보간
grid = make_grid(seoul_boundary, cell_size=500)
grid_pop = interpolate_population(grid, df_pop_dong, gdf_admin)
# 각 격자에 65+ 인구, 75+ 인구, 독거노인 인구 추정 컬럼 부여

df_walk = []
for _, dong in gdf_admin.iterrows():
    center = nearest_node(G, dong.population_weighted_center)
    iso_young = isochrone_polygon(G, center, SPEED_YOUNG, 30)
    iso_old = isochrone_polygon(G, center, SPEED_75, 30)

    gap_polygon = iso_young.difference(iso_old)
    gap_area_km2 = gap_polygon.area / 1e6

    # (v4 신규) 격차 영역에 거주하는 노인 인원
    gap_grids = grid[grid.intersects(gap_polygon)]
    senior_in_gap = (gap_grids.geometry.intersection(gap_polygon).area /
                     gap_grids.geometry.area * gap_grids.pop_65plus).sum()

    df_walk.append({
        'adm_dr_cd': dong.adm_dr_cd,
        'iso_young_km2': iso_young.area / 1e6,
        'iso_old_km2': iso_old.area / 1e6,
        'walk_gap_ratio': 1 - iso_old.area / iso_young.area,
        'minutes_to_match_young': time_to_reach_same_area(G, center, SPEED_75, iso_young.area),
        # v4 신규
        'senior_in_walk_gap': senior_in_gap,
        'solo_senior_in_gap': estimate_solo_senior(gap_polygon, grid),
    })
```

**핵심 파생 변수**:
| 변수 | 단위 | 의미 |
|------|------|------|
| `walk_gap_ratio` | 0~1 | 청년 30분권 대비 노인 30분권 면적 손실 비율 |
| `minutes_to_match_young` | 분 | 청년 30분권을 노인이 도달하려면 몇 분 |
| **`senior_in_walk_gap`** | **명 (v4 신규)** | **격차 영역에 거주하는 65세+ 추정 인원 — 이게 정책 우선순위 핵심** |
| **`solo_senior_in_gap`** | **명 (v4 신규)** | **격차 영역 거주 독거노인 추정 인원** |

**시각화 산출물**:

- **TB1-A**: 단일 동 줌인 — 청년 isochrone(연한 색) 위에 노인 isochrone(진한 색) 오버레이. 격차 영역에 점밀도(인구) 오버레이 추가.
- **TB1-B**: 서울 전체 코로플레스 — `minutes_to_match_young` (분 단위 수치) + 동별 라벨에 `senior_in_walk_gap` 인원 표시.
- **TB1-C**: 사다리 차트 (slope chart) — 가로축 청년/노인 두 그룹, 세로축 시간(분). 동별 격차 라인.
- **TB1-D (v4 신규)**: **인원 가중 막대 차트** — TOP 20 동의 `senior_in_walk_gap` 인원. "면적 격차 1위와 인원 격차 1위가 다르다" 폭로.

**구현 가능성**: ★★★★☆

---

### TB2. 응급 골든타임 사각 (Emergency Golden Time) — v4 수요 가중 강화

**측정 대상**:

- (v3) 119 출동 + 응급실 도착이 골든타임 초과인 동 면적 비율
- **(v4 신규) 골든타임 사각에 거주하는 65세+ 인구 인원 + 자치구별 합계**

**데이터** (v3와 동일):
| # | 데이터 | 출처 |
|---|--------|------|
| 1 | 서울시 119안전센터 위치 | 열린데이터광장 OA-21072 |
| 2 | 서울시 응급의료기관 위치 | 공공데이터포탈 (보건복지부) |
| 3 | 야간 응급실 운영 정보 | 보건복지부 응급의료포털 OpenAPI |
| 4 | 자치구별 응급환자 도착 시간 | 소방청 통계 |
| 5 | 노인 응급질환 통계 | OA-12603 |
| 6 | (v4) 격자 인구 (TB1과 공유) | — |

**노인 4대 응급 골든타임**:

- 낙상 → **60분** (메인)
- 뇌졸중 → 4.5시간
- 심근경색 → 90분
- 열사병 → **30분** (보수 기준)

**핵심 산출 로직** (v4 수정):

```python
G_drive = ox.graph_from_place('Seoul', network_type='drive')

dispatch_time = 6
golden_time = 60
on_scene_time = 5
travel_budget = golden_time - dispatch_time - on_scene_time  # 49분

er_locations = pd.read_csv('emergency_rooms.csv')
er_isochrones = []
for _, er in er_locations.iterrows():
    er_node = ox.distance.nearest_nodes(G_drive, er.lon, er.lat)
    iso = isochrone_polygon(G_drive, er_node,
                            speed_mps=25*1000/3600,
                            time_min=travel_budget)
    er_isochrones.append(iso)
reachable = unary_union(er_isochrones)

df_em = []
for _, dong in gdf_admin.iterrows():
    out_polygon = dong.geometry.difference(reachable)
    out_ratio = out_polygon.area / dong.geometry.area

    # (v4 신규) 사각 영역 거주 노인 인원 (격자 보간)
    out_grids = grid[grid.intersects(out_polygon)]
    senior_outside = (out_grids.geometry.intersection(out_polygon).area /
                      out_grids.geometry.area * out_grids.pop_65plus).sum()

    df_em.append({
        'adm_dr_cd': dong.adm_dr_cd,
        'er_outside_ratio': out_ratio,
        'senior_outside_60min': senior_outside,
        # 더 엄격한 30분 기준도 함께 계산
        'senior_outside_30min': compute_outside_for_budget(19, dong, grid),
    })
```

**핵심 파생 변수**:
| 변수 | 단위 | 의미 |
|------|------|------|
| `er_outside_ratio` | 0~1 | 동 면적 중 60분 골든타임 밖 비율 |
| **`senior_outside_60min`** | **명 (v4 신규)** | **낙상 골든타임 밖 65세+ 추정 인원** |
| **`senior_outside_30min`** | **명 (v4 신규)** | **열사병 골든타임 밖 65세+ 추정 인원 — 폭염 시즌 결정적** |

**시각화 산출물**:

- **TB2-A**: 응급실 60분 등시선 지도 + 사각 영역 별도 색칠. 사각 영역에 노인 인구 점밀도 오버레이.
- **TB2-B**: 자치구별 골든타임 밖 65세+ 인구 막대 차트 — **합계 인원 라벨 명시**.
- **TB2-C**: 시간대별 변동 — 출퇴근(차량 속도 저하) 적용 시 사각 인원 증가 비교.
- **TB2-D (v4 신규)**: **30분 vs 60분 비교 듀얼 패널** — "낙상 사각" vs "열사병 사각" 인원 차이 시각화.

**구현 가능성**: ★★★★☆

---

### TB3. 24시간 돌봄 가용성 (Care Availability Hours) — v4 동일 (이미 시간축)

> v3 그대로. 시간축 자체이므로 수요 가중은 합성 단계에서 결합.

**측정 대상**: 24시간을 4구간으로 나누고 각 구간에 가용한 노인 관련 시설 비율

**데이터** (v3와 동일):

- OA-12420 노인여가복지시설
- 보건소·보건분소·보건지소
- OA-1170 / 심평원 약국
- 자치구별 심야약국 / 일요당번약국

**구간 정의**:

- B1 평일 주간 (월-금 09-18시)
- B2 평일 야간 (월-금 18-09시)
- B3 주말 주간 (토-일 09-18시)
- B4 주말 야간 (토-일 18-09시)

**핵심 산출 로직**: v3 코드 유지 (`gap_b2`, `gap_b4`, `dead_hours_dong`).

**v4 추가**: 합성 단계에서 `dead_hours_dong` × 동별 65세+ 인구 → 영향 인원 산출.

**시각화**: v3 그대로 (TB3-A 시계 차트, TB3-B 동×시간대 히트맵, TB3-C 자치구 분산).

---

### TB4. 위기 시각 쉼터 도달 (Crisis-Hour Shelter) — v3 자체에 이미 인원 포함

> v3에서 이미 `senior_solo_at_risk_heat` 인원 단위로 계산. 유지.

**측정 대상**: 폭염 정오·한파 새벽에 75세+ 노인이 노인 보행속도로 도보 15분 내 가용 쉼터 도달 가능 인구 비율

**데이터** (v3와 동일, 모두 서울 데이터 허브 ✅):

- OA-21065 무더위쉼터
- OA-21066 한파쉼터
- OA-462 독거노인 (동별)
- 기상청 폭염일수·열대야일수 (자치구)

**핵심 산출**: v3 코드 유지.

**v4 미세 보강**: 운영시간 데이터를 OA-21065에서 직접 파싱하여 "정오 가동 쉼터만 필터링" 로직 명확화.

**시각화**: v3 그대로 (TB4-A 듀얼 맵, TB4-B 위험 시각 정점, TB4-C 위험 동 막대).

---

### TB5. 외로움 시간대 사회적 접점 (Isolation Hours Touch) — v3 동일

> v3 그대로. 이미 인원 단위 (`loneliness_load_b4`, `dead_zone_solo`).

**측정 대상**: 독거노인 외로움 위험 시각(주중 야간 + 일요일 + 명절)에 도보 15분(노인 속도) 내 가용 사회적 접점 수

**데이터** (v3와 동일):

- OA-462 독거노인
- 전통시장, 종교시설, 공원, 24시간 편의점

**시각화**: v3 그대로.

---

### TB6. 정책 시뮬레이션 — 시설 1개의 가치 (v4 신규 핵심 모듈)

> **이게 v4의 가장 큰 차별화 카드.** 진단을 처방으로 전환하는 모듈.

**측정 대상**: 그리드(500m 격자) 위 후보 지점에 가상 시설 1개 추가 시 격차 감소량 (분·인원 단위)

**대상 시설 유형 4종**:

1. **응급 야간 거점** (TB2 사각 + TB3 야간 사막 해소)
2. **무더위·한파 쉼터** (TB4 위기 시각 사각 해소)
3. **노인복지시설** (TB1 보행 격차 + TB5 외로움 사각 해소)
4. **저상버스 정류장** (TB1 보행 격차 보완)

**핵심 산출 로직** (v4 신규):

```python
# (1) 후보 그리드 생성 (서울 전체 500m 격자, 약 1500개)
candidate_grid = make_grid(seoul_boundary, cell_size=500)

# (2) 각 시설 유형별 후보 점수 계산
def simulate_facility_addition(facility_type, candidate_point):
    """가상 시설 1개를 candidate_point에 추가했을 때 격차 변화 계산"""

    # 영향 받는 동 식별 (15분 노인 보행 = 700m 반경)
    affected_dongs = gdf_admin[gdf_admin.distance(candidate_point) < 1500]

    # 시설 유형별 격차 감소 계산
    if facility_type == 'er_night':
        # TB2 사각 영역 중 이 후보지에서 49분 내 도달 가능 영역
        new_iso = isochrone_polygon(G_drive, nearest_node(G_drive, candidate_point),
                                     speed_mps=25*1000/3600, time_min=49)
        before_uncovered = current_uncovered_polygon  # TB2 사각 합집합
        after_uncovered = before_uncovered.difference(new_iso)
        senior_relieved = senior_population_in_polygon(
            before_uncovered.difference(after_uncovered), grid)
        return senior_relieved

    elif facility_type == 'heat_shelter':
        # TB4 폭염 사각 영역 중 이 후보지에서 노인 도보 15분 도달 가능 영역
        new_iso = isochrone_polygon(G, nearest_node(G, candidate_point),
                                     speed_mps=0.78, time_min=15)
        before_at_risk = current_heat_at_risk_polygon
        senior_relieved = solo_senior_in_polygon(
            before_at_risk.intersection(new_iso), grid)
        return senior_relieved

    # ... 그 외 유형 동일 패턴

# (3) 모든 후보지 × 모든 시설 유형 점수화
results = []
for facility_type in ['er_night', 'heat_shelter', 'welfare', 'lf_bus']:
    for _, candidate in candidate_grid.iterrows():
        score = simulate_facility_addition(facility_type, candidate.geometry.centroid)
        results.append({
            'facility_type': facility_type,
            'candidate_lon': candidate.geometry.centroid.x,
            'candidate_lat': candidate.geometry.centroid.y,
            'sgg_cd': spatial_join_sgg(candidate),
            'senior_relieved': score,
        })
df_sim = pd.DataFrame(results)

# (4) 시설 유형별 TOP 10 최적 입지 선정
top_candidates = df_sim.groupby('facility_type').apply(
    lambda x: x.nlargest(10, 'senior_relieved')
).reset_index(drop=True)
```

**핵심 파생 변수**:
| 변수 | 단위 | 의미 |
|------|------|------|
| `senior_relieved` | 명 | 후보지에 시설 추가 시 격차에서 벗어나는 65세+ 인원 |
| `cost_efficiency_rank` | 순위 | 시설 유형별 인원 효과 상위 N개 |

**시각화 산출물 — TB6 (가장 강력한 메인 시각화)**:

- **TB6-A**: **Before/After 듀얼 맵** — 좌: 현재 사각, 우: 시설 1개 추가 후 사각. 각각의 사각 인원 수치 라벨.
- **TB6-B**: **시설 유형별 TOP 10 최적 입지 점 지도** — 4개 시설 유형을 다른 색·기호로 표시. 각 점에 `senior_relieved` 인원 라벨.
- **TB6-C**: **자치구별 시설 1개 추가 효과 비교 막대** — "강북구 X동에 응급 야간 거점 1개 = 노인 N명 구제. 같은 시설을 강남구에 두면 M명 (M < N)" 같은 비교.

**구현 가능성**: ★★★☆☆ (계산 부담 있으나 그리드 1500개 × 4유형 = 6000회 isochrone 계산. 멀티프로세싱 + 캐시로 가능. dev는 그리드 200개로 prototyping)

---

## 4. 합성 지표 — "분(分)+인원" 종합

### 4-1. 동별 종합 격차 지수 (v3 그대로 + 인원 추가)

```python
df_total = (df_walk
    .merge(df_em, on='adm_dr_cd')
    .merge(care_24h, on='adm_dr_cd')
    .merge(df_crisis, on='adm_dr_cd')
    .merge(df_loneliness, on='adm_dr_cd'))

# (a) 시간 단위 격차
df_total['gap_walk_min'] = df_total['minutes_to_match_young'] - 30
df_total['gap_emergency_pct'] = df_total['er_outside_ratio'] * 100
df_total['gap_care_hours_pct'] = (1 - df_total['gap_b4']) * 100
df_total['gap_crisis_pct'] = (1 - df_total['heat_noon_reach_75']) * 100
df_total['gap_loneliness_load'] = df_total['loneliness_load_b4'].clip(upper=100)

# (b) v4 신규: 인원 단위 격차 (절대 영향 인구)
df_total['affected_walk'] = df_total['senior_in_walk_gap']
df_total['affected_emergency'] = df_total['senior_outside_60min']
df_total['affected_crisis'] = df_total['senior_solo_at_risk_heat']
df_total['affected_loneliness'] = df_total['dead_zone_solo']

# 종합 시간 격차 지수 (수치 단위 통일을 위한 가중)
df_total['총격차_지수'] = (
    df_total['gap_walk_min'] +
    df_total['gap_emergency_pct'] * 0.6 +
    df_total['gap_care_hours_pct'] * 0.3 +
    df_total['gap_crisis_pct'] * 0.4 +
    np.log1p(df_total['gap_loneliness_load']) * 5
)

# v4 신규: 인원 단위 종합 영향
df_total['총영향_인원'] = (
    df_total['affected_walk'] +
    df_total['affected_emergency'] +
    df_total['affected_crisis'] +
    df_total['affected_loneliness']
)
# (중복 카운트 가능성 — 발표 시 "지표별 영향 인원의 단순 합산이며 중복 가능"으로 명시)

# 5등급 분류
from jenkspy import JenksNaturalBreaks
jnb = JenksNaturalBreaks(5)
jnb.fit(df_total['총격차_지수'])
df_total['grade'] = jnb.labels_
```

### 4-2. 시간축 결합 클러스터링 (v4 신규, 4유형 분류 아님)

> 2025 우승작의 A/B/C/D 단순 분류와 차별화. **시간 차원의 결합 패턴**으로 군집화.

```python
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# 입력 = 5개 시간 격차 지표 (시간 차원만, z-score 표준화)
X = StandardScaler().fit_transform(df_total[
    ['gap_walk_min','gap_emergency_pct','gap_care_hours_pct',
     'gap_crisis_pct','gap_loneliness_load']
])
km = KMeans(n_clusters=5, random_state=42, n_init=20)
df_total['시간격차_유형'] = km.fit_predict(X)

# 군집별 평균 프로필 → 시간 차원 결합 라벨링
profiles = df_total.groupby('시간격차_유형')[
    ['gap_walk_min','gap_emergency_pct','gap_care_hours_pct',
     'gap_crisis_pct','gap_loneliness_load']].mean()

# 라벨링은 군집 평균 프로필 보고 수동 (예시)
LABELS = {
    0: '시간 평등형',                # 모든 시간 격차 낮음
    1: '응급 사각 + 위기 시각 붕괴형',  # TB2, TB3, TB4 동시 취약
    2: '보행 격차 단독형',            # TB1만 큼
    3: '외로움 시간 단독형',          # TB5만 큼
    4: '복합 시간 사각형',            # TB1+TB2+TB4 동시 취약
}
```

**중요 차별화**: 4가지 알파벳 라벨이 아니라 **"무엇 + 무엇이 동시에 취약한가"** 의 시간 결합 라벨. 정책 처방이 시간 차원별로 다름.

---

## 5. 시각화 산출물 — 시간축 + 처방 메인

> **원칙**: 코로플레스는 보조. 메인은 등시선·시계·시간 격차 사다리 + **(v4 신규) Before/After 시뮬레이션 맵**.

| 산출물                                   | 유형                        | 도구               | 차별화 포인트                               |
| ---------------------------------------- | --------------------------- | ------------------ | ------------------------------------------- |
| 종합 등시선 비교 지도                    | 등시선 (isochrone) 오버레이 | matplotlib + osmnx | 청년·노인 동시 표현                         |
| 24시간 시계 패널                         | Polar bar (시계 모양)       | matplotlib         | 시간 차원 직관                              |
| 위기 시각 듀얼 맵                        | 등시선 + 인구밀도 hexbin    | matplotlib         | 시간+공간 결합                              |
| 시간 격차 사다리 차트                    | Slope chart                 | matplotlib         | "분의 격차" 직관                            |
| 응급실 60분 사각 지도                    | 등시선 (역방향)             | osmnx + matplotlib | "사각" 강조 색상                            |
| 동 × 시간대 히트맵                       | Cell heatmap                | matplotlib         | "사막 시간대" 발견                          |
| 위기 시각 정점 차트                      | 시계열 라인 + 정점 강조     | matplotlib         | 의학적 근거 시각화                          |
| 168시간 외로움 곡선                      | 7일 × 24시간 폴딩 라인      | matplotlib         | 주간 패턴 폭로                              |
| **(v4) Before/After 시뮬레이션 듀얼 맵** | **등시선 듀얼 패널**        | **matplotlib**     | **처방형 시각화**                           |
| **(v4) 시설 유형별 최적 입지 점 지도**   | **점 지도 + 인원 라벨**     | **matplotlib**     | **"여기가 1순위" 명시**                     |
| **(v4) 시설 1개 효과 자치구 비교 막대**  | **막대 차트**               | **matplotlib**     | **"강북에 두면 N명, 강남에 두면 M명" 비교** |
| 시간격차 결합 유형 분포 지도             | 코로플레스 (5유형 색상)     | Tableau            | 동별 결핍 패턴                              |
| Tableau 종합 대시보드                    | 다중 시트                   | Tableau            | 인터랙티브 보조 (필터링만)                  |

---

## 6. PPT 슬라이드 매핑 (18슬라이드 권장, v4 신규 슬라이드 강조)

| #                | 슬라이드                                                           | 시각 자료                      | 단계                        |
| ---------------- | ------------------------------------------------------------------ | ------------------------------ | --------------------------- |
| 1                | 표지 — "분의 격차"                                                 | —                              | —                           |
| 2                | 문제 인식: 2040 약속의 숨은 가정                                   | 보행속도 비교 표               | **Phase 1: 약속의 환상**    |
| 3                | 노인 시간은 다르게 흐른다 — 4가지 시간 차원                        | 인포그래픽                     | Phase 1                     |
| 4                | TB1: 청년 30분권 vs 노인 30분권 등시선                             | TB1-A                          | **Phase 2: 시간 격차 진단** |
| 5                | TB1: 서울 전체 분의 격차 + **인원 가중**                           | TB1-B + TB1-D                  | Phase 2                     |
| 6                | TB2: 응급 골든타임 사각 + **인원**                                 | TB2-A + TB2-B                  | Phase 2                     |
| 7                | TB3: 24시간 시계 — 시설은 살아있나                                 | TB3-A + TB3-B                  | **Phase 3: 위기 시각 붕괴** |
| 8                | TB4: 위기 시각 듀얼 맵 (폭염/한파)                                 | TB4-A + TB4-B                  | Phase 3                     |
| 9                | TB5: 외로움 시간대 사각지대                                        | TB5-A + TB5-B                  | Phase 3                     |
| 10               | 종합: 분의 격차 지수 분포                                          | 코로플레스 + 등급 분포         | **Phase 4: 종합 진단**      |
| 11               | 종합: 권역 × 시간축 약점 매트릭스                                  | 5×5 매트릭스                   | Phase 4                     |
| 12               | 종합: 시간격차 결합 5유형 분포 지도                                | 코로플레스 5유형               | Phase 4                     |
| **13 (v4 신규)** | **TB6: 시설 1개의 가치 — 처방 시뮬레이션 개요**                    | **인포그래픽 (4개 시설 유형)** | **Phase 5: 처방**           |
| **14 (v4 신규)** | **TB6-A: 응급 야간 거점 Before/After 듀얼 맵**                     | **TB6-A**                      | **Phase 5**                 |
| **15 (v4 신규)** | **TB6-B: 시설 유형별 TOP 10 최적 입지 점 지도**                    | **TB6-B**                      | **Phase 5**                 |
| **16 (v4 신규)** | **TB6-C: 시설 1개 효과 자치구 비교**                               | **TB6-C**                      | **Phase 5**                 |
| 17               | 정책 시나리오 3가지 — 진단 + 처방 통합                             | 줌인 + 수치                    | Phase 5                     |
| 18               | 결론: 2040 계획 KPI 시간·인원 단위 보강 + 생활밀착형 행정모델 정합 | 표                             | Phase 5                     |

---

## 7. 정책 인사이트 시나리오 (3가지, v4 처방 강화)

### 시나리오 1: 응급 사각 동 (진단 + TB6 처방)

> **진단**: "노원구 X동 75세+ 인구 Y명 중 N명(M%)이 119 출동 + 응급실 도착 60분 골든타임 밖에 거주. 가장 가까운 응급실까지 평균 N분 소요."
>
> **처방 (TB6 결과)**: "동 내 좌표 (위도, 경도)에 야간 응급 1차 처치 거점 1개 신설 시 영향 노인 N명 → M명으로 감소. 같은 예산으로 강남구에 동일 거점 신설 시 효과 K명 (K << N-M). → 비용 효율 비교 시 노원구 X동이 우선순위 1위."

### 시나리오 2: 폭염 정오 쉼터 사각 (진단 + TB6 처방)

> **진단**: "동작구 Y동: 폭염일수 자치구 평균 상위 10% × 75세+ 독거노인 비율 30% × 정오 가용 쉼터 도보 15분 도달률 12%. 위험 인원 N명."
>
> **처방 (TB6 결과)**: "그리드 분석 결과 좌표 (위도, 경도) — 인근 경로당 부지 — 에 폭염 특별기간 정오~16시 한정 무더위쉼터 임시 지정 시 도달률 12% → 67%로 개선. 위험 인원 N명 → M명. 시설 신설이 아닌 운영시간 확대로 가능."

### 시나리오 3: 외로움 시간대 야간 돌봄 거점 (진단 + TB6 처방)

> **진단**: "강북구 Z동: 독거노인 N명 중 주말 야간 도보 15분 내 가용 사회적 접점 0개. 가장 가까운 24시간 편의점까지 노인 보행 22분."
>
> **처방 (TB6 결과)**: "주민센터 부지(좌표 표시)를 주말 야간 '야간 돌봄 거점'으로 운영 시 사각 인원 N명 → 0명. 신축 비용 0원, 운영비만 추가."

---

## 8. 데이터 가용성 + 우회 전략 (v3와 동일 + v4 추가)

| 잠재 리스크                                            | 우회 전략                                                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| OSM 도로망에 일부 좁은 골목 누락                       | 알파 셰이프 적용 시 보수적 추정. 한계 명시.                                                  |
| 시설 운영시간 데이터 산발적                            | 시설 유형별 표준 운영시간 가정 + 데이터 있는 시설은 실측. 가정값 부록 명시.                  |
| 응급실 데이터 야간 운영 정보                           | 응급의료포털 OpenAPI 호출. 실패 시 24시간 응급실만 보수적으로 사용.                          |
| 119 출동 시간 동별 변동                                | 자치구 평균 적용. 한계 명시.                                                                 |
| 65세+ 동별 인구 vs 75세+ 동별 인구                     | 75세+ 동별 미공개 시 자치구 75세+ 비율을 동별 65세+에 적용.                                  |
| isochrone 계산 시간 (467 동 × 여러 속도)               | 멀티프로세싱 + 결과 캐시. dev 단계는 중심점 100개로 prototyping.                             |
| **(v4) TB6 시뮬레이션 계산 부담 (1500 후보 × 4 유형)** | **그리드 해상도 단계적 적용: dev 단계 200개, 최종 1500개. 캐시 전제. 결과는 정적 PNG 산출.** |
| **(v4) 격자 인구 보간 정확도**                         | **dasymetric 기법 (건물 footprint 가중 보간) — 시간 부족 시 동 면적 균등 분포로 fallback**   |

---

## 9. 클로드 코드 작업 명세 (Claude Code Brief)

### 9-1. 환경 및 의존성

```bash
python -m venv .venv && source .venv/bin/activate
pip install osmnx==2.0.* networkx geopandas shapely pyproj rtree
pip install pandas numpy scipy scikit-learn
pip install matplotlib seaborn plotly jenkspy
pip install requests xlrd openpyxl
pip install rasterio  # (v4 신규: 격자 인구 보간용)
```

### 9-2. 디렉토리 구조 (v4 업데이트)

```
project/
├── data/
│   ├── raw/
│   │   ├── seoul_data_hub/   # OA-462, OA-21065, OA-21066
│   │   ├── open_data/        # OA-12420 등
│   │   └── public_portal/    # 응급실, 약국 등
│   ├── interim/
│   ├── processed/
│   └── shapefiles/
├── src/
│   ├── common/
│   │   ├── admin_master.py
│   │   ├── osm_graph.py
│   │   ├── isochrone.py
│   │   ├── grid_population.py    # (v4 신규: 격자 인구 보간)
│   │   └── normalization.py
│   ├── timebands/
│   │   ├── tb1_walking_gap.py    # (v4 수정: 인원 가중 추가)
│   │   ├── tb2_emergency.py      # (v4 수정: 인원 가중 추가)
│   │   ├── tb3_care_24h.py
│   │   ├── tb4_crisis_hour.py
│   │   └── tb5_loneliness.py
│   ├── synthesis/
│   │   ├── total_gap_index.py
│   │   ├── time_gap_clustering.py  # (v4 신규)
│   │   └── kwon_yeok_matrix.py
│   ├── simulation/                  # (v4 신규: 처방 모듈)
│   │   ├── candidate_grid.py
│   │   ├── simulate_er_night.py
│   │   ├── simulate_shelter.py
│   │   ├── simulate_welfare.py
│   │   └── simulate_lf_bus.py
│   └── viz/
│       ├── tb1_charts.py
│       ├── ...
│       ├── synthesis_charts.py
│       └── simulation_charts.py     # (v4 신규)
├── outputs/
│   ├── figures/
│   ├── tables/
│   └── tableau/
├── notebooks/
│   └── exploratory.ipynb
├── docs/
│   └── seoul_data_hub_evidence/
└── README.md
```

### 9-3. 단계별 실행 명령어

```bash
# Stage 1: 공통 인프라
python -m src.common.admin_master
python -m src.common.osm_graph --cache
python -m src.common.grid_population   # v4 신규

# Stage 2: 시간축별 산출 (병렬 가능)
python -m src.timebands.tb1_walking_gap
python -m src.timebands.tb2_emergency
python -m src.timebands.tb3_care_24h
python -m src.timebands.tb4_crisis_hour
python -m src.timebands.tb5_loneliness

# Stage 3: 합성
python -m src.synthesis.total_gap_index
python -m src.synthesis.time_gap_clustering   # v4 신규
python -m src.synthesis.kwon_yeok_matrix

# Stage 4 (v4 신규): 시뮬레이션
python -m src.simulation.candidate_grid
python -m src.simulation.simulate_er_night
python -m src.simulation.simulate_shelter
python -m src.simulation.simulate_welfare
python -m src.simulation.simulate_lf_bus

# Stage 5: 시각화
python -m src.viz.tb1_charts
# ...
python -m src.viz.synthesis_charts
python -m src.viz.simulation_charts   # v4 신규
```

### 9-4. 검증 기준 (Acceptance Criteria)

| 모듈                        | 출력 파일                              | 검증                                                         |
| --------------------------- | -------------------------------------- | ------------------------------------------------------------ |
| common.admin_master         | `data/interim/admin_master.csv`        | 426개 행정동 × 권역 매핑                                     |
| common.osm_graph            | `data/shapefiles/seoul_walk.graphml`   | 그래프 노드 > 100,000                                        |
| **common.grid_population**  | **`data/interim/grid_pop_500m.gpkg`**  | **그리드 ≈ 1500개, 65+ 인구 합 ≈ 통계청 서울 65+ 인구 ±5%**  |
| tb1                         | `data/processed/tb1_walking_gap.csv`   | `walk_gap_ratio`, `senior_in_walk_gap` 결측 없음             |
| tb2                         | `data/processed/tb2_emergency.csv`     | `senior_outside_60min`, `senior_outside_30min` < 65+ 총 인구 |
| tb3                         | `data/processed/tb3_care_24h.csv`      | B1, B2, B3, B4 모두 ≥ 0; B1 ≥ B4                             |
| tb4                         | `data/processed/tb4_crisis.csv`        | 폭염 risk 자치구 분포 동남권·서남권 상위 (계획 합치)         |
| tb5                         | `data/processed/tb5_loneliness.csv`    | `loneliness_load_b4` right-skewed 정상                       |
| synthesis.total_gap         | `data/processed/total_gap_index.csv`   | 5등급 분포 정규성                                            |
| synthesis.clustering        | `data/processed/time_gap_clusters.csv` | 5개 군집, 군집별 평균 프로필 차이 명확                       |
| **simulation.simulate\_\*** | **`data/processed/sim_<type>.csv`**    | **각 후보지 × 시설 유형별 `senior_relieved` 산출, 양수만**   |

### 9-5. 코드 스타일

- Python 3.11+
- type hints 적극 사용
- 모든 산출 함수에 docstring (입력·출력·단위 명시)
- 설정값은 `src/config.yaml`에 외부화 (보행속도, 골든타임, 시간대 정의, 그리드 해상도)
- 재현성: 모든 random seed = 42
- **시뮬레이션 모듈은 isochrone 캐시 적극 활용** (계산 부담 큼)

### 9-6. README.md 필수 내용

- 프로젝트 한 줄 정의
- 5개 시간축 + 1개 시뮬레이션 모듈 요약
- 실행 순서 (Stage 1-5)
- 산출물 위치
- 데이터 출처 + 라이선스
- 한계 (보행속도 가정, 운영시간 표준 가정, 격자 인구 보간 가정 등)

---

## 10. 일정 (5/13 마감 역산, v4 업데이트)

| 주차           | 일정                                                                            | 마일스톤                                                                      |
| -------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| W1 (4/15-4/20) | 공통 인프라 (격자 인구 포함) + 데이터 수집 완료                                 | admin_master, OSM 그래프 캐시, **grid_pop**, OA 데이터 다운로드               |
| W2 (4/21-4/27) | 시간축 5개 병렬 구현 (인원 가중 포함)                                           | TB1~TB5 processed CSV 산출                                                    |
| W3 (4/28-5/4)  | 합성 + **시뮬레이션** + 시각화 60%                                              | total_gap_index, 클러스터링, **TB6 4개 시뮬레이션 모듈** 완성, 메인 차트 10개 |
| W4 (5/5-5/11)  | PPT 통합 + Tableau + 정책 시나리오 (TB6 결과 결합) + 서울 데이터 허브 활용 증빙 | 발표자료 v1                                                                   |
| W5 (5/12-5/13) | 최종 리뷰 + 제출                                                                | 제출 완료                                                                     |

---

## 11. 차별화 점검 체크리스트 (v4 확장, 제출 전 자가 확인)

### v3 항목 (유지)

- [ ] 메인 시각화 중 코로플레스가 50% 이하인가?
- [ ] 등시선·시계·사다리 차트 중 최소 3개를 핵심 산출물로 포함했는가?
- [ ] 노인 보행속도 보정이 모든 시간 분석에 반영되었는가?
- [ ] "분(分)" 단위 또는 시간 단위 수치가 발표 핵심 메시지에 등장하는가?
- [ ] 위기 시각(폭염 정오, 한파 새벽, 야간 응급) 분석이 포함되었는가?
- [ ] 시설 운영시간을 고려한 분석이 1개 이상인가?
- [ ] 정책 인사이트가 "어디에 시설을"이 아니라 "언제·얼마나 빨리"로 표현되었는가?
- [ ] 서울 데이터 허브 데이터 1건 이상 활용 + 활용 화면 캡처 보유?

### v4 신규 항목

- [ ] **모든 시간 격차 지표가 "인원" 단위로도 표현되는가? (수요 가중)**
- [ ] **TB6 시뮬레이션 결과(시설 1개 추가 효과)가 정책 시나리오 3개 모두에 통합되었는가?**
- [ ] **Before/After 시뮬레이션 듀얼 맵이 핵심 산출물에 포함되었는가?**
- [ ] **시간격차 결합 클러스터링 라벨이 알파벳(A/B/C/D)이 아닌 시간 차원 결합 명칭인가?**
- [ ] **2x2 매트릭스가 메인 시각화에 사용되지 않았는가? (있다면 보조로만)**
- [ ] **7대 도메인(의료/교통/복지...) 분류가 채택되지 않았는가?**

14개 모두 충족 시 차별화 검수 통과.

---

## 부록 A. v3 → v4 변경 사항 요약 (제미니 비판 반영 결과)

| 제미니 지적                         | v4 처리           | 처리 방식                                                        |
| ----------------------------------- | ----------------- | ---------------------------------------------------------------- |
| 수요 증발                           | **채택**          | TB1, TB2에 격자 인구 보간 + `senior_in_*` 인원 가중 추가         |
| 처방적 시뮬레이션 부재              | **채택 (재해석)** | 인터랙티브 대시보드 ❌ → 정적 사전 계산 시뮬레이션 ✅ (TB6 신규) |
| 다차원성 결여 → 7대 도메인 끌어오라 | **기각**          | 7대 도메인 회귀 시 차별화 손상. 시간축 5개 유지.                 |
| K-means 4유형 클러스터링            | **부분 채택**     | 알파벳 4유형 ❌ → 시간 결합 5유형 ✅                             |
| 2x2 매트릭스 도입                   | **기각**          | 2025 우승작 핵심 시각화. 메인 사용 금지.                         |
| 입지 최적화 (대상 수상 패턴)        | **채택**          | TB6에 그리드 후보지 점수화 → TOP 10 최적 입지 도출               |
| 생활밀착형 행정모델 정합            | **채택**          | 결론 슬라이드 18에 명시                                          |
| 유니버설 디자인 정책 도구           | **채택**          | 1페이지 문제 인식 어휘로 차용                                    |
| Phase 1-4 스토리텔링                | **부분 채택**     | 5단계로 재편 (약속의 환상 → 진단 → 위기 시각 붕괴 → 종합 → 처방) |
| 인터랙티브 클릭 재계산 대시보드     | **기각**          | 시각화 부문이지 개발 부문 아님. 시간 부담. 정적으로 처리.        |

---

## 부록 B. 데이터셋 목록 통합 (체크리스트용)

### 서울 데이터 허브 (data.seoul.go.kr/bsp/wgs/) — 필수 1건 이상

- [ ] **OA-462**: 서울시 독거노인 현황(성별/동별) — TB1, TB2, TB4, TB5 공유
- [ ] **OA-21065**: 서울시 무더위쉼터 — TB4 핵심
- [ ] **OA-21066**: 서울시 한파쉼터 — TB4 핵심

### 열린데이터광장

- [ ] OA-12420: 노인여가 복지시설(동별) — TB3, TB5
- [ ] OA-13175: 자치구별 고령인구 추계 — 인구 보정
- [ ] OA-21072: 119안전센터 위치 — TB2
- [ ] OA-22229: 저상버스 도입 노선 — TB1 보조, TB6 시뮬레이션
- [ ] OA-1094: 버스 정류소 위치 — TB1 보조, TB6
- [ ] OA-13241: 서울교통공사 엘리베이터 — TB1 보조
- [ ] OA-12603: 교통사고(연령층별 사상자) — TB2 보조
- [ ] OA-12494: 의료기관(동별) — 보조

### 공공데이터포탈

- [ ] 응급의료기관 위치 + 운영정보 (응급의료포털 OpenAPI) — TB2, TB6
- [ ] 약국 현황 (건강보험심사평가원 OpenAPI) — TB3
- [ ] 기상청 폭염일수·열대야일수 (자치구별) — TB4

### 통계청 / SGIS

- [ ] 행정동 경계 shapefile — 모든 모듈 공통
- [ ] 65세+, 75세+ 동별 인구 (KOSIS) — 모든 모듈 공통
- [ ] (선택) 건물 footprint (격자 인구 보간 정확도용) — TB1, TB2 보강

### OpenStreetMap

- [ ] 보행 네트워크 그래프 — TB1, TB4, TB5, TB6
- [ ] 차량 네트워크 그래프 — TB2, TB6
