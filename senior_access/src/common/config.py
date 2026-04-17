"""
config.py — 분(分)의 격차 프로젝트 전역 상수

모든 분석 파라미터는 여기서 중앙 관리.
보행속도·반경·경로 등 변경 시 이 파일만 수정.
"""

from pathlib import Path

# ──────────────────────────────────────────────
# 프로젝트 루트 경로
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # seoul-2026-bigdata/
SENIOR_ROOT  = Path(__file__).resolve().parents[2]  # senior_access/

# 기존 캐시 / 원본 데이터 위치 (루트 기준)
CACHE_DIR       = PROJECT_ROOT / "cache"
LEGACY_DATA_DIR = PROJECT_ROOT / "노인친화아이디어" / "data"

# 신규 데이터 디렉토리
RAW_DIR       = SENIOR_ROOT / "data" / "raw"
INTERIM_DIR   = SENIOR_ROOT / "data" / "interim"
PROCESSED_DIR = SENIOR_ROOT / "data" / "processed"
OUTPUT_DIR    = SENIOR_ROOT / "outputs"
FIGURES_DIR   = OUTPUT_DIR / "figures"
TABLES_DIR    = OUTPUT_DIR / "tables"

# ──────────────────────────────────────────────
# 보행속도 (m/s) — Bohannon 1997, Studenski 2011
# ──────────────────────────────────────────────
SPEED_YOUNG_MPS  = 1.20   # 표준 시민 (20~64세)
SPEED_65_74_MPS  = 0.95   # 65~74세
SPEED_75_MPS     = 0.78   # 75~84세 (메인 분석 기준)
SPEED_85_MPS     = 0.58   # 85세+

# 프로젝트 채택값: 75세+ 보수 기준
SPEED_SENIOR_MPS = SPEED_75_MPS

# ──────────────────────────────────────────────
# 분석 반경 (분)
# ──────────────────────────────────────────────
RADIUS_TB1_MIN    = 30   # TB1 보행 격차: 청년 vs 노인 30분권 비교
RADIUS_TB2_MIN    = 30   # TB2 7개 차원: 노인 30분 도달 시설 수
RADIUS_TB3_MIN    = 15   # TB3 위기 쉼터: 노인 15분 (열사병 기준)
RADIUS_TB4_MIN    = 15   # TB4 사회적 접점: 노인 15분

# ──────────────────────────────────────────────
# 집계구 인구 데이터 파일
# ──────────────────────────────────────────────
LOCAL_PEOPLE_CSV = PROJECT_ROOT / "data" / "LOCAL_PEOPLE_20260409.csv"
OA_BOUNDARY_SHP  = PROJECT_ROOT / "data" / "bnd_oa_11_2025_2Q" / "bnd_oa_11_2025_2Q.shp"

# LOCAL_PEOPLE 컬럼명 (65세+ 인구 = 65~69 + 70세이상 남+여)
LP_SENIOR_COLS = [
    "남자65세부터69세생활인구수",
    "남자70세이상생활인구수",
    "여자65세부터69세생활인구수",
    "여자70세이상생활인구수",
]
LP_ALL_COLS = [
    "남자65세부터69세생활인구수",
    "남자70세이상생활인구수",
    "여자65세부터69세생활인구수",
    "여자70세이상생활인구수",
    "총생활인구수",
]
LP_TIMESLOT_COL = "시간대구분"
LP_OA_CODE_COL  = "집계구코드"
LP_DONG_CODE_COL = "행정동코드"

# 대표 시간대 (분석용 — 일간 합산 후 평균)
# 시간대구분 0~23은 각 시간대를 의미. 전체 평균을 쓰려면 None
LP_REPR_HOUR = None  # None이면 24시간 평균

# ──────────────────────────────────────────────
# OSM 그래프 (기존 캐시 재활용)
# ──────────────────────────────────────────────
WALK_GRAPH_PKL = CACHE_DIR / "walk_graph.pkl"

# ──────────────────────────────────────────────
# 기존 시설 데이터 파일 경로 (노인친화아이디어/data/)
# ──────────────────────────────────────────────
FILES = {
    # TB2 의료·보건
    "clinics":       LEGACY_DATA_DIR / "13_2서울시 의원 인허가 정보.json",
    "health_centers":LEGACY_DATA_DIR / "13_보건소+및+보건분소_20260415213630.xlsx",
    # TB2 복지·커뮤니티 (경로당 포함)
    "welfare":       LEGACY_DATA_DIR / "5_1_노인여가+복지시설(동별)_20260415212825.xlsx",
    # TB2 생활인프라
    "markets":       LEGACY_DATA_DIR / "10_\\서울시 전통시장 현황(2025.7.31.기준).xlsx",
    # TB2 기후재난 / TB3
    "heat_shelters": LEGACY_DATA_DIR / "7_서울시 무더위쉼터.json",
    "cold_shelters": LEGACY_DATA_DIR / "8_서울시 한파쉼터.json",
    # TB3 / TB4 독거노인
    "solo_seniors":  LEGACY_DATA_DIR / "9_독거노인+현황(연령별_동별)_20260415213126.xlsx",
    # TB2 사회적 관계망 / TB4
    "parks_shp":     LEGACY_DATA_DIR / "12_2_공원좌표UPIS_SHP_ZON216.zip",
}

# 사용자가 추가로 제공해야 할 파일 (raw/ 아래에 놓아야 함)
FILES_NEEDED = {
    "adm_dong_shp":    RAW_DIR / "seoul_data_hub" / "행정동경계.shp",       # 필수-1
    "pharmacies":      RAW_DIR / "public_portal"  / "약국현황.csv",          # 필수-2
    "low_floor_bus":   RAW_DIR / "seoul_data_hub" / "저상버스정류장.json",    # 필수-3
    "subway_elevator": RAW_DIR / "seoul_data_hub" / "서울시 지하철역 엘리베이터 위치정보.json",  # 필수-4
    "community_center":RAW_DIR / "public_portal"  / "주민센터.csv",          # 필수-5
    "heat_days":       RAW_DIR / "open_data"      / "폭염일수.csv",           # 권장-1
    "religion":        RAW_DIR / "public_portal"  / "종교시설.csv",           # 권장-2
    "supermarkets":    RAW_DIR / "public_portal"  / "소상공인상가정보.csv",    # 권장-3
    "cctv":            RAW_DIR / "seoul_data_hub" / "CCTV.json",             # 선택
}

# ──────────────────────────────────────────────
# 좌표계
# ──────────────────────────────────────────────
CRS_WGS84  = "EPSG:4326"
CRS_KOREA  = "EPSG:5179"   # 국가 기본도 (meter 단위)
CRS_PROJ   = CRS_KOREA     # 면적 계산용 투영 좌표계

# ──────────────────────────────────────────────
# 이소크론 계산 설정
# ──────────────────────────────────────────────
ISOCHRONE_ALPHA   = 0.005    # alpha shape 파라미터 (클수록 느슨한 hull)
ISOCHRONE_CACHE_DIR = CACHE_DIR / "isochrones"

# ──────────────────────────────────────────────
# 시각화
# ──────────────────────────────────────────────
FONT_FAMILY = "AppleGothic"   # macOS 한글 폰트
DPI         = 150
FIG_SIZE_FULL = (16, 10)
FIG_SIZE_HALF = (8, 6)

# ──────────────────────────────────────────────
# 색상 팔레트 (메인 브랜드)
# ──────────────────────────────────────────────
COLOR_YOUNG  = "#4FC3F7"   # 청년 30분권 — 하늘색
COLOR_SENIOR = "#E53935"   # 노인 30분권 — 붉은색
COLOR_GAP    = "#FF7043"   # 격차 영역
COLOR_SAFE   = "#A5D6A7"   # 도달 가능
COLOR_DANGER = "#EF5350"   # 도달 불가

CMAP_SEVERITY = "OrRd"     # 취약도 코로플레스

# ──────────────────────────────────────────────
# 재현성
# ──────────────────────────────────────────────
RANDOM_SEED = 42
