[Bokji] 서울시 노인 생활복지 및 녹지 접근성 분석 파이프라인 구축
작업 개요
서울시 공공데이터를 활용하여 어르신들이 도보 10~20분 내에 복지시설과 녹지에 접근할 수 있는지 분석하고,
자치구 및 행정동 단위에서 복지 사각지대를 시각화하는 분석 파이프라인을 구축했습니다.

사용 데이터
파일 설명
서울시 사회복지시설(노인여가복지시설) 목록.csv 경로당·노인복지관 목록 (시설명, 주소, 유형)
서울시 주요 공원현황(2026 상반기).xlsx 서울 주요 공원 위치·면적 데이터
고령자현황\_20260421103806.csv 행정동 단위 65세이상 인구 및 고령화율
구현 내용

1. analysis.py — 통합 분석 파이프라인 (6단계)
   instruction.md 명세 기반으로 전체 파이프라인을 구현했습니다.

Step 2 (데이터 전처리): 복지시설·공원·고령인구 CSV/xlsx 로드, euc-kr 디코딩, 결측치 처리
Step 3 (공간 접근성 분석): EPSG:5179(한국 좌표계) 기준 400m·800m 버퍼 생성 및 구별 커버리지(%) 산출
Step 4 (평가지표 산출):
Welfare Index: 65세이상 1만명당 복지시설 수
Green Index: 65세이상 1인당 공원 면적(㎡/인)
Vulnerability Score: 위 지표와 고령화율을 Min-Max 정규화 후 가중 합산 (복지 40% + 녹지 30% + 고령화율 30%)
Step 5 (시각화): Folium 인터랙티브 지도, 막대그래프, 산점도
Step 6 (리포트): 복지시설 확충 시급 자치구 TOP 5 출력 및 CSV 저장 2. visualize_welfare.py — 복지시설 접근성 단독 시각화
Folium 지도: 복지지수 단계구분도(Choropleth) + 유형별(노인복지관/경로당/경로당(소규모)) 마커 + 400m·800m 버퍼 레이어
정적 차트 4종 (welfare_analysis_chart2.png):
자치구별 복지시설 지수 막대그래프
유형별 누적 시설 수 + 65세이상 인구 오버레이
400m·800m 보행권 커버리지 비교 막대
고령화율 vs 복지지수 사분면 산점도 3. visualize_parks.py — 녹지·공원 접근성 단독 시각화
Folium 지도: 녹지지수 단계구분도 + 공원 버블 마커(면적 비례) + 400m·800m 버퍼 레이어
정적 차트 4종 (park_analysis_chart.png):
자치구별 1인당 녹지면적 막대그래프
공원 수 vs 65세이상 인구 버블 차트
400m·800m 보행권 커버리지 비교 막대
면적 상위 10개 공원 막대그래프 4. visualize_dong.py — 행정동 단위 정밀 분석
Nominatim 지오코딩 (RateLimiter + 캐시 파일 geocode_cache.json 적용): 복지시설 주소를 실제 위경도로 변환
행정동 GeoJSON (HangJeongDong_ver20230701.geojson) 활용, 구-동 이름 불일치 교정 매핑 포함
공원·복지시설을 행정동에 Spatial Join하여 동 단위 집계
인터랙티브 지도 2종:
park_dong_map.html: 행정동 단위 공원 400m 보행권 커버리지 단계구분도
welfare_dong_map.html: 행정동 단위 복지시설 지수 단계구분도
산출물 (output/)
파일 설명
seoul_welfare_map.html 복지 결핍 지수 통합 인터랙티브 지도
welfare_accessibility_map.html 복지시설 접근성 인터랙티브 지도
park_accessibility_map.html 공원·녹지 접근성 인터랙티브 지도
park_dong_map.html 행정동 단위 녹지 접근성 지도
welfare_dong_map.html 행정동 단위 복지시설 접근성 지도
welfare_analysis_chart.png 자치구별 결핍 지수 막대 + 인구 vs 복지지수 산점도
welfare_green_scatter.png 복지지수 vs 녹지지수 2D 분포 산점도
welfare_analysis_chart2.png 복지시설 접근성 4종 차트
park_analysis_chart.png 공원·녹지 접근성 4종 차트
district_welfare_analysis.csv 25개 자치구 전체 분석 결과
top5_urgent_districts.csv 복지시설 확충 시급 자치구 TOP 5
geocode_cache.json 복지시설 주소 지오코딩 캐시
주요 기술 스택
pandas, geopandas, shapely — 데이터 처리 및 공간 분석
folium — 인터랙티브 웹 지도
matplotlib, koreanize_matplotlib — 정적 시각화 (한글 폰트)
geopy (Nominatim) — 주소 지오코딩
좌표계: WGS84(EPSG:4326) 시각화 / Korea 2000(EPSG:5179) 거리 계산
