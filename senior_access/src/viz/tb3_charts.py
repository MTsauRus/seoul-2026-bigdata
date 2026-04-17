"""
tb3_charts.py — TB3 위기 시각 쉼터 도달 시각화

산출물
------
outputs/figures/tb3_A_heat_blind_map.png
    무더위쉼터 도달 불가 집계구 지도 (폭염 사각지대)

outputs/figures/tb3_B_cold_blind_map.png
    한파쉼터 도달 불가 집계구 지도

outputs/figures/tb3_C_risk_bar.png
    폭염 위험 점수 상위 10개 자치구 막대 차트
    (solo_not_heat × 폭염일수)

도출 방법
---------
1. 무더위쉼터(4,107개) + 한파쉼터(1,642개) 각각의 노인 15분 등시선 합집합 계산
   → 셸터 도달 가능 영역 = unary_union(각 쉼터의 이소크론)
2. 집계구 centroid가 도달 가능 영역 안에 있으면 covered=1, 아니면 0
3. 독거노인 수 = 자치구별 독거노인 총수 ÷ 자치구 내 집계구 수 (균등 배분)
4. heat_risk_score = 미도달 독거노인 수 × 폭염일수 (서울 평균 11.3일)
"""

import logging

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from matplotlib import font_manager

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR, FIGURES_DIR,
    DPI, FIG_SIZE_FULL, FIG_SIZE_HALF,
    COLOR_DANGER, COLOR_SAFE,
)

logger = logging.getLogger(__name__)

SGG_CODE_NAME = {
    "1101":"종로구","1102":"중구","1103":"용산구","1104":"성동구","1105":"광진구",
    "1106":"동대문구","1107":"중랑구","1108":"성북구","1109":"강북구","1110":"도봉구",
    "1111":"노원구","1112":"은평구","1113":"서대문구","1114":"마포구","1115":"양천구",
    "1116":"강서구","1117":"구로구","1118":"금천구","1119":"영등포구","1120":"동작구",
    "1121":"관악구","1122":"서초구","1123":"강남구","1124":"송파구","1125":"강동구",
}

# SHP sgg_code → LP sgg_code (폭염 위험 자치구 식별용)
SHP_TO_LP = {
    "1101":"1111","1102":"1114","1103":"1117","1104":"1120","1105":"1121",
    "1106":"1123","1107":"1126","1108":"1129","1109":"1130","1110":"1132",
    "1111":"1135","1112":"1138","1113":"1141","1114":"1144","1115":"1147",
    "1116":"1150","1117":"1153","1118":"1154","1119":"1156","1120":"1159",
    "1121":"1162","1122":"1165","1123":"1168","1124":"1171","1125":"1174",
}
LP_TO_SHP = {v: k for k, v in SHP_TO_LP.items()}


def _set_korean_font():
    candidates = ["AppleGothic", "NanumGothic", "Malgun Gothic", "NanumBarunGothic"]
    for name in candidates:
        if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def run_all(force: bool = False) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    _set_korean_font()

    df_tb3 = _load_tb3()
    gdf_oa = _load_oa()

    plot_heat_blind_map(df_tb3, gdf_oa, force=force)
    plot_cold_blind_map(df_tb3, gdf_oa, force=force)
    plot_risk_bar(df_tb3, force=force)
    logger.info("TB3 시각화 완료")


# ──────────────────────────────────────────────────────────
# A. 무더위쉼터 사각지대 지도
# ──────────────────────────────────────────────────────────

def plot_heat_blind_map(
    df_tb3: pd.DataFrame,
    gdf_oa: gpd.GeoDataFrame,
    force: bool = False,
) -> None:
    out = FIGURES_DIR / "tb3_A_heat_blind_map.png"
    if out.exists() and not force:
        return

    gdf = gdf_oa.merge(
        df_tb3[["oa_code","heat_reachable","solo_not_heat"]],
        on="oa_code", how="left"
    )
    gdf["heat_reachable"] = gdf["heat_reachable"].fillna(1)

    fig, ax = plt.subplots(1, 1, figsize=FIG_SIZE_FULL)
    gdf_wgs = gdf.to_crs("EPSG:4326")

    # 커버 지역 (연한 배경)
    gdf_wgs[gdf_wgs["heat_reachable"] == 1].plot(
        ax=ax, color="#e8f5e9", linewidth=0, alpha=0.8
    )
    # 사각지대 (붉게)
    blind = gdf_wgs[gdf_wgs["heat_reachable"] == 0]
    blind.plot(ax=ax, color=COLOR_DANGER, linewidth=0, alpha=0.9)

    # 자치구 경계
    gdf_wgs.dissolve(by="sgg_code").boundary.plot(
        ax=ax, color="white", linewidth=0.5, alpha=0.6
    )

    # 범례
    patches = [
        mpatches.Patch(color="#e8f5e9", label="쉼터 도달 가능 (15분 이내)"),
        mpatches.Patch(color=COLOR_DANGER, label=f"쉼터 도달 불가 사각지대 ({len(blind):,}개 집계구)"),
    ]
    ax.legend(handles=patches, loc="lower right", fontsize=10,
              framealpha=0.9, edgecolor="#cccccc")

    # 주석
    solo_risk = df_tb3["solo_not_heat"].sum()
    ax.text(0.02, 0.96,
            f"무더위쉼터 미도달 독거노인: {solo_risk:,.0f}명\n"
            f"서울 독거노인 {solo_risk/df_tb3['solo_senior_est'].sum()*100:.1f}% 쉼터 사각지대",
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9))

    ax.set_title(
        "서울시 무더위쉼터 도달 사각지대\n"
        "노인 보행속도(0.78 m/s) 기준 15분 내 도달 불가 집계구",
        fontsize=14, fontweight="bold", pad=12
    )
    ax.set_axis_off()
    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# B. 한파쉼터 사각지대 지도
# ──────────────────────────────────────────────────────────

def plot_cold_blind_map(
    df_tb3: pd.DataFrame,
    gdf_oa: gpd.GeoDataFrame,
    force: bool = False,
) -> None:
    out = FIGURES_DIR / "tb3_B_cold_blind_map.png"
    if out.exists() and not force:
        return

    gdf = gdf_oa.merge(
        df_tb3[["oa_code","cold_reachable","solo_not_cold"]],
        on="oa_code", how="left"
    )
    gdf["cold_reachable"] = gdf["cold_reachable"].fillna(1)

    fig, ax = plt.subplots(1, 1, figsize=FIG_SIZE_FULL)
    gdf_wgs = gdf.to_crs("EPSG:4326")

    gdf_wgs[gdf_wgs["cold_reachable"] == 1].plot(
        ax=ax, color="#e3f2fd", linewidth=0, alpha=0.8
    )
    blind = gdf_wgs[gdf_wgs["cold_reachable"] == 0]
    blind.plot(ax=ax, color="#1565C0", linewidth=0, alpha=0.9)

    gdf_wgs.dissolve(by="sgg_code").boundary.plot(
        ax=ax, color="white", linewidth=0.5, alpha=0.6
    )

    patches = [
        mpatches.Patch(color="#e3f2fd", label="쉼터 도달 가능 (15분 이내)"),
        mpatches.Patch(color="#1565C0", label=f"쉼터 도달 불가 사각지대 ({len(blind):,}개 집계구)"),
    ]
    ax.legend(handles=patches, loc="lower right", fontsize=10,
              framealpha=0.9, edgecolor="#cccccc")

    solo_risk = df_tb3["solo_not_cold"].sum()
    ax.text(0.02, 0.96,
            f"한파쉼터 미도달 독거노인: {solo_risk:,.0f}명\n"
            f"서울 독거노인 {solo_risk/df_tb3['solo_senior_est'].sum()*100:.1f}% 쉼터 사각지대",
            transform=ax.transAxes, fontsize=10, va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9))

    ax.set_title(
        "서울시 한파쉼터 도달 사각지대\n"
        "노인 보행속도(0.78 m/s) 기준 15분 내 도달 불가 집계구",
        fontsize=14, fontweight="bold", pad=12
    )
    ax.set_axis_off()
    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# C. 폭염 위험 점수 상위 자치구 막대
# ──────────────────────────────────────────────────────────

def plot_risk_bar(
    df_tb3: pd.DataFrame,
    force: bool = False,
    top_n: int = 10,
) -> None:
    out = FIGURES_DIR / "tb3_C_risk_bar.png"
    if out.exists() and not force:
        return

    # 자치구 집계
    df = df_tb3.copy()
    df["sgg_name"] = df["sgg_code"].map(SGG_CODE_NAME).fillna(df["sgg_code"])
    sgg = df.groupby("sgg_name").agg(
        heat_risk=("heat_risk_score", "sum"),
        solo_not_heat=("solo_not_heat", "sum"),
        solo_total=("solo_senior_est", "sum"),
    ).reset_index().sort_values("heat_risk", ascending=False).head(top_n)

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = plt.get_cmap("OrRd")(
        np.linspace(0.4, 0.9, len(sgg))[::-1]
    )
    bars = ax.barh(sgg["sgg_name"][::-1], sgg["heat_risk"][::-1],
                   color=colors[::-1], edgecolor="white", linewidth=0.5)

    # 막대 끝에 숫자 표시
    for bar, (_, row) in zip(bars, sgg[::-1].iterrows()):
        ax.text(bar.get_width() + sgg["heat_risk"].max() * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{row['solo_not_heat']:,.0f}명",
                va="center", fontsize=9, color="#333333")

    ax.set_xlabel("폭염 위험 점수 (미도달 독거노인 수 × 폭염일수)", fontsize=11)
    ax.set_title(
        f"폭염 위험 상위 {top_n}개 자치구\n"
        "위험 점수 = 무더위쉼터 미도달 독거노인 × 자치구 평균 폭염일수(일)",
        fontsize=13, fontweight="bold"
    )
    ax.spines[["top","right"]].set_visible(False)
    ax.set_xlim(0, sgg["heat_risk"].max() * 1.2)

    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# 데이터 로더
# ──────────────────────────────────────────────────────────

def _load_tb3() -> pd.DataFrame:
    path = PROCESSED_DIR / "tb3_crisis.csv"
    if not path.exists():
        raise FileNotFoundError(f"TB3 결과 없음: {path}")
    df = pd.read_csv(path, dtype={"oa_code": str, "dong_code": str, "sgg_code": str})
    df["sgg_code"] = df["sgg_code"].str.zfill(4)
    return df


def _load_oa() -> gpd.GeoDataFrame:
    path = INTERIM_DIR / "oa_master.gpkg"
    if not path.exists():
        raise FileNotFoundError(f"OA master 없음: {path}")
    return gpd.read_file(path)


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_all(force=True)
    print(f"\n산출물 디렉토리: {FIGURES_DIR}")
