"""
tb4_social_touch.py — 사회적 접점 도달 분석

독거노인 거주 집계구에서 노인 보행속도(0.78 m/s)로 15분 내
도달 가능한 사회적 접점 유형 수(touch_count)를 계산.

사회적 접점 유형 (최대 5종)
----------------------------
1. park        : 공원       (현재 데이터 있음)
2. market      : 전통시장   (좌표 없음 → 제공 시 자동 포함)
3. community   : 주민센터   (사용자 제공)
4. religion    : 종교시설   (사용자 제공)
5. welfare     : 경로당·복지관 (좌표 없음 → 제공 시 자동 포함)

핵심 지표
---------
touch_count       : 도달 가능 접점 유형 수 (0~5)
lonely_oa         : touch_count < 2이면 1 (사회 단절 위험)
solo_senior_est   : 집계구 추정 독거노인 수
loneliness_load   : solo_senior_est × (1 − touch_count/max_touch_count)
                    높을수록 사회적 고립 위험

산출물
------
data/processed/tb4_social_touch.csv
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR,
    SPEED_SENIOR_MPS, RADIUS_TB4_MIN,
    FILES, FILES_NEEDED, CRS_WGS84,
)
from ..common.facility_loader import (
    load_parks, load_traditional_markets,
    load_community_centers, load_religion,
    load_welfare_facilities,
)
from ..common.isochrone import reachable_area_from_facilities

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROCESSED_DIR / "tb4_social_touch.csv"

# SGG 이름 → LP 코드 (TB3과 동일)
SGG_NAME_TO_LP = {
    "종로구":"1111","중구":"1114","용산구":"1117","성동구":"1120","광진구":"1121",
    "동대문구":"1123","중랑구":"1126","성북구":"1129","강북구":"1130","도봉구":"1132",
    "노원구":"1135","은평구":"1138","서대문구":"1141","마포구":"1144","양천구":"1147",
    "강서구":"1150","구로구":"1153","금천구":"1154","영등포구":"1156","동작구":"1159",
    "관악구":"1162","서초구":"1165","강남구":"1168","송파구":"1171","강동구":"1174",
}

SHP_TO_LP_SGG = {
    "1101":"1111","1102":"1114","1103":"1117","1104":"1120","1105":"1121",
    "1106":"1123","1107":"1126","1108":"1129","1109":"1130","1110":"1132",
    "1111":"1135","1112":"1138","1113":"1141","1114":"1144","1115":"1147",
    "1116":"1150","1117":"1153","1118":"1154","1119":"1156","1120":"1159",
    "1121":"1162","1122":"1165","1123":"1168","1124":"1171","1125":"1174",
}

LONELY_THRESHOLD = 2   # touch_count < 이 값이면 사회 단절 위험


# ──────────────────────────────────────────────────────────
# 독거노인 데이터 (TB3와 공유)
# ──────────────────────────────────────────────────────────

def load_solo_seniors_by_dong() -> pd.DataFrame:
    """독거노인 현황 xlsx → 행정동별 독거노인 수."""
    from ..timebands.tb3_crisis_hour import load_solo_seniors_by_dong as _load
    return _load()


# ──────────────────────────────────────────────────────────
# 메인 분석 함수
# ──────────────────────────────────────────────────────────

def run(force: bool = False) -> pd.DataFrame:
    """
    TB4 사회적 접점 분석 실행.

    Returns
    -------
    pd.DataFrame: 집계구별 touch_count, loneliness_load 등
    """
    if OUTPUT_PATH.exists() and not force:
        logger.info("기존 tb4_social_touch.csv 로드")
        return pd.read_csv(OUTPUT_PATH)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("=== TB4 사회적 접점 도달 분석 시작 ===")

    # ── 1. 사회적 접점 데이터 로드 ───────────────────────
    touchpoints: dict[str, pd.DataFrame] = {}
    loaders = {
        "park":      load_parks,
        "market":    load_traditional_markets,
        "community": load_community_centers,
        "religion":  load_religion,
        "welfare":   load_welfare_facilities,
    }
    for ttype, loader in loaders.items():
        try:
            df = loader()
            if not df.empty:
                touchpoints[ttype] = df
                logger.info("접점 유형 '%s': %d건", ttype, len(df))
            else:
                logger.warning("접점 유형 '%s': 데이터 없음", ttype)
        except Exception as e:
            logger.warning("접점 '%s' 로드 오류: %s", ttype, e)

    if not touchpoints:
        logger.error("사용 가능한 사회적 접점 데이터 없음. TB4 중단.")
        return pd.DataFrame()

    max_types = len(touchpoints)
    logger.info("사용 가능한 접점 유형: %d종 — %s", max_types, list(touchpoints.keys()))

    # ── 2. 접점 유형별 등시선 합집합 계산 ────────────────
    reachable_areas = {}
    for ttype, df_tp in touchpoints.items():
        logger.info("'%s' 등시선 합집합 계산 중 (%d건)…", ttype, len(df_tp))
        try:
            area = reachable_area_from_facilities(
                df_tp, SPEED_SENIOR_MPS, RADIUS_TB4_MIN
            )
            reachable_areas[ttype] = area
        except Exception as e:
            logger.warning("'%s' 등시선 계산 오류: %s", ttype, e)

    if not reachable_areas:
        logger.error("등시선 계산 결과 없음. TB4 중단.")
        return pd.DataFrame()

    # ── 3. 집계구 마스터 로드 ─────────────────────────────
    oa_master_path = INTERIM_DIR / "oa_master.gpkg"
    if not oa_master_path.exists():
        from ..common.admin_master import build_oa_master
        gdf_oa = build_oa_master()
    else:
        gdf_oa = gpd.read_file(oa_master_path)

    dong_pop_path = INTERIM_DIR / "dong_pop.csv"
    df_dong_pop = pd.read_csv(dong_pop_path, dtype={"dong_code_lp": str})

    # ── 4. 집계구별 도달 가능 접점 유형 수 계산 ──────────
    logger.info("집계구 %d개 접점 도달 판정 중…", len(gdf_oa))
    records = []
    for _, row in gdf_oa.iterrows():
        pt = Point(row["centroid_lon"], row["centroid_lat"])
        touch_flags = {}
        for ttype, area in reachable_areas.items():
            try:
                touch_flags[f"reach_{ttype}"] = int(area.contains(pt))
            except Exception:
                touch_flags[f"reach_{ttype}"] = 0

        touch_count = sum(touch_flags.values())
        records.append({
            "oa_code":     row["oa_code"],
            "dong_code":   row["dong_code"],
            "sgg_code":    row["sgg_code"],
            "centroid_lon": row["centroid_lon"],
            "centroid_lat": row["centroid_lat"],
            "touch_count": touch_count,
            "max_types":   max_types,
            **touch_flags,
        })

    df_tb4 = pd.DataFrame(records)

    # ── 5. 독거노인 인구 배분 ────────────────────────────
    df_solo = load_solo_seniors_by_dong()
    df_tb4 = _assign_solo_seniors(df_tb4, df_solo, df_dong_pop)

    # ── 6. 외로움 지수 산출 ───────────────────────────────
    df_tb4["lonely_oa"] = (df_tb4["touch_count"] < LONELY_THRESHOLD).astype(int)
    df_tb4["loneliness_load"] = (
        df_tb4["solo_senior_est"] * (1 - df_tb4["touch_count"] / max(max_types, 1))
    )

    # ── 7. 저장 ──────────────────────────────────────────
    df_tb4.to_csv(OUTPUT_PATH, index=False)
    _print_summary(df_tb4)
    logger.info("TB4 저장: %s", OUTPUT_PATH)
    return df_tb4


# ──────────────────────────────────────────────────────────
# 독거노인 배분 (TB3와 유사)
# ──────────────────────────────────────────────────────────

def _assign_solo_seniors(
    df_tb4: pd.DataFrame,
    df_solo: pd.DataFrame,
    df_dong_pop: pd.DataFrame,
) -> pd.DataFrame:
    """자치구 수준 독거노인 균등 배분."""
    solo_by_sgg = df_solo.copy()
    solo_by_sgg["sgg_lp"] = solo_by_sgg["sgg_name"].map(SGG_NAME_TO_LP)
    solo_total = solo_by_sgg.groupby("sgg_lp")["solo_senior_count"].sum().reset_index()

    df_tb4["sgg_lp"] = df_tb4["sgg_code"].map(SHP_TO_LP_SGG)
    oa_count = df_tb4.groupby("sgg_lp")["oa_code"].count().reset_index()
    oa_count.columns = ["sgg_lp", "total_oa"]

    sgg_merge = solo_total.merge(oa_count, on="sgg_lp", how="left")
    sgg_merge["solo_per_oa"] = (
        sgg_merge["solo_senior_count"].fillna(0) /
        sgg_merge["total_oa"].replace(0, 1)
    )

    df_tb4 = df_tb4.merge(sgg_merge[["sgg_lp", "solo_per_oa"]], on="sgg_lp", how="left")
    df_tb4["solo_senior_est"] = df_tb4["solo_per_oa"].fillna(0)
    df_tb4 = df_tb4.drop(columns=["solo_per_oa"])
    return df_tb4


# ──────────────────────────────────────────────────────────
# 요약 출력
# ──────────────────────────────────────────────────────────

def _print_summary(df: pd.DataFrame) -> None:
    total_oa  = len(df)
    lonely    = df["lonely_oa"].sum()
    solo_tot  = df["solo_senior_est"].sum()
    solo_lonely = df.loc[df["lonely_oa"] == 1, "solo_senior_est"].sum()
    avg_touch = df["touch_count"].mean()

    print("\n" + "="*55)
    print("TB4 사회적 접점 도달 분석 결과")
    print("="*55)
    print(f"  접점 유형 수        : {df['max_types'].iloc[0]}종")
    print(f"  분석 집계구 수      : {total_oa:,}개")
    print(f"  평균 도달 접점 수   : {avg_touch:.2f}종")
    print(f"  사회 단절 위험 집계구: {lonely:,}개 ({lonely/total_oa*100:.1f}%)")
    print(f"  추정 독거노인 총계  : {solo_tot:,.0f}명")
    print(f"  단절 집계구 독거노인: {solo_lonely:,.0f}명 ({solo_lonely/max(solo_tot,1)*100:.1f}%)")

    # 접점별 커버 비율
    reach_cols = [c for c in df.columns if c.startswith("reach_")]
    if reach_cols:
        print("\n  [접점 유형별 커버 집계구 비율]")
        for col in reach_cols:
            ttype = col.replace("reach_", "")
            cnt = df[col].sum()
            print(f"    {ttype:12s}: {cnt:,}개 ({cnt/total_oa*100:.1f}%)")

    # 자치구별 고립 상위 5
    sgg_lonely = (
        df.groupby("sgg_code")
        .agg(lonely_oa=("lonely_oa","sum"),
             total_oa=("oa_code","count"),
             solo_lonely=("solo_senior_est",
                          lambda x: x[df.loc[x.index,"lonely_oa"]==1].sum()))
        .assign(lonely_rate=lambda d: d.lonely_oa/d.total_oa)
        .sort_values("lonely_rate", ascending=False)
        .head(5)
    )
    print("\n  [사회 단절 집계구 비율 상위 5개 자치구]")
    for sgg, row in sgg_lonely.iterrows():
        print(f"    sgg {sgg}: {row.lonely_oa:.0f}/{row.total_oa:.0f}개 "
              f"({row.lonely_rate*100:.1f}%) 독거노인 {row.solo_lonely:.0f}명")
    print("="*55)


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    import argparse
    parser = argparse.ArgumentParser(description="TB4 사회적 접점 분석")
    parser.add_argument("--force", action="store_true", help="결과 재계산")
    args = parser.parse_args()

    df = run(force=args.force)
    print(f"\n산출물: {OUTPUT_PATH}")
