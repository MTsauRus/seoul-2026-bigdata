"""
tb1_charts.py — TB1 보행 격차 시각화

산출물
------
outputs/figures/tb1_A_loss_ratio_map.png
    서울 전역 집계구별 보행 격차(loss_ratio) 코로플레스 지도

outputs/figures/tb1_B_slope_chart.png
    자치구별 청년·노인 30분 도달 면적 비교 슬로프 차트

outputs/figures/tb1_C_dist_by_sgg.png
    자치구별 loss_ratio 박스플롯 (격차 분포)

도출 방법
---------
1. 집계구(19,097개) centroid에서 OSM 보행 네트워크 Dijkstra(15분 cutoff)
2. 청년(1.20 m/s) vs 노인(0.78 m/s) 30분 등시선 alpha shape 면적 계산
3. loss_ratio = 1 - (노인면적 / 청년면적) → 0에 가까울수록 격차 없음, 1에 가까울수록 격차 큼
4. 샘플 2,000개 계산 후 KNN 보간으로 전체 집계구 커버
"""

import logging
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib import font_manager

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR, FIGURES_DIR,
    FONT_FAMILY, DPI, FIG_SIZE_FULL, FIG_SIZE_HALF,
    COLOR_YOUNG, COLOR_SENIOR, COLOR_GAP, CMAP_SEVERITY,
)

logger = logging.getLogger(__name__)

# ── 한글 폰트 설정 ──
def _set_korean_font():
    candidates = ["AppleGothic", "NanumGothic", "Malgun Gothic", "NanumBarunGothic"]
    for name in candidates:
        if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False

# 자치구 코드 → 이름 (SHP 기준 1101~1125)
SGG_CODE_NAME = {
    "1101":"종로구","1102":"중구","1103":"용산구","1104":"성동구","1105":"광진구",
    "1106":"동대문구","1107":"중랑구","1108":"성북구","1109":"강북구","1110":"도봉구",
    "1111":"노원구","1112":"은평구","1113":"서대문구","1114":"마포구","1115":"양천구",
    "1116":"강서구","1117":"구로구","1118":"금천구","1119":"영등포구","1120":"동작구",
    "1121":"관악구","1122":"서초구","1123":"강남구","1124":"송파구","1125":"강동구",
}


def run_all(force: bool = False) -> None:
    """TB1 시각화 전체 실행."""
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    _set_korean_font()

    df_tb1 = _load_tb1()
    gdf_oa = _load_oa()

    plot_loss_ratio_map(df_tb1, gdf_oa, force=force)
    plot_slope_chart(df_tb1, force=force)
    plot_sgg_boxplot(df_tb1, force=force)
    logger.info("TB1 시각화 완료")


# ──────────────────────────────────────────────────────────
# A. 코로플레스 지도 — loss_ratio
# ──────────────────────────────────────────────────────────

def plot_loss_ratio_map(
    df_tb1: pd.DataFrame,
    gdf_oa: gpd.GeoDataFrame,
    force: bool = False,
) -> None:
    out = FIGURES_DIR / "tb1_A_loss_ratio_map.png"
    if out.exists() and not force:
        logger.info("기존 파일 사용: %s", out)
        return

    # 조인
    gdf = gdf_oa.merge(df_tb1[["oa_code","loss_ratio"]], on="oa_code", how="left")
    gdf["loss_ratio"] = gdf["loss_ratio"].fillna(gdf["loss_ratio"].median())

    fig, ax = plt.subplots(1, 1, figsize=FIG_SIZE_FULL)
    gdf.to_crs("EPSG:4326").plot(
        column="loss_ratio",
        ax=ax,
        cmap=CMAP_SEVERITY,
        vmin=0.3, vmax=0.9,
        linewidth=0,
        legend=True,
        legend_kwds={
            "label": "보행 격차 지수 (loss ratio)",
            "orientation": "vertical",
            "shrink": 0.7,
            "pad": 0.02,
        },
    )

    # 자치구 경계 오버레이 (집계구를 구 단위로 dissolve)
    gdf_sgg = gdf.to_crs("EPSG:4326").dissolve(by="sgg_code").boundary
    gdf_sgg.plot(ax=ax, color="white", linewidth=0.6, alpha=0.7)

    ax.set_title(
        "서울시 보행 격차 지수\n"
        "노인(75세+, 0.78 m/s) 30분권 / 청년(1.20 m/s) 30분권 면적 손실 비율",
        fontsize=14, fontweight="bold", pad=12
    )
    ax.set_axis_off()

    # 주석: 평균값
    avg = df_tb1["loss_ratio"].mean()
    ax.text(0.02, 0.04,
            f"서울 평균 loss ratio: {avg:.3f}\n"
            f"→ 노인은 청년 대비 {(1-avg)*100:.1f}% 면적만 접근",
            transform=ax.transAxes, fontsize=10,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.85))

    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# B. 슬로프 차트 — 자치구별 청년 vs 노인 30분권 면적
# ──────────────────────────────────────────────────────────

def plot_slope_chart(
    df_tb1: pd.DataFrame,
    force: bool = False,
) -> None:
    out = FIGURES_DIR / "tb1_B_slope_chart.png"
    if out.exists() and not force:
        return

    df = df_tb1.copy()
    df["sgg_name"] = df["sgg_code"].map(SGG_CODE_NAME).fillna(df["sgg_code"])

    # 자치구별 평균
    sgg = df.groupby("sgg_name").agg(
        young=("iso_young_area_m2", "mean"),
        senior=("iso_senior_area_m2", "mean"),
        loss=("loss_ratio", "mean"),
    ).reset_index().sort_values("young", ascending=False)

    # m² → km²
    sgg["young_km2"]  = sgg["young"]  / 1e6
    sgg["senior_km2"] = sgg["senior"] / 1e6

    fig, ax = plt.subplots(figsize=(11, 9))

    cmap = plt.get_cmap("OrRd")
    loss_norm = plt.Normalize(sgg["loss"].min(), sgg["loss"].max())

    for _, row in sgg.iterrows():
        lw = 1.5 + (row["loss"] - sgg["loss"].min()) / (sgg["loss"].max() - sgg["loss"].min() + 1e-9) * 2
        color = cmap(loss_norm(row["loss"]))
        ax.plot([0, 1], [row["young_km2"], row["senior_km2"]],
                color=color, alpha=0.75, linewidth=lw)

    # 라벨: 겹침 방지를 위해 y값 기준 정렬 후 간격 보정
    def _place_labels(sgg_sorted, x_pos, col, ha, color_fn):
        y_vals = sgg_sorted[col].values.copy().astype(float)
        min_gap = (y_vals.max() - y_vals.min()) * 0.025
        # 아래에서 위로 순서 맞춤 (겹침 방지)
        for i in range(1, len(y_vals)):
            if y_vals[i] - y_vals[i-1] < min_gap:
                y_vals[i] = y_vals[i-1] + min_gap
        for val, (_, row) in zip(y_vals, sgg_sorted.iterrows()):
            label = row["sgg_name"] if ha == "right" else f"{row[col]:.1f} km²"
            ax.text(x_pos, val, label, ha=ha, va="center",
                    fontsize=8, color=color_fn(row["loss"]))

    sgg_left  = sgg.sort_values("young_km2")
    sgg_right = sgg.sort_values("senior_km2")
    _place_labels(sgg_left,  -0.04, "young_km2",  "right",
                  lambda l: "#444444")
    _place_labels(sgg_right,  1.04, "senior_km2", "left",
                  lambda l: cmap(loss_norm(l)))

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["청년\n(1.20 m/s, 30분)", "노인 75세+\n(0.78 m/s, 30분)"], fontsize=12)
    ax.set_ylabel("평균 도달 면적 (km²)", fontsize=11)
    ax.set_title("자치구별 청년 vs 노인 30분 도달 면적 비교\n색이 진할수록 격차(loss ratio) 큼",
                 fontsize=13, fontweight="bold")
    ax.set_xlim(-0.55, 1.65)
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.xaxis.set_tick_params(length=0)

    # 컬러바
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=loss_norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.4, pad=0.01, aspect=20)
    cbar.set_label("보행 격차 지수\n(loss ratio)", fontsize=9)

    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# C. 자치구별 loss_ratio 분포 박스플롯
# ──────────────────────────────────────────────────────────

def plot_sgg_boxplot(
    df_tb1: pd.DataFrame,
    force: bool = False,
) -> None:
    out = FIGURES_DIR / "tb1_C_sgg_boxplot.png"
    if out.exists() and not force:
        return

    df = df_tb1.copy()
    df["sgg_name"] = df["sgg_code"].map(SGG_CODE_NAME).fillna(df["sgg_code"])

    # 중앙값 기준 정렬
    order = (
        df.groupby("sgg_name")["loss_ratio"]
        .median()
        .sort_values(ascending=False)
        .index.tolist()
    )

    fig, ax = plt.subplots(figsize=(14, 6))
    data_by_sgg = [df[df["sgg_name"] == n]["loss_ratio"].dropna().values for n in order]

    bp = ax.boxplot(
        data_by_sgg,
        patch_artist=True,
        medianprops=dict(color="white", linewidth=2),
        whiskerprops=dict(color="#888888"),
        capprops=dict(color="#888888"),
        flierprops=dict(marker=".", color="#cccccc", markersize=3),
    )

    # 그라데이션 색상 (높을수록 붉게)
    cmap = plt.get_cmap("OrRd")
    medians = [np.median(d) for d in data_by_sgg]
    norm = plt.Normalize(min(medians), max(medians))
    for patch, med in zip(bp["boxes"], medians):
        patch.set_facecolor(cmap(norm(med)))

    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels(order, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("보행 격차 지수 (loss ratio)", fontsize=11)
    ax.set_title("자치구별 보행 격차 분포\n(높을수록 노인-청년 접근 격차 큼)",
                 fontsize=13, fontweight="bold")
    ax.axhline(df_tb1["loss_ratio"].median(), color="#444444",
               linestyle="--", linewidth=1, alpha=0.7, label="서울 중앙값")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 1)

    plt.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: %s", out)


# ──────────────────────────────────────────────────────────
# 데이터 로더
# ──────────────────────────────────────────────────────────

def _load_tb1() -> pd.DataFrame:
    path = PROCESSED_DIR / "tb1_walking_gap.csv"
    if not path.exists():
        raise FileNotFoundError(f"TB1 결과 없음: {path}\n먼저 tb1_walking_gap.py를 실행하세요.")
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
