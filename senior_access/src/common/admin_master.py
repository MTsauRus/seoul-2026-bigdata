"""
admin_master.py — 집계구·행정동 마스터 테이블 생성

서울시 생활인구 데이터(LOCAL_PEOPLE)의 행정동코드와
통계청 집계구 shapefile의 ADM_CD 코드 체계가 달라 직접 JOIN 불가.
(교집합 32/424개 — 서로 다른 코드 체계)

이 모듈은 두 마스터를 독립 관리하고, 행정동 경계 shapefile이 추가되면
코드 브릿지를 완성하는 구조를 제공한다.

출력 파일
---------
interim/oa_master.gpkg   — 집계구별 geometry + centroid + ADM_CD (행정동코드)
interim/dong_pop.csv     — LP 행정동코드별 65세+ 생활인구 (24h 평균)
interim/admin_master.csv — 집계구별 65세+ 인구 (코드 브릿지 완성 후)
"""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np

from .config import (
    LOCAL_PEOPLE_CSV, OA_BOUNDARY_SHP,
    INTERIM_DIR, PROCESSED_DIR,
    CRS_WGS84, CRS_KOREA,
    LP_SENIOR_COLS, LP_TIMESLOT_COL, LP_OA_CODE_COL, LP_DONG_CODE_COL,
)

logger = logging.getLogger(__name__)

OA_MASTER_PATH   = INTERIM_DIR / "oa_master.gpkg"
DONG_POP_PATH    = INTERIM_DIR / "dong_pop.csv"
ADMIN_MASTER_PATH = INTERIM_DIR / "admin_master.csv"


# ──────────────────────────────────────────────────────────
# 1. 집계구 마스터 (geometry 기반)
# ──────────────────────────────────────────────────────────

def build_oa_master(force: bool = False) -> gpd.GeoDataFrame:
    """
    집계구 경계 shapefile에서 마스터 GeoDataFrame 생성.

    컬럼
    ----
    oa_code  : 집계구코드 (TOT_OA_CD)
    dong_code: 행정동코드 (ADM_CD, shapefile 기준)
    sgg_code : 자치구코드 (dong_code 앞 4자리)
    geometry : 집계구 폴리곤 (EPSG:5179)
    centroid_lon / centroid_lat : WGS84 centroid
    area_m2  : 집계구 면적 (m²)
    """
    if OA_MASTER_PATH.exists() and not force:
        logger.info("기존 oa_master.gpkg 로드")
        return gpd.read_file(OA_MASTER_PATH)

    if not OA_BOUNDARY_SHP.exists():
        raise FileNotFoundError(
            f"집계구 shapefile 없음: {OA_BOUNDARY_SHP}\n"
            "data/bnd_oa_11_2025_2Q/ 디렉토리를 확인하세요."
        )

    logger.info("집계구 shapefile 로드 중: %s", OA_BOUNDARY_SHP)
    gdf = gpd.read_file(OA_BOUNDARY_SHP, encoding="euc-kr")

    # 컬럼 정규화
    gdf = gdf.rename(columns={
        "TOT_OA_CD": "oa_code",
        "ADM_CD":    "dong_code",
    })
    gdf["oa_code"]   = gdf["oa_code"].astype(str).str.zfill(14)
    gdf["dong_code"] = gdf["dong_code"].astype(str).str.zfill(8)
    gdf["sgg_code"]  = gdf["dong_code"].str[:4]   # 시군구 코드 4자리

    # 면적 (이미 EPSG:5179 — meter 단위)
    gdf["area_m2"] = gdf.geometry.area

    # WGS84 centroid 좌표
    centroids_wgs = gdf.geometry.centroid.to_crs(CRS_WGS84)
    gdf["centroid_lon"] = centroids_wgs.x
    gdf["centroid_lat"] = centroids_wgs.y

    # 불필요 컬럼 제거
    drop_cols = [c for c in ["BASE_DATE"] if c in gdf.columns]
    gdf = gdf.drop(columns=drop_cols)

    # 저장
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OA_MASTER_PATH, driver="GPKG")
    logger.info("oa_master 저장: %s  (%d 집계구)", OA_MASTER_PATH, len(gdf))
    return gdf


# ──────────────────────────────────────────────────────────
# 2. LOCAL_PEOPLE 행정동별 65세+ 인구 집계
# ──────────────────────────────────────────────────────────

def build_dong_population(force: bool = False) -> pd.DataFrame:
    """
    LOCAL_PEOPLE_20260409.csv에서 행정동별 65세+ 생활인구 24시간 평균 산출.

    반환 컬럼
    ---------
    dong_code_lp : LP 행정동코드 (8자리, LP 자체 코드 체계)
    pop_65plus   : 65세+ 생활인구 24h 평균 (남65~69 + 남70이상 + 여65~69 + 여70이상)
    pop_total    : 총 생활인구 24h 평균

    주의: dong_code_lp는 shapefile의 dong_code(ADM_CD)와 코드 체계가 달라
    직접 JOIN 불가. 행정동 경계 shapefile 제공 후 브릿지 완성.
    """
    if DONG_POP_PATH.exists() and not force:
        logger.info("기존 dong_pop.csv 로드")
        return pd.read_csv(DONG_POP_PATH, dtype={"dong_code_lp": str})

    if not LOCAL_PEOPLE_CSV.exists():
        raise FileNotFoundError(f"LOCAL_PEOPLE CSV 없음: {LOCAL_PEOPLE_CSV}")

    logger.info("LOCAL_PEOPLE 로드 중 (약 30초 소요)…")
    df = pd.read_csv(LOCAL_PEOPLE_CSV, encoding="euc-kr",
                     dtype={LP_DONG_CODE_COL: str, LP_OA_CODE_COL: str})

    # 65세+ 컬럼 → 숫자 변환 ('*'는 결측 처리)
    for col in LP_SENIOR_COLS + ["총생활인구수"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["pop_65plus"] = df[LP_SENIOR_COLS].sum(axis=1)
    df["pop_total"]  = df["총생활인구수"]

    # 시간대(0~23)별로 한 번씩 집계 → 평균
    dong_hourly = (
        df.groupby([LP_TIMESLOT_COL, LP_DONG_CODE_COL])[["pop_65plus", "pop_total"]]
        .sum()
        .reset_index()
    )
    dong_avg = (
        dong_hourly.groupby(LP_DONG_CODE_COL)[["pop_65plus", "pop_total"]]
        .mean()
        .reset_index()
        .rename(columns={LP_DONG_CODE_COL: "dong_code_lp"})
    )

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    dong_avg.to_csv(DONG_POP_PATH, index=False)
    logger.info(
        "dong_pop 저장: %s  (%d 행정동, 65세+ 합 %.0f명)",
        DONG_POP_PATH, len(dong_avg), dong_avg["pop_65plus"].sum()
    )
    return dong_avg


# ──────────────────────────────────────────────────────────
# 3. 집계구별 65세+ 인구 배분 (코드 브릿지)
# ──────────────────────────────────────────────────────────

def build_admin_master(
    adm_dong_shp: Path | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """
    집계구별 65세+ 인구를 포함한 최종 마스터 CSV 생성.

    adm_dong_shp : 행정동 경계 shapefile (사용자 제공, 필수-1)
                   제공 시 LP 코드 → SHP 코드 브릿지를 공간 조인으로 완성.
                   미제공 시 자치구(sgg_code) 수준 균등 배분으로 근사.

    반환 컬럼
    ---------
    oa_code, dong_code, sgg_code,
    centroid_lon, centroid_lat, area_m2,
    pop_65plus, pop_total
    """
    if ADMIN_MASTER_PATH.exists() and not force:
        logger.info("기존 admin_master.csv 로드")
        return pd.read_csv(ADMIN_MASTER_PATH, dtype={"oa_code": str, "dong_code": str})

    gdf_oa  = build_oa_master(force=force)
    df_dong = build_dong_population(force=force)

    # ── 브릿지 완성 경로 ─────────────────────────────────
    if adm_dong_shp is not None and Path(adm_dong_shp).exists():
        logger.info("행정동 경계 shapefile로 코드 브릿지 생성: %s", adm_dong_shp)
        df_master = _bridge_via_adm_dong(gdf_oa, df_dong, Path(adm_dong_shp))
    else:
        logger.warning(
            "행정동 경계 shapefile 없음 → 자치구 수준 균등 배분으로 근사.\n"
            "  정확한 분석을 위해 data/raw/seoul_data_hub/행정동경계.shp 제공 후 재실행."
        )
        df_master = _bridge_via_sgg(gdf_oa, df_dong)

    df_master.to_csv(ADMIN_MASTER_PATH, index=False)
    logger.info(
        "admin_master 저장: %s  (%d 집계구, 65세+ 합 %.0f명)",
        ADMIN_MASTER_PATH, len(df_master), df_master["pop_65plus"].sum()
    )
    return df_master


def _bridge_via_adm_dong(
    gdf_oa: gpd.GeoDataFrame,
    df_dong: pd.DataFrame,
    adm_dong_shp: Path,
) -> pd.DataFrame:
    """
    행정동 경계 shapefile 공간 조인으로 코드 브릿지.

    1. 집계구 centroid를 WGS84로 변환
    2. 행정동 경계 안에 속하는 centroid → 행정동코드(LP 체계) 부여
    3. LP 인구를 행정동 내 집계구 수로 균등 배분
    """
    gdf_dong_bnd = gpd.read_file(adm_dong_shp).to_crs(CRS_WGS84)

    # 행정동 경계의 코드 컬럼 자동 탐지
    code_col = _detect_dong_code_col(gdf_dong_bnd)
    logger.info("행정동 경계 코드 컬럼 탐지: %s", code_col)

    # 집계구 centroid GeoDataFrame
    gdf_centroids = gpd.GeoDataFrame(
        gdf_oa[["oa_code", "dong_code", "sgg_code", "centroid_lon", "centroid_lat", "area_m2"]].copy(),
        geometry=gpd.points_from_xy(gdf_oa["centroid_lon"], gdf_oa["centroid_lat"]),
        crs=CRS_WGS84,
    )

    # 공간 조인 (centroid가 속하는 행정동 탐색)
    joined = gpd.sjoin(gdf_centroids, gdf_dong_bnd[[code_col, "geometry"]],
                       how="left", predicate="within")
    joined = joined.rename(columns={code_col: "dong_code_lp"})
    joined["dong_code_lp"] = joined["dong_code_lp"].astype(str).str.zfill(8)

    # LP 인구 JOIN
    merged = joined.merge(df_dong, on="dong_code_lp", how="left")

    # 같은 행정동 내 집계구 수로 인구 균등 배분
    oa_count = merged.groupby("dong_code_lp")["oa_code"].transform("count")
    merged["pop_65plus"] = merged["pop_65plus"] / oa_count
    merged["pop_total"]  = merged["pop_total"]  / oa_count

    return merged[["oa_code", "dong_code", "sgg_code",
                   "centroid_lon", "centroid_lat", "area_m2",
                   "pop_65plus", "pop_total"]].fillna(0)


def _bridge_via_sgg(
    gdf_oa: gpd.GeoDataFrame,
    df_dong: pd.DataFrame,
) -> pd.DataFrame:
    """
    행정동 경계 없을 때 — 자치구(sgg_code 4자리) 수준 균등 배분.

    LP 행정동코드 앞 4자리를 sgg_code로 사용하여 자치구 합산 후
    집계구 수로 균등 배분. 정확도 낮음, 브릿지 완성 전 임시.
    """
    df_dong["sgg_code_lp"] = df_dong["dong_code_lp"].str[:4]
    sgg_pop = df_dong.groupby("sgg_code_lp")[["pop_65plus", "pop_total"]].sum().reset_index()
    sgg_pop = sgg_pop.rename(columns={"sgg_code_lp": "sgg_code"})

    merged = gdf_oa[["oa_code", "dong_code", "sgg_code",
                      "centroid_lon", "centroid_lat", "area_m2"]].merge(
        sgg_pop, on="sgg_code", how="left"
    )

    oa_per_sgg = merged.groupby("sgg_code")["oa_code"].transform("count")
    merged["pop_65plus"] = merged["pop_65plus"] / oa_per_sgg
    merged["pop_total"]  = merged["pop_total"]  / oa_per_sgg

    return merged.fillna(0)


def _detect_dong_code_col(gdf: gpd.GeoDataFrame) -> str:
    """행정동 경계 shapefile에서 행정동코드 컬럼 이름 자동 탐지."""
    candidates = ["ADM_DR_CD", "행정동코드", "dong_code", "HDONG_CD",
                  "ADM_CD", "H_CD", "ADMDONG_CD"]
    for c in candidates:
        if c in gdf.columns:
            return c
    # 8자리 숫자처럼 보이는 컬럼 탐지
    for c in gdf.columns:
        if c == "geometry":
            continue
        sample = gdf[c].dropna().astype(str)
        if sample.str.match(r"^\d{8}$").all() and len(sample) > 0:
            return c
    raise ValueError(
        f"행정동코드 컬럼을 찾을 수 없습니다. 컬럼 목록: {gdf.columns.tolist()}"
    )


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    adm_shp = None
    if len(sys.argv) > 1:
        adm_shp = Path(sys.argv[1])

    oa  = build_oa_master()
    pop = build_dong_population()
    master = build_admin_master(adm_dong_shp=adm_shp)

    print(f"\n집계구 수     : {len(oa):,}")
    print(f"행정동 수 (LP): {len(pop):,}")
    print(f"65세+ 합계    : {master['pop_65plus'].sum():,.0f}명")
    print(f"admin_master  : {ADMIN_MASTER_PATH}")
