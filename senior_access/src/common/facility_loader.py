"""
facility_loader.py — 7개 차원 시설 데이터 통합 로더

각 시설 파일을 읽어 표준 형식(lon, lat, facility_type, dimension)으로 정규화.
모든 반환값은 WGS84(EPSG:4326) 좌표 기준.

좌표계 참고
-----------
- 무더위쉼터    : lon/lat 직접 (WGS84)
- 한파쉼터      : lot(경도)/lat(위도) (WGS84)
- 의원          : x/y (EPSG:5186 → WGS84 변환)
- 보건소(xlsx)  : 컬럼 자동 탐지
- 기타 xlsx     : 컬럼 자동 탐지
"""

import json
import logging
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import pyproj

from .config import FILES, FILES_NEEDED, CRS_WGS84

logger = logging.getLogger(__name__)

# 좌표 변환기
# 의원 인허가 x/y: EPSG:2097 (Bessel 기반 중부원점 TM — 공공데이터포털 구식 표준)
# 한파쉼터 xcrd/ycrd: EPSG:5186 (Korea 2000 Central Belt 2010)
_PROJ_2097_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:2097", "EPSG:4326", always_xy=True)
_PROJ_5186_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)

# 7개 차원 정의
DIMENSIONS = [
    "medical",      # 의료·보건
    "transport",    # 교통·이동
    "welfare",      # 복지·커뮤니티
    "infra",        # 생활 인프라
    "safety",       # 안전·치안
    "climate",      # 기후재난
    "social",       # 사회적 관계망
]


# ──────────────────────────────────────────────────────────
# 표준 출력 형식
# ──────────────────────────────────────────────────────────

def _std(records: list[dict], dimension: str, facility_type: str) -> pd.DataFrame:
    """표준 시설 DataFrame 생성 헬퍼."""
    df = pd.DataFrame(records)
    df["dimension"]     = dimension
    df["facility_type"] = facility_type
    df = df.dropna(subset=["lon", "lat"])
    df = df[(df["lon"].between(126.5, 127.5)) & (df["lat"].between(37.0, 38.0))]
    return df[["lon", "lat", "dimension", "facility_type"] +
              [c for c in df.columns if c not in ["lon","lat","dimension","facility_type"]]]


# ──────────────────────────────────────────────────────────
# 의료·보건 (medical)
# ──────────────────────────────────────────────────────────

def load_clinics() -> pd.DataFrame:
    """
    서울시 의원 인허가 정보 (JSON, EPSG:5186 좌표 → WGS84 변환).
    영업 중인 의원만 포함.
    """
    path = FILES["clinics"]
    if not path.exists():
        logger.warning("의원 데이터 없음: %s", path)
        return pd.DataFrame(columns=["lon", "lat", "dimension", "facility_type"])

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    data = raw["DATA"] if isinstance(raw, dict) else raw

    records = []
    for r in data:
        # 영업 상태 필터 (휴업·폐업 제외)
        state = r.get("dtlstatenm", "")
        if state in ("폐업", "휴업"):
            continue
        x = _to_float(r.get("x"))
        y = _to_float(r.get("y"))
        if x is None or y is None:
            continue
        lon, lat = _PROJ_2097_TO_WGS84.transform(x, y)
        records.append({"lon": lon, "lat": lat, "name": r.get("bplcnm", "")})

    logger.info("의원 로드: %d건 (영업 중)", len(records))
    return _std(records, "medical", "clinic")


def load_health_centers() -> pd.DataFrame:
    """보건소·보건분소·보건지소 (xlsx)."""
    path = FILES["health_centers"]
    if not path.exists():
        logger.warning("보건소 데이터 없음: %s", path)
        return _empty()

    df = _read_xlsx(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        logger.warning("보건소 데이터 좌표 컬럼 탐지 실패")
        return _empty()

    records = [
        {"lon": float(r[lon_col]), "lat": float(r[lat_col]),
         "name": r.get("명칭", r.get("기관명", ""))}
        for _, r in df.iterrows()
        if _to_float(r.get(lon_col)) and _to_float(r.get(lat_col))
    ]
    logger.info("보건소 로드: %d건", len(records))
    return _std(records, "medical", "health_center")


def load_pharmacies() -> pd.DataFrame:
    """약국 위치 (사용자 제공 CSV/JSON)."""
    path = FILES_NEEDED["pharmacies"]
    if not path.exists():
        logger.warning("약국 데이터 없음 (필수-2): %s", path)
        return _empty()

    df = _auto_read(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        return _empty()

    records = [{"lon": float(r[lon_col]), "lat": float(r[lat_col])}
               for _, r in df.iterrows() if _to_float(r.get(lon_col))]
    logger.info("약국 로드: %d건", len(records))
    return _std(records, "medical", "pharmacy")


# ──────────────────────────────────────────────────────────
# 교통·이동 (transport)
# ──────────────────────────────────────────────────────────

def load_low_floor_bus() -> pd.DataFrame:
    """저상버스 정류장 (OA-22229)."""
    path = FILES_NEEDED["low_floor_bus"]
    if not path.exists():
        logger.warning("저상버스 정류장 없음 (필수-3): %s", path)
        return _empty()

    data = _read_json_data(path)
    records = _extract_coords(data, lon_keys=["LON","lon","X","x"],
                              lat_keys=["LAT","lat","Y","y"])
    logger.info("저상버스 정류장: %d건", len(records))
    return _std(records, "transport", "low_floor_bus")


def load_subway_elevator() -> pd.DataFrame:
    """지하철역 엘리베이터 위치 (WKT POINT 형식 또는 lon/lat)."""
    path = FILES_NEEDED["subway_elevator"]
    if not path.exists():
        logger.warning("지하철 엘리베이터 없음 (필수-4): %s", path)
        return _empty()

    data = _read_json_data(path)
    records = []
    for r in data:
        # WKT 형식: 'POINT(127.015 37.579)'
        wkt = r.get("node_wkt") or r.get("NODE_WKT")
        if wkt and wkt.upper().startswith("POINT"):
            try:
                coords_str = wkt.strip()[6:-1]  # 'POINT(' 제거, ')' 제거
                lon_s, lat_s = coords_str.split()
                records.append({"lon": float(lon_s), "lat": float(lat_s),
                                 "name": r.get("sbwy_stn_nm", "")})
                continue
            except Exception:
                pass
        # 일반 lon/lat 키 시도
        lon = next((_to_float(r.get(k)) for k in ["lon","LON","x","X"] if r.get(k)), None)
        lat = next((_to_float(r.get(k)) for k in ["lat","LAT","y","Y"] if r.get(k)), None)
        if lon and lat:
            records.append({"lon": lon, "lat": lat})

    logger.info("지하철 엘리베이터: %d건", len(records))
    return _std(records, "transport", "subway_elevator")


# ──────────────────────────────────────────────────────────
# 복지·커뮤니티 (welfare)
# ──────────────────────────────────────────────────────────

def load_welfare_facilities() -> pd.DataFrame:
    """
    노인여가복지시설 (xlsx) — 경로당·노인복지관·노인교실 포함.
    OA-12420 기준. 좌표가 없으면 주소 기반 geocoding 필요 (추후 구현).
    """
    path = FILES["welfare"]
    if not path.exists():
        logger.warning("노인여가복지시설 없음: %s", path)
        return _empty()

    df = _read_xlsx(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        logger.warning("복지시설 좌표 컬럼 없음 — 주소 geocoding 필요 (미구현)")
        return _empty()

    records = []
    type_col = _detect_col(df, ["시설종류", "시설유형", "종류", "구분"])
    for _, r in df.iterrows():
        lon_v = _to_float(r.get(lon_col))
        lat_v = _to_float(r.get(lat_col))
        if lon_v and lat_v:
            ftype = str(r.get(type_col, "welfare")) if type_col else "welfare"
            records.append({"lon": lon_v, "lat": lat_v, "subtype": ftype})

    logger.info("복지시설 로드: %d건", len(records))
    return _std(records, "welfare", "welfare_facility")


# ──────────────────────────────────────────────────────────
# 생활 인프라 (infra)
# ──────────────────────────────────────────────────────────

def load_traditional_markets() -> pd.DataFrame:
    """전통시장 (xlsx, OA-1176)."""
    path = FILES["markets"]
    if not path.exists():
        logger.warning("전통시장 없음: %s", path)
        return _empty()

    df = _read_xlsx(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        return _empty()

    records = [{"lon": float(r[lon_col]), "lat": float(r[lat_col]),
                "name": r.get("시장명", r.get("마켓명", ""))}
               for _, r in df.iterrows() if _to_float(r.get(lon_col))]
    logger.info("전통시장 로드: %d건", len(records))
    return _std(records, "infra", "traditional_market")


def load_supermarkets() -> pd.DataFrame:
    """슈퍼마켓 (소상공인 상가정보 CSV, 사용자 제공)."""
    path = FILES_NEEDED["supermarkets"]
    if not path.exists():
        logger.warning("슈퍼마켓 데이터 없음 (권장-3): %s", path)
        return _empty()

    df = _auto_read(path)
    # 소상공인 상가정보: 업태코드 필터 (슈퍼마켓)
    if "상권업종소분류명" in df.columns:
        df = df[df["상권업종소분류명"].str.contains("슈퍼|마트|편의점", na=False)]
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        return _empty()

    records = [{"lon": float(r[lon_col]), "lat": float(r[lat_col])}
               for _, r in df.iterrows() if _to_float(r.get(lon_col))]
    logger.info("슈퍼마켓 로드: %d건", len(records))
    return _std(records, "infra", "supermarket")


# ──────────────────────────────────────────────────────────
# 안전·치안 (safety)
# ──────────────────────────────────────────────────────────

def load_community_centers() -> pd.DataFrame:
    """주민센터·행정복지센터 (사용자 제공)."""
    path = FILES_NEEDED["community_center"]
    if not path.exists():
        logger.warning("주민센터 데이터 없음 (필수-5): %s", path)
        return _empty()

    df = _auto_read(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        return _empty()

    records = [{"lon": float(r[lon_col]), "lat": float(r[lat_col])}
               for _, r in df.iterrows() if _to_float(r.get(lon_col))]
    logger.info("주민센터 로드: %d건", len(records))
    return _std(records, "safety", "community_center")


def load_cctv() -> pd.DataFrame:
    """CCTV 위치 (OA-11571, 선택)."""
    path = FILES_NEEDED["cctv"]
    if not path.exists():
        logger.info("CCTV 데이터 없음 (선택) — 건너뜀")
        return _empty()

    data = _read_json_data(path)
    records = _extract_coords(data)
    logger.info("CCTV 로드: %d건", len(records))
    return _std(records, "safety", "cctv")


# ──────────────────────────────────────────────────────────
# 기후재난 (climate)
# ──────────────────────────────────────────────────────────

def load_heat_shelters() -> pd.DataFrame:
    """무더위쉼터 (OA-21065, lon/lat 직접 WGS84)."""
    path = FILES["heat_shelters"]
    if not path.exists():
        logger.warning("무더위쉼터 없음: %s", path)
        return _empty()

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    data = raw["DATA"] if isinstance(raw, dict) else raw

    records = []
    for r in data:
        lon = _to_float(r.get("lon") or r.get("map_coord_x"))
        lat = _to_float(r.get("lat") or r.get("map_coord_y"))
        if lon and lat:
            records.append({"lon": lon, "lat": lat, "name": r.get("r_area_nm", "")})

    logger.info("무더위쉼터 로드: %d건", len(records))
    return _std(records, "climate", "heat_shelter")


def load_cold_shelters() -> pd.DataFrame:
    """한파쉼터 (OA-21066, lot=경도/lat=위도 WGS84)."""
    path = FILES["cold_shelters"]
    if not path.exists():
        logger.warning("한파쉼터 없음: %s", path)
        return _empty()

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    data = raw["DATA"] if isinstance(raw, dict) else raw

    records = []
    for r in data:
        lon = _to_float(r.get("lot") or r.get("lon") or r.get("xcrd"))
        lat = _to_float(r.get("lat"))
        if lon and lat:
            records.append({"lon": lon, "lat": lat, "name": r.get("restarea_nm", "")})

    logger.info("한파쉼터 로드: %d건", len(records))
    return _std(records, "climate", "cold_shelter")


# ──────────────────────────────────────────────────────────
# 사회적 관계망 (social)
# ──────────────────────────────────────────────────────────

def load_parks() -> pd.DataFrame:
    """
    서울시 공원 좌표 (UPIS SHP zip 또는 기타).
    압축 해제 후 shapefile 형태로 로드.
    """
    path = FILES["parks_shp"]
    if not path.exists():
        logger.warning("공원 shapefile zip 없음: %s", path)
        return _empty()

    import zipfile, tempfile, os
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(tmpdir)
            shp_files = list(Path(tmpdir).rglob("*.shp"))
            if not shp_files:
                logger.warning("공원 zip에 .shp 없음")
                return _empty()
            gdf = gpd.read_file(shp_files[0])
            # 투영 CRS로 centroid 계산 후 WGS84로 재변환
            gdf_proj = gdf.to_crs("EPSG:5179")
            centroids_proj = gdf_proj.geometry.centroid
            gdf_cent = gpd.GeoDataFrame(geometry=centroids_proj, crs="EPSG:5179").to_crs(CRS_WGS84)
            records = [{"lon": pt.x, "lat": pt.y} for pt in gdf_cent.geometry if pt.x and pt.y]
    except Exception as e:
        logger.warning("공원 SHP 로드 실패: %s", e)
        return _empty()

    logger.info("공원 로드: %d건", len(records))
    return _std(records, "social", "park")


def load_religion() -> pd.DataFrame:
    """종교시설 (사용자 제공, 권장-2)."""
    path = FILES_NEEDED["religion"]
    if not path.exists():
        logger.info("종교시설 없음 (권장-2) — 건너뜀")
        return _empty()

    df = _auto_read(path)
    lon_col, lat_col = _detect_coord_cols(df)
    if lon_col is None:
        return _empty()

    records = [{"lon": float(r[lon_col]), "lat": float(r[lat_col])}
               for _, r in df.iterrows() if _to_float(r.get(lon_col))]
    logger.info("종교시설 로드: %d건", len(records))
    return _std(records, "social", "religion")


# ──────────────────────────────────────────────────────────
# 전체 로드 함수
# ──────────────────────────────────────────────────────────

def load_all_facilities() -> pd.DataFrame:
    """
    7개 차원 전체 시설 데이터를 하나의 DataFrame으로 반환.

    반환 컬럼: lon, lat, dimension, facility_type, (name, subtype 등 선택)
    """
    loaders = [
        load_clinics,
        load_health_centers,
        load_pharmacies,
        load_low_floor_bus,
        load_subway_elevator,
        load_welfare_facilities,
        load_traditional_markets,
        load_supermarkets,
        load_community_centers,
        load_cctv,
        load_heat_shelters,
        load_cold_shelters,
        load_parks,
        load_religion,
    ]

    dfs = []
    for loader in loaders:
        try:
            df = loader()
            if not df.empty:
                dfs.append(df)
        except Exception as e:
            logger.warning("%s 실패: %s", loader.__name__, e)

    if not dfs:
        logger.error("로드된 시설 데이터 없음")
        return _empty()

    combined = pd.concat(dfs, ignore_index=True)
    logger.info(
        "전체 시설 로드 완료: %d건 / 차원: %s",
        len(combined),
        combined.groupby("dimension").size().to_dict(),
    )
    return combined


def load_dimension(dimension: str) -> pd.DataFrame:
    """특정 차원만 로드."""
    dim_loaders = {
        "medical":   [load_clinics, load_health_centers, load_pharmacies],
        "transport": [load_low_floor_bus, load_subway_elevator],
        "welfare":   [load_welfare_facilities],
        "infra":     [load_traditional_markets, load_supermarkets],
        "safety":    [load_community_centers, load_cctv],
        "climate":   [load_heat_shelters, load_cold_shelters],
        "social":    [load_parks, load_religion],
    }
    loaders = dim_loaders.get(dimension, [])
    dfs = [loader() for loader in loaders]
    dfs = [d for d in dfs if not d.empty]
    return pd.concat(dfs, ignore_index=True) if dfs else _empty()


# ──────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────

def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["lon", "lat", "dimension", "facility_type"])


def _to_float(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def _read_xlsx(path: Path) -> pd.DataFrame:
    try:
        return pd.read_excel(path, engine="openpyxl")
    except ImportError:
        try:
            return pd.read_excel(path, engine="xlrd")
        except Exception as e:
            logger.warning("xlsx 읽기 실패 (%s): %s", path.name, e)
            return pd.DataFrame()
    except Exception as e:
        logger.warning("xlsx 읽기 실패 (%s): %s", path.name, e)
        return pd.DataFrame()


def _auto_read(path: Path) -> pd.DataFrame:
    """확장자에 따라 자동으로 파일 읽기."""
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return _read_xlsx(path)
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        data = raw["DATA"] if isinstance(raw, dict) and "DATA" in raw else raw
        return pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame()
    if ext in (".csv",):
        for enc in ["utf-8", "utf-8-sig", "euc-kr", "cp949"]:
            try:
                return pd.read_csv(path, encoding=enc, low_memory=False)
            except UnicodeDecodeError:
                continue
    return pd.DataFrame()


def _read_json_data(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ["DATA", "data", "result", "items", "features"]:
            if k in raw:
                return raw[k]
    return []


def _detect_coord_cols(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """DataFrame에서 경도·위도 컬럼을 자동 탐지."""
    lon_candidates = ["경도", "lon", "LON", "x_coord", "X_COORD", "longitude",
                      "LONGITUDE", "X", "lng", "LNG", "위경도X", "좌표X"]
    lat_candidates = ["위도", "lat", "LAT", "y_coord", "Y_COORD", "latitude",
                      "LATITUDE", "Y", "위경도Y", "좌표Y"]

    lon_col = next((c for c in lon_candidates if c in df.columns), None)
    lat_col = next((c for c in lat_candidates if c in df.columns), None)
    return lon_col, lat_col


def _detect_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    return next((c for c in candidates if c in df.columns), None)


def _extract_coords(
    data: list[dict],
    lon_keys: list[str] = ("LON","lon","x","X","longitude","경도","lot"),
    lat_keys: list[str] = ("LAT","lat","y","Y","latitude","위도"),
) -> list[dict]:
    """JSON 레코드 목록에서 좌표 추출."""
    records = []
    for r in data:
        lon = next((_to_float(r.get(k)) for k in lon_keys if r.get(k)), None)
        lat = next((_to_float(r.get(k)) for k in lat_keys if r.get(k)), None)
        if lon and lat:
            records.append({"lon": lon, "lat": lat})
    return records


# ──────────────────────────────────────────────────────────
# CLI 현황 점검
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("\n=== 시설 데이터 현황 ===")
    loaders_meta = [
        ("의원",         load_clinics),
        ("보건소",       load_health_centers),
        ("약국",         load_pharmacies),
        ("저상버스",     load_low_floor_bus),
        ("지하철엘리베", load_subway_elevator),
        ("복지시설",     load_welfare_facilities),
        ("전통시장",     load_traditional_markets),
        ("슈퍼마켓",     load_supermarkets),
        ("주민센터",     load_community_centers),
        ("CCTV",         load_cctv),
        ("무더위쉼터",   load_heat_shelters),
        ("한파쉼터",     load_cold_shelters),
        ("공원",         load_parks),
        ("종교시설",     load_religion),
    ]

    for name, loader in loaders_meta:
        df = loader()
        status = f"{len(df):>5d}건" if not df.empty else "  없음"
        print(f"  {name:12s}: {status}")
