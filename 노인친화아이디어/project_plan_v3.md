# 프로젝트 v3 — "분(分)의 격차"

## 어르신의 시간은 다르게 흐른다 — 서울 노인 시간 격차 진단

> **목적 명세**: 본 문서는 (1) 클로드 코드가 분석·시각화 코드를 작성할 수 있는 기술 명세서이자, (2) 팀원 발표·협업을 위한 기획서다. 두 용도를 모두 만족하도록 구성했다.

---

## 0. 차별화 선언 (이게 가장 중요하다)

### 0-1. 우리가 **하지 않는** 것

| 흔한 접근                                            | 왜 안 하는가                                               |
| ---------------------------------------------------- | ---------------------------------------------------------- |
| 도보 N분 시설 커버리지를 메인 지표로 쓰기            | 모든 시민을 같은 보행속도로 가정. 노인 진단의 핵심을 놓침  |
| 행정동 코로플레스 맵을 메인으로 도배하기             | 공간 분포만 보여줌. 시간 차원이 빠짐                       |
| 시설 수·종류 다양성 점수화                           | 시설이 있어도 노인이 활동하는 시간에 닫혀 있으면 의미 없음 |
| "서울 평균 vs 자치구 격차" 균형발전 프레임 단독      | 익숙하고 흔한 결론으로 귀결됨                              |
| 2x2 매트릭스로 동을 4유형으로 분류 후 권역 정책 제안 | 분석 구조가 식상함                                         |

### 0-2. 우리가 **하는** 것 — 시간축으로 회전

**분석 객체 회전**: 행정동(공간 단위) → **노인 1인의 일상 시간**(시간 단위)
**핵심 질문 회전**: "어디에 무엇이 있는가" → **"노인의 분(分)으로 환산했을 때 닿는가, 언제 닿는가, 위기에 닿는가"**
**메인 시각화 회전**: 코로플레스 → **등시선·시계 차트·시간 격차 사다리**

### 0-3. 한 줄 정의

> **2040 서울도시기본계획이 약속한 "보행 30분 자족 생활권"은 표준 시민 기준이다. 노인의 시간으로 환산하면 그 약속은 60분이 되고, 위기 시각에는 영(零)이 된다. 본 프로젝트는 그 격차를 분(分) 단위로 측정한다.**

---

## 1. 핵심 문제의식

### 1-1. 2040 계획의 보이지 않는 가정

2040 서울도시기본계획은 "도보 30분 자족적 생활권"을 핵심 비전으로 제시한다(p.46). 그러나 이 30분은 **표준 시민의 보행속도(약 4 km/h, 1.1 m/s)** 를 가정한다. 같은 계획서는 시 인구의 19%(2025)가 65세 이상이며 2040년에는 32%에 이를 것이라고도 명시한다(p.27). 약속된 시간과 실제로 그 약속을 받을 시민의 시간이 일치하지 않는다.

### 1-2. 노인의 시간은 어떻게 다른가 (출처 있는 수치)

| 차원                    | 표준 시민 | 65~74세  | 75~84세  | 85세+    |
| ----------------------- | --------- | -------- | -------- | -------- |
| 보행속도 (m/s)          | 1.1 ~ 1.4 | 0.95     | 0.78     | 0.58     |
| 도보 30분 도달 거리 (m) | 약 2,000  | 약 1,710 | 약 1,400 | 약 1,040 |
| 1 km 도달 시간 (분)     | 12.5      | 17.5     | 21.4     | 28.7     |

> 출처: Bohannon (1997) "Comfortable and maximum walking speed of adults aged 20-79"; Studenski et al. (2011) JAMA. 대한노인병학회 보고서. 본 프로젝트는 한국 노인 평균값을 65~74세 0.95, 75세+ 0.78 m/s로 채택.

→ **계획의 30분 약속은 65~74세에게는 약 35분, 75세 이상에게는 약 45분, 85세 이상에게는 약 60분**.

### 1-3. 시간은 보행만의 문제가 아니다

| 시간 차원         | 표준 시민에겐 무관 | 노인에겐 결정적                                  |
| ----------------- | ------------------ | ------------------------------------------------ |
| **응급 골든타임** | 평소 의료 접근성   | 낙상 1시간, 열사병 30분, 뇌졸중 4.5시간 골든타임 |
| **시설 운영시간** | 9-18시면 충분      | 야간·새벽 응급, 주말 외로움 시간                 |
| **위기 시각**     | 평균 분석          | 폭염 정오, 한파 새벽 결정적                      |
| **외로움 시간대** | 평균 사회 접촉     | 일요일, 명절, 야간이 위험 시각                   |

### 1-4. 결과적 메시지

> **"30분 자족 생활권"은 청년의 시간이다. 노인의 시간은 이미 더 길고, 위기 시각엔 멈춘다.**

---

## 2. 핵심 메시지 3개 (발표 결론으로 이어질 메시지)

1. **약속된 30분, 실제 60분** — 청년 보행 30분권과 노인 보행 30분권의 면적 격차를 동 단위로 측정. 격차가 큰 동 = 2040 약속이 가장 늦게 도착하는 동.

2. **시설은 살아있나** — 노인이 가장 필요한 시간(야간 응급, 주말 외로움, 폭염 정오)에 보건소·복지관·쉼터의 몇 %가 작동하는지 측정. "주간 평균"이 가린 운영시간 사각.

3. **골든타임의 외곽** — 119 출동 + 응급실 도달 시간 합산이 골든타임을 초과하는 동의 65세 이상 인구. "응급의 외곽"에 서울 노인 몇 %가 살고 있나.

---

## 3. 분석 프레임 — 5개 시간축 (TimeBands)

> 데이터셋, 파생 변수, 시각화는 **모두 시간 단위(분, 시각, 시간대)** 로 정렬. 종합 지수도 z-score가 아닌 **분(分) 단위 격차**로 표현한다.

### TB1. 보행 시간 격차 (Walking Time Gap)

**측정 대상**: 청년 30분권 면적 vs 노인 30분권 면적의 동별 격차

**데이터**:
| # | 데이터 | ID | 출처 |
|---|--------|-----|------|
| 1 | 행정동 경계 shapefile | — | 통계청 SGIS |
| 2 | OSM 보행 가능 도로망 (서울) | — | OpenStreetMap |
| 3 | 65세+ 인구 (동별) | 통계청 KOSIS | — |
| 4 | 75세+ 인구 (동별) | 통계청 KOSIS | — |
| 5 | 행정동별 인구밀도 | (3에서 도출) | — |

**핵심 산출 로직**:

```python
# (1) OSM 보행 네트워크 그래프 구축
import osmnx as ox
G = ox.graph_from_place('Seoul, South Korea', network_type='walk')

# (2) 각 동의 인구가중 중심점(centroid가 아니라 인구밀도 중심)에서
#     30분 isochrone을 두 가지 속도로 그린다
SPEED_YOUNG = 1.20  # m/s = 4.32 km/h
SPEED_65_74 = 0.95  # m/s = 3.42 km/h
SPEED_75 = 0.78     # m/s = 2.81 km/h

def isochrone_polygon(G, center_node, speed_mps, time_min):
    travel_time = nx.single_source_dijkstra_path_length(
        G, center_node, cutoff=time_min*60,
        weight=lambda u,v,d: d['length']/speed_mps)
    nodes = [n for n,t in travel_time.items()]
    return convex_hull_or_alpha_shape(nodes)

# (3) 동별로 두 isochrone의 면적 차이 = "분의 격차 면적"
df_walk = []
for _, dong in gdf_admin.iterrows():
    center = nearest_node(G, dong.population_weighted_center)
    iso_young = isochrone_polygon(G, center, SPEED_YOUNG, 30)
    iso_old = isochrone_polygon(G, center, SPEED_75, 30)
    gap_area = iso_young.area - iso_old.area
    gap_ratio = 1 - iso_old.area / iso_young.area  # 0~1
    df_walk.append({
        'adm_dr_cd': dong.adm_dr_cd,
        'iso_young_km2': iso_young.area / 1e6,
        'iso_old_km2': iso_old.area / 1e6,
        'walk_gap_ratio': gap_ratio,
        'minutes_to_match_young': time_to_reach_same_area(G, center, SPEED_75, iso_young.area)
    })
```

**핵심 파생 변수**:

- `walk_gap_ratio` = 청년 30분권 대비 노인 30분권 면적 손실 비율 (0~1)
- `minutes_to_match_young` = 청년 30분권을 노인이 도달하려면 몇 분 걸리는가 (실제 분 단위)

**시각화 산출물**:

- **TB1-A**: 단일 동 줌인 — 청년 isochrone(연한 색) 위에 노인 isochrone(진한 색) 오버레이. "약속된 영역 vs 실제 도달 영역" 시각화.
- **TB1-B**: 서울 전체 코로플레스 — `minutes_to_match_young` (분 단위 수치). 색상 범례에 "30분", "45분", "60분", "75분+" 표시.
- **TB1-C**: 사다리 차트 (slope chart) — 가로축 청년/노인 두 그룹, 세로축 시간(분). 동별 격차 라인.

**구현 가능성**: ★★★★☆ (osmnx + networkx 학습 곡선 있으나 표준 라이브러리)

---

### TB2. 응급 골든타임 사각 (Emergency Golden Time)

**측정 대상**: 119 출동 → 응급실 도착 시간이 노인 4대 응급 골든타임을 초과하는 동의 65세+ 인구

**데이터**:
| # | 데이터 | 출처 |
|---|--------|------|
| 1 | 서울시 119안전센터 위치 | 열린데이터광장 OA-21072 |
| 2 | 서울시 응급의료기관 위치 | 공공데이터포탈 (보건복지부) |
| 3 | 야간 응급실 운영 정보 | 보건복지부 응급의료포털 OpenAPI |
| 4 | 자치구별 응급환자 도착 시간 | 소방청 통계 또는 서울시 통계 |
| 5 | 노인 응급질환 통계 | OA-12603 (보조), 응급의료포털 |

**노인 4대 응급 골든타임 (의학 표준)**:

- 낙상 → 1시간 (대퇴골 골절 합병증 위험)
- 뇌졸중 → 4.5시간 (혈전용해제 투여 가능 시간)
- 심근경색 → 90분 (PCI 시술 권고)
- 열사병 → 30분 (체온 강하 골든타임)

→ 가장 짧은 30분(열사병)을 보수 기준, 가장 흔한 60분(낙상)을 메인 기준으로 사용.

**핵심 산출 로직**:

```python
# (1) 모든 응급실에 대해 60분 isochrone 계산 (역방향)
#     단, 차량 속도 적용 (도시 평균 25 km/h, 출퇴근 40 km/h)
G_drive = ox.graph_from_place('Seoul', network_type='drive')

dispatch_time = 6  # 119 출동 평균 6분 (소방청 통계)
golden_time = 60   # 낙상 기준
on_scene_time = 5  # 현장 응급처치 시간

travel_budget = golden_time - dispatch_time - on_scene_time  # 49분

er_locations = pd.read_csv('emergency_rooms.csv')
er_isochrones = []
for _, er in er_locations.iterrows():
    er_node = ox.distance.nearest_nodes(G_drive, er.lon, er.lat)
    iso = isochrone_polygon(G_drive, er_node,
                            speed_mps=25*1000/3600,
                            time_min=travel_budget)
    er_isochrones.append(iso)

reachable_area = unary_union(er_isochrones)

# (2) 행정동별 65세+ 인구 중 reachable_area 밖에 거주하는 비율 추정
#     (인구밀도 균등 분포 가정)
df_em = []
for _, dong in gdf_admin.iterrows():
    out_area = dong.geometry.difference(reachable_area).area
    out_ratio = out_area / dong.geometry.area
    df_em.append({
        'adm_dr_cd': dong.adm_dr_cd,
        'er_outside_ratio': out_ratio,
        'senior_outside': out_ratio * dong.pop_65plus
    })
```

**핵심 파생 변수**:

- `er_outside_ratio` = 동 면적 중 60분 골든타임 밖 비율
- `senior_outside` = 골든타임 밖에 거주하는 65세+ 인구 추정

**시각화 산출물**:

- **TB2-A**: 응급실 60분 등시선 지도 + 사각 영역에 다른 색칠. 점선 = 90분(심근경색), 굵은선 = 60분(낙상), 진한 영역 = 30분(열사병) 사각.
- **TB2-B**: 자치구별 골든타임 밖 65세+ 인구 막대 차트.
- **TB2-C**: 시간대별 변동 — 출퇴근(차량 속도 저하) 적용 시 사각 인구 증가 비교 막대.

**구현 가능성**: ★★★★☆ (osmnx로 가능, 응급실 데이터는 응급의료포털 API 호출 필요)

---

### TB3. 24시간 돌봄 가용성 (Care Availability Hours)

**측정 대상**: 24시간을 4개 구간(주간 평일·야간·주말 주간·주말 야간)으로 나누고, 각 구간에 가용한 노인 관련 시설 비율

**데이터**:
| # | 데이터 | 출처 | 운영시간 정보 |
|---|--------|------|--------------|
| 1 | 노인여가복지시설 (동별) | OA-12420 | 부분적 (없으면 표준 가정 9-18시 평일) |
| 2 | 보건소·보건분소·보건지소 | 서울 데이터 허브 | 표준 9-18시 평일 |
| 3 | 약국 위치 + 운영시간 | 심평원 OpenAPI | 운영시간 포함 |
| 4 | 심야약국 / 일요당번약국 | 자치구별 데이터 (OA-11613 등) | 야간/주말 운영 |
| 5 | 응급실 (24시간) | TB2와 공유 | 24시간 |
| 6 | 무더위쉼터 운영시간 | OA-21065 | 일부 포함 |

**구간 정의**:

- **B1 평일 주간** (월-금 09-18시) - 모든 시설 가동 가정
- **B2 평일 야간** (월-금 18-09시) - 약국 일부 + 응급실만
- **B3 주말 주간** (토-일 09-18시) - 시설 일부 + 약국 + 당번약국
- **B4 주말 야간** (토-일 18-09시) - 응급실 + 심야약국만

**핵심 산출 로직**:

```python
# 각 시설에 4구간 가동 비트맵 부여
def availability_bitmap(facility_type, opening_hours=None):
    """[B1, B2, B3, B4] 형식의 0/1 벡터 반환"""
    if facility_type == 'er':
        return [1,1,1,1]
    if facility_type == 'gungro':  # 경로당 표준
        return [1,0,0,0]
    if facility_type == 'pharm_24h':
        return [1,1,1,1]
    if facility_type == 'pharm_normal':
        return [1,0,1,0]
    if facility_type == 'health_center':
        return [1,0,0,0]
    # 운영시간 데이터가 있으면 거기서 계산
    if opening_hours:
        return parse_opening_hours(opening_hours)

# 동별 × 구간별 가용 시설 수
care_24h = pd.DataFrame()
for band_idx, band in enumerate(['B1','B2','B3','B4']):
    facilities_active = all_facilities[
        all_facilities['avail_bitmap'].apply(lambda b: b[band_idx]==1)
    ]
    count_by_dong = facilities_active.groupby('adm_dr_cd').size()
    care_24h[band] = count_by_dong

care_24h['gap_b2'] = care_24h['B2'] / care_24h['B1']  # 야간 잔존 비율
care_24h['gap_b4'] = care_24h['B4'] / care_24h['B1']  # 최약점 시각 잔존 비율
```

**핵심 파생 변수**:

- `availability_bitmap` (시설 단위) = 4구간 가동 벡터
- `gap_b2`, `gap_b4` (동 단위) = 야간·심야 시설 잔존 비율
- `dead_hours_dong` = `gap_b4 == 0`인 동 식별

**시각화 산출물**:

- **TB3-A**: **시계 차트 (Polar bar chart)** — 24시간을 시계로 표현, 동별 시설 가용 비율을 시간대별 부채꼴 면적으로. 4개 시계를 small multiples로 비교.
- **TB3-B**: 동 × 시간대 히트맵 — 가로 24시간, 세로 행정동(노인 인구 상위 30개), 색상 = 가용 시설 수. "사막 시간대" 한눈에.
- **TB3-C**: 자치구 평균 vs 동별 분산 — 자치구는 평균 충분해 보여도 일부 동은 zero인 구간 폭로.

**구현 가능성**: ★★★☆☆ (시설 운영시간 표준 가정이 강함. 보수적으로 표시 + 한계 명시)

---

### TB4. 위기 시각 쉼터 도달 (Crisis-Hour Shelter)

**측정 대상**: 폭염 정오~오후 4시 + 한파 새벽 2시~6시에 65세+ 노인이 도보(노인 속도)로 가용한 쉼터에 도달 가능한 인구 비율

**데이터**:
| # | 데이터 | 출처 |
|---|--------|------|
| 1 | 서울시 무더위쉼터 (위치+운영시간) | OA-21065 (서울 데이터 허브) ✅ |
| 2 | 서울시 한파쉼터 | OA-21066 (서울 데이터 허브) ✅ |
| 3 | 자치구별 폭염일수·열대야일수 | 기상청 OpenAPI |
| 4 | 65세+ 독거노인 (동별) | OA-462 (서울 데이터 허브) ✅ |
| 5 | 75세+ 인구 (동별) | KOSIS |

**핵심 산출 로직**:

```python
# (1) 무더위쉼터 운영시간 파싱 — 정오 가동 여부
df_heat = pd.read_csv('OA-21065.csv')
df_heat['noon_active'] = df_heat['운영시간'].apply(is_active_at, hour=13)  # 13시 기준
heat_active = df_heat[df_heat['noon_active']]

# (2) 노인 보행속도 기반 쉼터 isochrone (15분 = 700m for 75+)
heat_iso = []
for _, sh in heat_active.iterrows():
    node = ox.distance.nearest_nodes(G_walk, sh.lon, sh.lat)
    iso = isochrone_polygon(G_walk, node, speed_mps=0.78, time_min=15)
    heat_iso.append(iso)
heat_reachable_75 = unary_union(heat_iso)

# (3) 동별 위기 도달 가능 인구
df_crisis = []
for _, dong in gdf_admin.iterrows():
    in_area = dong.geometry.intersection(heat_reachable_75).area
    in_ratio = in_area / dong.geometry.area
    senior_unreachable = (1 - in_ratio) * dong.solo_senior_pop
    df_crisis.append({
        'adm_dr_cd': dong.adm_dr_cd,
        'heat_noon_reach_75': in_ratio,
        'senior_solo_at_risk_heat': senior_unreachable,
        'heat_days': dong.sgg_heat_days
    })
df_crisis['heat_risk_score'] = (
    df_crisis['senior_solo_at_risk_heat'] * df_crisis['heat_days']
)
```

**핵심 파생 변수**:

- `heat_noon_reach_75` = 폭염 정오 75세+ 도보 15분 쉼터 도달 가능 면적 비율
- `senior_solo_at_risk_heat` = 도달 불가능한 독거노인 추정 인원
- `heat_risk_score` = 도달 불가 인원 × 폭염일수 (연간 위험 노출량)

**시각화 산출물**:

- **TB4-A**: **위기 시각 듀얼 맵** — 좌: 폭염 정오 가용 쉼터 + 75+ 노인 도보 15분 등시선. 우: 한파 새벽 같은 분석. 두 위기 시각의 사각이 겹치는 영역 강조.
- **TB4-B**: 폭염 위험 시각 정점 차트 — 가로 시각(시간), 세로 노인 사망률(역사 통계). 13-16시 정점을 시각화하여 "왜 이 시각이 결정적인가" 정당화.
- **TB4-C**: 동별 `heat_risk_score` 막대 차트 (상위 20개) — 정책 우선순위 직접 제시.

**구현 가능성**: ★★★★★ (서울 데이터 허브 필수 데이터 2건 활용 + 강력한 메시지)

---

### TB5. 외로움 시간대 사회적 접점 (Isolation Hours Touch)

**측정 대상**: 독거노인 외로움 위험 시각(주중 야간 + 일요일 + 명절)에 도보 15분(노인 속도) 내 가용 사회적 접점 수

**사회적 접점 정의**: 24시간 편의점, 종교시설(주말 가동), 공원(상시), 전통시장(주말 가동), 경로당(평일 가동만), 주민센터.

**데이터**:
| # | 데이터 | 출처 |
|---|--------|------|
| 1 | 독거노인 (동별) | OA-462 (서울 데이터 허브) ✅ |
| 2 | 서울시 전통시장 | OA-1176 |
| 3 | 자치구별 종교시설 | 공공데이터포탈 |
| 4 | 서울시 공원 (위치+면적) | OA 다수 |
| 5 | 24시간 편의점 (대안: 지번 기반 추정) | 소상공인진흥공단 상가정보 |

**핵심 산출 로직**:

```python
# 시간대별 가용 접점 분류
TOUCH_TYPES = {
    'convenience_24h': [1,1,1,1],
    'religion':        [0,0,1,1],  # 주말 가동
    'park':            [1,1,1,1],
    'market':          [1,0,1,0],
    'gungro':          [1,0,0,0],
    'jumin_center':    [1,0,0,0]
}

# 외로움 위험 시각 = B2(평일 야간) + B4(주말 야간 + 일요일)
def loneliness_score(dong):
    touches_b2_b4 = count_facilities_active_in_bands(
        dong, ['B2','B4'], walk_speed=0.78, time_min=15)
    return dong.solo_senior_pop / max(touches_b2_b4, 0.5)
    # 점수 클수록 외로움 시간 1접점당 떠맡는 독거노인 많음
```

**핵심 파생 변수**:

- `loneliness_load_b4` = 주말 야간 1개 사회적 접점이 떠맡는 독거노인 인원
- `dead_zone_solo` = 주말 야간 도보 15분 내 접점 0개인 독거노인 인원

**시각화 산출물**:

- **TB5-A**: 시간대별 가용 접점 동 평균 라인 차트 (24시간 × 7일 = 168시간 곡선). 외로움 위험 시각 정점 하이라이트.
- **TB5-B**: 동별 `loneliness_load_b4` 코로플레스 — 주말 야간 1접점당 노인 부담.
- **TB5-C**: 사각지대 동(`dead_zone_solo > 0`) 점 지도 + 독거노인 인원 라벨.

**구현 가능성**: ★★★☆☆ (편의점·종교시설 데이터 정밀도가 낮을 수 있음)

---

## 4. 합성 지표 — "분(分)의 격차" 종합

z-score 합성이 아닌 **시간 단위 합성**으로 차별화.

```python
# 행정동 단위 종합 시간 격차 지수
df_total = (df_walk
    .merge(df_em, on='adm_dr_cd')
    .merge(care_24h, on='adm_dr_cd')
    .merge(df_crisis, on='adm_dr_cd')
    .merge(df_loneliness, on='adm_dr_cd'))

# 각 축을 "분(分) 또는 인구비율"로 통일
df_total['gap_walk_min'] = df_total['minutes_to_match_young'] - 30
df_total['gap_emergency_min'] = df_total['er_outside_ratio'] * 60  # 사각 비율 × 60분 가중
df_total['gap_care_hours_pct'] = (1 - df_total['gap_b4']) * 100  # 잔존률의 역
df_total['gap_crisis_pct'] = (1 - df_total['heat_noon_reach_75']) * 100
df_total['gap_loneliness_load'] = df_total['loneliness_load_b4'].clip(upper=100)

# 종합 시간 격차 지수 (단위: "분 + %p" — 발표 시 분리 표기)
df_total['총격차_지수'] = (
    df_total['gap_walk_min'] +
    df_total['gap_emergency_min'] * 0.5 +
    df_total['gap_care_hours_pct'] * 0.3 +
    df_total['gap_crisis_pct'] * 0.4 +
    np.log1p(df_total['gap_loneliness_load']) * 5
)

# 5등급 자연 분류 (Jenks)
from jenkspy import JenksNaturalBreaks
jnb = JenksNaturalBreaks(5)
jnb.fit(df_total['총격차_지수'])
df_total['grade'] = jnb.labels_  # 0=최우수, 4=최취약
```

> **가중치 결정 근거**: 보행 격차는 일상 약속의 직접 위반(가중 1.0), 응급은 심각하나 빈도 낮음(0.5), 24시간 가용성은 누적 영향(0.3), 위기 시각은 계절성 반영(0.4), 외로움은 정성적 → 로그 압축 후 추가. 최종 발표에서 가중치 감수성 분석을 부록으로 첨부.

---

## 5. 시각화 산출물 — 시간축 메인

> **원칙**: 코로플레스는 보조. 메인은 **시간을 보여주는 차트**.

| 산출물                 | 유형                            | 도구               | 차별화 포인트       |
| ---------------------- | ------------------------------- | ------------------ | ------------------- |
| 종합 등시선 비교 지도  | 등시선 (isochrone) 오버레이     | matplotlib + osmnx | 청년·노인 동시 표현 |
| 24시간 시계 패널       | Polar bar (시계 모양)           | matplotlib         | 시간 차원 직관      |
| 위기 시각 듀얼 맵      | 등시선 + 인구밀도 hexbin        | matplotlib         | 시간+공간 결합      |
| 시간 격차 사다리 차트  | Slope chart                     | matplotlib         | "분의 격차" 직관    |
| 응급실 60분 사각 지도  | 등시선 (역방향)                 | osmnx + matplotlib | "사각" 강조 색상    |
| 동 × 시간대 히트맵     | Cell heatmap                    | matplotlib         | "사막 시간대" 발견  |
| 위기 시각 정점 차트    | 시계열 라인 + 정점 강조         | matplotlib         | 의학적 근거 시각화  |
| 168시간 외로움 곡선    | 7일 × 24시간 폴딩 라인          | matplotlib         | 주간 패턴 폭로      |
| 권역 × 격차축 매트릭스 | 카드 레이아웃 (small multiples) | matplotlib         | 권역별 약점 시간축  |
| Tableau 대시보드       | 종합 대시보드                   | Tableau            | 인터랙티브 보조     |

**중요**: 코로플레스 맵은 만들되 **"보조 시각화"** 로 명시. 메인은 등시선·시계·시간 격차.

---

## 6. PPT 슬라이드 매핑 (15슬라이드 권장)

> 분량 제한이 있다면 줄이고, 없으면 부록 슬라이드로 보강.

| #   | 슬라이드                                    | 시각 자료                    |
| --- | ------------------------------------------- | ---------------------------- |
| 1   | 표지 — "분의 격차"                          | —                            |
| 2   | 문제 인식: 2040 약속의 숨은 가정            | 보행속도 비교 표 + 거리 계산 |
| 3   | 노인 시간은 다르게 흐른다 — 4가지 시간 차원 | 인포그래픽                   |
| 4   | TB1: 청년 30분권 vs 노인 30분권 등시선      | TB1-A                        |
| 5   | TB1: 서울 전체 분의 격차 분포               | TB1-B + TB1-C                |
| 6   | TB2: 응급 골든타임 사각                     | TB2-A                        |
| 7   | TB3: 24시간 시계 — 시설은 살아있나          | TB3-A + TB3-B                |
| 8   | TB4: 위기 시각 듀얼 맵 (폭염/한파)          | TB4-A + TB4-B                |
| 9   | TB5: 외로움 시간대 사각지대                 | TB5-A + TB5-B                |
| 10  | 종합: 분의 격차 지수 분포                   | 코로플레스 + 등급 분포       |
| 11  | 종합: 권역 × 시간축 약점 매트릭스           | 5×5 매트릭스                 |
| 12  | 정책 시나리오 1: 응급 사각 해소             | 줌인 + 수치                  |
| 13  | 정책 시나리오 2: 위기 시각 쉼터 운영시간    | 줌인 + 수치                  |
| 14  | 정책 시나리오 3: 야간 돌봄 거점             | 줌인 + 수치                  |
| 15  | 결론: 2040 계획 KPI를 시간 단위로 보강 제안 | 표                           |

---

---

## 7. 정책 인사이트 시나리오 (3가지)

### 시나리오 1: 응급 골든타임 외곽 동 — 119안전센터 추가 배치

> "노원구 X동 75세+ 인구 Y명 중 N% (M명)가 119 출동 + 응급실 도착 60분 골든타임 밖에 거주. 가장 가까운 응급실까지 평균 N분 소요. → 권고: 인근 보건지소를 야간 응급 1차 처치 거점으로 운영시간 확대 또는 119안전센터 신설 후보 1순위."

### 시나리오 2: 폭염 정오 쉼터 사각 — 운영시간 확대 정책

> "동작구 Y동: 폭염일수 자치구 평균 상위 10% × 75세+ 독거노인 비율 30% × 정오 가용 쉼터 도보 15분 도달률 12%. → 권고: 인근 경로당·종교시설을 폭염 특별기간 정오~16시 한정 무더위쉼터로 임시 지정 시 도달률 12% → 67%로 개선 (시뮬레이션)."

### 시나리오 3: 외로움 시간대 사회적 접점 사각 — 야간 돌봄 거점

> "강북구 Z동: 독거노인 N명 중 주말 야간 도보 15분 내 가용 사회적 접점 0개. 가장 가까운 24시간 편의점까지 노인 보행 22분. → 권고: 주민센터 일부 공간을 주말 야간 '야간 돌봄 거점'으로 운영. 1접점 신설 시 사각 인원 N명 → 0명."

---

## 8. 데이터 가용성 + 우회 전략

| 잠재 리스크                              | 우회 전략                                                                     |
| ---------------------------------------- | ----------------------------------------------------------------------------- |
| OSM 도로망에 일부 좁은 골목 누락         | 알파 셰이프 적용 시 보수적 추정. 한계 명시.                                   |
| 시설 운영시간 데이터 산발적              | 시설 유형별 표준 운영시간 가정 + 데이터 있는 시설은 실측. 가정값 부록 명시.   |
| 응급실 데이터 야간 운영 정보             | 응급의료포털 OpenAPI 호출. 실패 시 24시간 응급실만 보수적으로 사용.           |
| 119 출동 시간 동별 변동                  | 자치구 평균 적용. 한계 명시.                                                  |
| 65세+ 동별 인구 vs 75세+ 동별 인구       | 75세+ 인구가 동별 미공개일 시 자치구 75세+ 비율을 동별 65세+에 적용하여 추정. |
| isochrone 계산 시간 (467 동 × 여러 속도) | 멀티프로세싱 + 결과 캐시. dev 단계는 중심점 100개로 prototyping.              |

---

## 9. 클로드 코드 작업 명세 (Claude Code Brief)

### 9-1. 환경 및 의존성

```bash
python -m venv .venv && source .venv/bin/activate
pip install osmnx==2.0.* networkx geopandas shapely pyproj
pip install pandas numpy scipy scikit-learn
pip install matplotlib seaborn plotly jenkspy
pip install requests xlrd openpyxl
```

### 9-2. 디렉토리 구조

```
project/
├── data/
│   ├── raw/              # 다운로드 원본
│   │   ├── seoul_data_hub/   # OA-462, OA-21065, OA-21066
│   │   ├── open_data/        # OA-12420 등
│   │   └── public_portal/    # 응급실, 약국 등
│   ├── interim/          # 행정동 매핑 후
│   ├── processed/        # 파생변수 산출 후
│   └── shapefiles/       # 행정동 shp + OSM 그래프 캐시
├── src/
│   ├── common/
│   │   ├── admin_master.py    # 행정동 마스터 + 권역 매핑
│   │   ├── osm_graph.py       # OSM 그래프 로드/캐시
│   │   ├── isochrone.py       # 등시선 계산 함수
│   │   └── normalization.py
│   ├── timebands/
│   │   ├── tb1_walking_gap.py
│   │   ├── tb2_emergency.py
│   │   ├── tb3_care_24h.py
│   │   ├── tb4_crisis_hour.py
│   │   └── tb5_loneliness.py
│   ├── synthesis/
│   │   ├── total_gap_index.py
│   │   └── kwon_yeok_matrix.py
│   └── viz/
│       ├── tb1_charts.py
│       ├── tb2_charts.py
│       ├── ...
│       └── synthesis_charts.py
├── outputs/
│   ├── figures/          # PNG/SVG 시각화 산출
│   ├── tables/           # CSV 결과 테이블
│   └── tableau/          # Tableau 데이터 소스
├── notebooks/
│   └── exploratory.ipynb
├── docs/
│   └── seoul_data_hub_evidence/  # 활용 증빙 캡처
└── README.md
```

### 9-3. 단계별 실행 명령어 (Make 또는 sh)

```bash
# Stage 1: 공통 인프라 구축
python -m src.common.admin_master         # 행정동 마스터 생성
python -m src.common.osm_graph --cache    # OSM 그래프 다운로드 + 캐시

# Stage 2: 시간축별 산출 (병렬 가능)
python -m src.timebands.tb1_walking_gap
python -m src.timebands.tb2_emergency
python -m src.timebands.tb3_care_24h
python -m src.timebands.tb4_crisis_hour
python -m src.timebands.tb5_loneliness

# Stage 3: 합성
python -m src.synthesis.total_gap_index
python -m src.synthesis.kwon_yeok_matrix

# Stage 4: 시각화
python -m src.viz.tb1_charts
python -m src.viz.tb2_charts
# ...
python -m src.viz.synthesis_charts
```

### 9-4. 검증 기준 (Acceptance Criteria)

각 시간축 모듈은 다음을 만족해야 한다:

| 모듈                | 출력 파일                            | 검증                                                              |
| ------------------- | ------------------------------------ | ----------------------------------------------------------------- |
| common.admin_master | `data/interim/admin_master.csv`      | 426개 행정동 × 권역 매핑                                          |
| common.osm_graph    | `data/shapefiles/seoul_walk.graphml` | 그래프 노드 > 100,000                                             |
| tb1                 | `data/processed/tb1_walking_gap.csv` | 모든 동에 `walk_gap_ratio`, `minutes_to_match_young` 결측 없음    |
| tb2                 | `data/processed/tb2_emergency.csv`   | `senior_outside` 합계 > 0, < 65세+ 총 인구                        |
| tb3                 | `data/processed/tb3_care_24h.csv`    | B1, B2, B3, B4 모두 ≥ 0; B1 ≥ B4                                  |
| tb4                 | `data/processed/tb4_crisis.csv`      | 폭염 risk_score 자치구 분포 동남권·서남권에 상위 집중 (계획 합치) |
| tb5                 | `data/processed/tb5_loneliness.csv`  | `loneliness_load_b4` 분포 right-skewed 정상                       |
| synthesis           | `data/processed/total_gap_index.csv` | 5등급(grade) 분포 정규성                                          |

### 9-5. 코드 스타일

- Python 3.11+
- type hints 적극 사용
- 모든 산출 함수에 docstring (입력·출력·단위 명시)
- 설정값은 `src/config.yaml`에 외부화 (보행속도, 골든타임, 시간대 정의)
- 재현성: 모든 random seed = 42

### 9-6. README.md 필수 내용

- 프로젝트 한 줄 정의
- 5개 시간축 요약
- 실행 순서 (Stage 1-4)
- 산출물 위치
- 데이터 출처 + 라이선스
- 한계 (보행속도 가정, 운영시간 표준 가정 등)

---

## 10. 일정 (5/13 마감 역산)

| 주차           | 일정                                                                 | 마일스톤                                                    |
| -------------- | -------------------------------------------------------------------- | ----------------------------------------------------------- |
| W1 (4/15-4/20) | 공통 인프라 구축, 데이터 수집 완료                                   | admin_master 완성, OSM 그래프 캐시, 모든 OA 데이터 다운로드 |
| W2 (4/21-4/27) | 시간축 5개 병렬 구현                                                 | TB1~TB5 processed CSV 산출                                  |
| W3 (4/28-5/4)  | 합성 + 시각화 80%                                                    | total_gap_index 완성, 메인 차트 10개 산출                   |
| W4 (5/5-5/11)  | PPT 통합 + Tableau + 정책 시나리오 + 서울 데이터 허브 활용 증빙 정리 | 발표자료 v1                                                 |
| W5 (5/12-5/13) | 최종 리뷰 + 제출                                                     | 제출 완료                                                   |

---

## 11. 차별화 점검 체크리스트 (제출 전 자가 확인)

- [ ] 메인 시각화 중 코로플레스가 50% 이하인가?
- [ ] 등시선·시계·사다리 차트 중 최소 3개를 핵심 산출물로 포함했는가?
- [ ] 노인 보행속도 보정이 모든 시간 분석에 반영되었는가?
- [ ] "분(分)" 단위 또는 시간 단위 수치가 발표 핵심 메시지에 등장하는가?
- [ ] 위기 시각(폭염 정오, 한파 새벽, 야간 응급) 분석이 포함되었는가?
- [ ] 시설 운영시간을 고려한 분석이 1개 이상인가?
- [ ] 정책 인사이트가 "어디에 시설을"이 아니라 "언제·얼마나 빨리"로 표현되었는가?
- [ ] 서울 데이터 허브 데이터 1건 이상 활용 + 활용 화면 캡처 보유?

8개 모두 충족 시 차별화 검수 통과.
