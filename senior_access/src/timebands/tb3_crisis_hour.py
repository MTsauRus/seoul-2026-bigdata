"""
tb3_crisis_hour.py — TB3 위기 시각 쉼터 도달 분석

측정 대상
---------
폭염 정오 / 한파 새벽에 75세+ 독거노인이 노인 보행속도(0.78 m/s)로
15분 내 도달 가능한 쉼터의 커버리지 계산.

핵심 질문: "쉼터가 열려 있어도 걸어서 닿을 수 없으면 의미가 없다."

산출물
------
data/processed/tb3_crisis.csv
    oa_code, dong_code, sgg_code,
    heat_reachable      : 무더위쉼터 15분 도달 가능 여부 (0/1)
    cold_reachable      : 한파쉼터 15분 도달 가능 여부 (0/1)
    solo_senior_est     : 집계구 추정 독거노인 수
    solo_not_heat       : 무더위쉼터 미도달 독거노인 추정
    solo_not_cold       : 한파쉼터 미도달 독거노인 추정
    heat_risk_score     : solo_not_heat × heat_days (폭염 노출 위험)
    dong_code_lp        : LP 행정동코드 (인구 브릿지용)
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.ops import unary_union

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.config import (
    PROCESSED_DIR, INTERIM_DIR,
    SPEED_SENIOR_MPS, RADIUS_TB3_MIN,
    FILES, CRS_WGS84, CRS_KOREA,
)
from src.common.facility_loader import load_heat_shelters, load_cold_shelters
from src.common.graph_loader import load_walk_graph, nearest_node
from src.common.isochrone import reachable_area_from_facilities

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROCESSED_DIR / "tb3_crisis.csv"

# 자치구별 폭염일수 기본값 (기상청 데이터 없을 시 서울 평균 사용)
# 출처: 기상청 2019-2023 폭염일수 자치구 평균 근사
DEFAULT_HEAT_DAYS: dict[str, float] = {
    "1101": 11.2, "1102": 10.8, "1103": 10.5, "1104": 12.1,
    "1105": 11.8, "1106": 11.3, "1107": 11.0, "1108": 9.8,
    "1109": 9.5,  "1110": 9.2,  "1111": 9.0,  "1112": 9.6,
    "1113": 10.1, "1114": 10.3, "1115": 11.5, "1116": 11.8,
    "1117": 12.0, "1118": 12.4, "1119": 13.5, "1120": 12.9,
    "1121": 13.2, "1122": 12.0, "1123": 12.8, "1124": 13.1,
    "1125": 13.4,
}
SEOUL_AVG_HEAT_DAYS = 11.3


def load_solo_seniors_by_dong() -> pd.DataFrame:
    """
    독거노인 현황 xlsx → 행정동별 독거노인 수.

    파일 구조: 4행 헤더 → 행4~ 실데이터
    동별(1)=시도, 동별(2)=자치구, 동별(3)=동명, 2024.열3=계(총합)
    """
    path = FILES["solo_seniors"]
    df_raw = pd.read_excel(path, header=None, engine="openpyxl")

    # 행 4부터 실데이터, 컬럼 4(index 3)이 전체 독거노인 합계
    df = df_raw.iloc[4:].reset_index(drop=True)
    df.columns = ["시도", "자치구", "동명", "합계", "65_79", "80이상"] + list(df_raw.columns[6:])

    # 자치구·시도 forward-fill (동 행은 NaN이므로 먼저 채워야 함)
    df["시도"]   = df["시도"].replace({"소계": None, "합계": None}).ffill()
    df["자치구"] = df["자치구"].replace({"소계": None, "합계": None}).ffill()

    # 실제 동 행만 (소계·합계 제외)
    df = df[df["동명"].notna() & ~df["동명"].astype(str).str.strip().isin(["소계", "합계", "계"])]
    df = df[df["자치구"].notna()]

    df["합계"] = pd.to_numeric(df["합계"], errors="coerce").fillna(0)

    # 동명 + 자치구 조합으로 키 생성 (행정동코드 매핑용)
    result = df[["자치구", "동명", "합계"]].copy()
    result.columns = ["sgg_name", "dong_name", "solo_senior_count"]
    logger.info("독거노인 데이터: %d 행정동", len(result))
    return result


def load_heat_days_by_sgg(heat_days_csv: Path | None = None) -> dict[str, float]:
    """
    자치구별 폭염일수 로드.
    CSV가 없으면 기본값 사용.
    """
    if heat_days_csv and heat_days_csv.exists():
        df = pd.read_csv(heat_days_csv)
        return dict(zip(df.iloc[:, 0].astype(str).str[:4], df.iloc[:, 1]))
    logger.warning("폭염일수 데이터 없음 → 서울 평균 기본값 사용 (%.1f일)", SEOUL_AVG_HEAT_DAYS)
    return DEFAULT_HEAT_DAYS


def run(force: bool = False) -> pd.DataFrame:
    """
    TB3 분석 메인 함수.

    Returns
    -------
    pd.DataFrame with columns defined in 모듈 docstring
    """
    if OUTPUT_PATH.exists() and not force:
        logger.info("기존 tb3_crisis.csv 로드")
        return pd.read_csv(OUTPUT_PATH)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 데이터 로드 ────────────────────────────────────
    logger.info("=== TB3 위기 시각 쉼터 도달 분석 시작 ===")

    df_heat_sh = load_heat_shelters()
    df_cold_sh = load_cold_shelters()
    logger.info("무더위쉼터 %d건, 한파쉼터 %d건", len(df_heat_sh), len(df_cold_sh))

    df_solo = load_solo_seniors_by_dong()

    # 집계구 마스터 (centroid 좌표 포함)
    oa_master_path = INTERIM_DIR / "oa_master.gpkg"
    if not oa_master_path.exists():
        from src.common.admin_master import build_oa_master
        gdf_oa = build_oa_master()
    else:
        gdf_oa = gpd.read_file(oa_master_path)

    dong_pop_path = INTERIM_DIR / "dong_pop.csv"
    df_dong_pop = pd.read_csv(dong_pop_path, dtype={"dong_code_lp": str})

    # ── 2. 쉼터 등시선 합집합 계산 ────────────────────────
    logger.info("무더위쉼터 등시선 합집합 계산 중 (%.0f m/s × %d분)…",
                SPEED_SENIOR_MPS, RADIUS_TB3_MIN)
    heat_reachable = reachable_area_from_facilities(
        df_heat_sh, SPEED_SENIOR_MPS, RADIUS_TB3_MIN)

    logger.info("한파쉼터 등시선 합집합 계산 중…")
    cold_reachable = reachable_area_from_facilities(
        df_cold_sh, SPEED_SENIOR_MPS, RADIUS_TB3_MIN)

    # ── 3. 집계구별 도달 가능 여부 판정 ──────────────────
    logger.info("집계구 %d개 도달 가능성 판정 중…", len(gdf_oa))
    records = []
    for _, row in gdf_oa.iterrows():
        pt = Point(row["centroid_lon"], row["centroid_lat"])
        heat_ok = int(heat_reachable.contains(pt))
        cold_ok = int(cold_reachable.contains(pt))
        records.append({
            "oa_code":       row["oa_code"],
            "dong_code":     row["dong_code"],
            "sgg_code":      row["sgg_code"],
            "centroid_lon":  row["centroid_lon"],
            "centroid_lat":  row["centroid_lat"],
            "heat_reachable": heat_ok,
            "cold_reachable": cold_ok,
        })

    df_tb3 = pd.DataFrame(records)

    # ── 4. 독거노인 인구 추정 배분 ────────────────────────
    # LP 행정동코드별 65세+ 인구를 집계구 수로 균등 배분 (근사치)
    oa_per_dong = df_tb3.groupby("dong_code")["oa_code"].count().rename("oa_count")
    df_tb3 = df_tb3.merge(oa_per_dong, on="dong_code")

    # dong_pop의 sgg_code (LP 앞 4자리)별 65세+ 합산
    df_dong_pop["sgg_lp"] = df_dong_pop["dong_code_lp"].str[:4]
    sgg_pop_lp = df_dong_pop.groupby("sgg_lp")["pop_65plus"].sum().reset_index()

    # 집계구 수도 자치구별 산출
    oa_per_sgg = df_tb3.groupby("sgg_code")["oa_code"].count().reset_index()
    oa_per_sgg.columns = ["sgg_code", "total_oa"]

    # 독거노인 동별 합계 → 자치구별 합산
    solo_by_sgg = df_solo.copy()
    # 자치구명 → 코드 매핑 (LP 기준 앞 4자리)
    # 서울 25개구 이름 → sgg_code(LP) 매핑
    SGG_NAME_TO_LP = {
        "종로구":"1111","중구":"1114","용산구":"1117","성동구":"1120","광진구":"1121",
        "동대문구":"1123","중랑구":"1126","성북구":"1129","강북구":"1130","도봉구":"1132",
        "노원구":"1135","은평구":"1138","서대문구":"1141","마포구":"1144","양천구":"1147",
        "강서구":"1150","구로구":"1153","금천구":"1154","영등포구":"1156","동작구":"1159",
        "관악구":"1162","서초구":"1165","강남구":"1168","송파구":"1171","강동구":"1174",
    }
    solo_by_sgg["sgg_lp"] = solo_by_sgg["sgg_name"].map(SGG_NAME_TO_LP)
    solo_total = solo_by_sgg.groupby("sgg_lp")["solo_senior_count"].sum().reset_index()

    # 집계구당 독거노인 = 자치구 독거노인 / 자치구 집계구 수
    # sgg_code(SHP, 앞 4자리) ↔ sgg_lp(LP, 앞 4자리) 매핑
    # 두 코드 체계가 달라 자치구 순서로 정렬하여 대응
    # SHP sgg_code: 1101~1125 (종로~강동, 25개구)
    # LP  sgg_code: 1111~1174 (종로~강동, 25개구)
    SHP_TO_LP_SGG = {
        "1101":"1111","1102":"1114","1103":"1117","1104":"1120","1105":"1121",
        "1106":"1123","1107":"1126","1108":"1129","1109":"1130","1110":"1132",
        "1111":"1135","1112":"1138","1113":"1141","1114":"1144","1115":"1147",
        "1116":"1150","1117":"1153","1118":"1154","1119":"1156","1120":"1159",
        "1121":"1162","1122":"1165","1123":"1168","1124":"1171","1125":"1174",
    }
    df_tb3["sgg_lp"] = df_tb3["sgg_code"].map(SHP_TO_LP_SGG)

    # 자치구별 독거노인 수 합계 및 집계구 수 → 집계구당 균등 배분
    df_sgg_merge = (
        df_tb3.groupby("sgg_lp")["oa_code"].count().reset_index()
        .rename(columns={"oa_code": "total_oa_in_sgg"})
        .merge(solo_total, on="sgg_lp", how="left")
    )
    df_sgg_merge["solo_per_oa"] = (
        df_sgg_merge["solo_senior_count"].fillna(0) /
        df_sgg_merge["total_oa_in_sgg"].replace(0, 1)
    )

    df_tb3 = df_tb3.merge(df_sgg_merge[["sgg_lp","solo_per_oa"]], on="sgg_lp", how="left")
    df_tb3["solo_senior_est"] = df_tb3["solo_per_oa"].fillna(0)

    # ── 5. 도달 불가 독거노인 계산 ────────────────────────
    df_tb3["solo_not_heat"] = df_tb3["solo_senior_est"] * (1 - df_tb3["heat_reachable"])
    df_tb3["solo_not_cold"] = df_tb3["solo_senior_est"] * (1 - df_tb3["cold_reachable"])

    # ── 6. 폭염 위험 점수 ─────────────────────────────────
    heat_days_map = load_heat_days_by_sgg()
    df_tb3["heat_days"] = df_tb3["sgg_lp"].map(
        lambda c: heat_days_map.get(c, SEOUL_AVG_HEAT_DAYS)
    )
    df_tb3["heat_risk_score"] = df_tb3["solo_not_heat"] * df_tb3["heat_days"]

    # ── 7. 저장 ──────────────────────────────────────────
    keep_cols = [
        "oa_code", "dong_code", "sgg_code", "sgg_lp",
        "centroid_lon", "centroid_lat",
        "heat_reachable", "cold_reachable",
        "solo_senior_est", "solo_not_heat", "solo_not_cold",
        "heat_days", "heat_risk_score",
    ]
    df_out = df_tb3[keep_cols]
    df_out.to_csv(OUTPUT_PATH, index=False)

    # ── 8. 검증 및 요약 출력 ─────────────────────────────
    _print_summary(df_out)
    logger.info("TB3 저장: %s", OUTPUT_PATH)
    return df_out


def _print_summary(df: pd.DataFrame) -> None:
    total_oa    = len(df)
    heat_covered = df["heat_reachable"].sum()
    cold_covered = df["cold_reachable"].sum()
    solo_total   = df["solo_senior_est"].sum()
    solo_heat_risk = df["solo_not_heat"].sum()
    solo_cold_risk = df["solo_not_cold"].sum()

    print("\n" + "="*55)
    print("TB3 위기 시각 쉼터 도달 분석 결과")
    print("="*55)
    print(f"  분석 집계구 수     : {total_oa:,}개")
    print(f"  무더위쉼터 커버 집계구 : {heat_covered:,}개 ({heat_covered/total_oa*100:.1f}%)")
    print(f"  한파쉼터 커버 집계구   : {cold_covered:,}개 ({cold_covered/total_oa*100:.1f}%)")
    print(f"  추정 독거노인 총계   : {solo_total:,.0f}명")
    print(f"  무더위쉼터 미도달  : {solo_heat_risk:,.0f}명 ({solo_heat_risk/solo_total*100:.1f}%)")
    print(f"  한파쉼터 미도달    : {solo_cold_risk:,.0f}명 ({solo_cold_risk/solo_total*100:.1f}%)")
    print()

    # 자치구별 폭염 위험 상위 5개
    sgg_risk = (
        df.groupby("sgg_code")
        .agg(heat_risk=("heat_risk_score","sum"),
             solo_not_heat=("solo_not_heat","sum"))
        .sort_values("heat_risk", ascending=False)
        .head(5)
    )
    print("  [폭염 위험 상위 5개 자치구]")
    for sgg, row in sgg_risk.iterrows():
        print(f"    sgg {sgg}: 위험점수 {row.heat_risk:.0f}, 미도달 독거노인 {row.solo_not_heat:.0f}명")
    print("="*55)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run(force=False)
    print(f"\n산출물: {OUTPUT_PATH}")
