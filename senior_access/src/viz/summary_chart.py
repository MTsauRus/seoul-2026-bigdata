"""
summary_chart.py — 팀 발표용 종합 요약 시각화

산출물
------
outputs/figures/summary_dashboard.png
    4-패널 대시보드
    ┌─────────────────┬──────────────────┐
    │ TB1: 보행 격차   │ TB3: 쉼터 사각지대│
    │ 코로플레스 지도   │ 지도              │
    ├─────────────────┴──────────────────┤
    │ 핵심 수치 배너 (KPI 3개)             │
    ├─────────────────┬──────────────────┤
    │ 자치구별 격차     │ 폭염 위험 자치구  │
    │ 박스플롯(간략)   │ 막대 (Top 5)     │
    └─────────────────┴──────────────────┘
"""

import logging

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from matplotlib import font_manager

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR, FIGURES_DIR,
    DPI, CMAP_SEVERITY, COLOR_DANGER,
)

logger = logging.getLogger(__name__)

SGG_CODE_NAME = {
    "1101":"종로구","1102":"중구","1103":"용산구","1104":"성동구","1105":"광진구",
    "1106":"동대문구","1107":"중랑구","1108":"성북구","1109":"강북구","1110":"도봉구",
    "1111":"노원구","1112":"은평구","1113":"서대문구","1114":"마포구","1115":"양천구",
    "1116":"강서구","1117":"구로구","1118":"금천구","1119":"영등포구","1120":"동작구",
    "1121":"관악구","1122":"서초구","1123":"강남구","1124":"송파구","1125":"강동구",
}


def _set_korean_font():
    candidates = ["AppleGothic", "NanumGothic", "Malgun Gothic", "NanumBarunGothic"]
    for name in candidates:
        if any(name.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def run(force: bool = False) -> None:
    out = FIGURES_DIR / "summary_dashboard.png"
    if out.exists() and not force:
        logger.info("기존 파일 사용: %s", out)
        return

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    _set_korean_font()

    df_tb1 = pd.read_csv(PROCESSED_DIR / "tb1_walking_gap.csv",
                          dtype={"oa_code": str, "sgg_code": str})
    df_tb3 = pd.read_csv(PROCESSED_DIR / "tb3_crisis.csv",
                          dtype={"oa_code": str, "sgg_code": str})
    df_tb1["sgg_code"] = df_tb1["sgg_code"].str.zfill(4)
    df_tb3["sgg_code"] = df_tb3["sgg_code"].str.zfill(4)
    gdf_oa = gpd.read_file(INTERIM_DIR / "oa_master.gpkg")

    # ── 레이아웃 ─────────────────────────────────────────
    fig = plt.figure(figsize=(20, 16), facecolor="#F8F9FA")
    gs = gridspec.GridSpec(
        3, 2,
        figure=fig,
        height_ratios=[5, 1.5, 4],
        hspace=0.35, wspace=0.15,
    )

    ax_map1 = fig.add_subplot(gs[0, 0])   # TB1 지도
    ax_map2 = fig.add_subplot(gs[0, 1])   # TB3 지도
    ax_kpi  = fig.add_subplot(gs[1, :])   # KPI 배너
    ax_box  = fig.add_subplot(gs[2, 0])   # 박스플롯
    ax_bar  = fig.add_subplot(gs[2, 1])   # 위험 막대

    # ── 제목 ─────────────────────────────────────────────
    fig.suptitle(
        "분(分)의 격차 — 노인이 걸어서 닿는 서울\n"
        "서울 2026 빅데이터 분석 경진대회",
        fontsize=18, fontweight="bold", y=0.98, color="#1A1A2E"
    )

    # ── Panel 1: TB1 코로플레스 ──────────────────────────
    gdf1 = gdf_oa.merge(df_tb1[["oa_code","loss_ratio"]], on="oa_code", how="left")
    gdf1["loss_ratio"] = gdf1["loss_ratio"].fillna(gdf1["loss_ratio"].median())
    gdf1_wgs = gdf1.to_crs("EPSG:4326")
    gdf1_wgs.plot(column="loss_ratio", ax=ax_map1, cmap=CMAP_SEVERITY,
                  vmin=0.35, vmax=0.85, linewidth=0)
    gdf1_wgs.dissolve(by="sgg_code").boundary.plot(
        ax=ax_map1, color="white", linewidth=0.4, alpha=0.6)
    ax_map1.set_title("① 보행 격차 지수 (loss ratio)", fontsize=12, fontweight="bold",
                      pad=6, color="#1A1A2E")
    ax_map1.set_axis_off()

    sm1 = plt.cm.ScalarMappable(cmap=CMAP_SEVERITY,
                                  norm=plt.Normalize(0.35, 0.85))
    sm1.set_array([])
    cb1 = fig.colorbar(sm1, ax=ax_map1, shrink=0.5, pad=0.02,
                        orientation="horizontal", aspect=30)
    cb1.set_label("0 = 격차 없음 → 1 = 완전 격차", fontsize=8)

    # ── Panel 2: TB3 사각지대 지도 ───────────────────────
    gdf3 = gdf_oa.merge(
        df_tb3[["oa_code","heat_reachable"]], on="oa_code", how="left"
    )
    gdf3["heat_reachable"] = gdf3["heat_reachable"].fillna(1)
    gdf3_wgs = gdf3.to_crs("EPSG:4326")
    gdf3_wgs[gdf3_wgs["heat_reachable"] == 1].plot(
        ax=ax_map2, color="#DCEDC8", linewidth=0)
    gdf3_wgs[gdf3_wgs["heat_reachable"] == 0].plot(
        ax=ax_map2, color=COLOR_DANGER, linewidth=0, alpha=0.9)
    gdf3_wgs.dissolve(by="sgg_code").boundary.plot(
        ax=ax_map2, color="white", linewidth=0.4, alpha=0.6)

    blind_cnt = (gdf3_wgs["heat_reachable"] == 0).sum()
    patches = [
        mpatches.Patch(color="#DCEDC8", label="커버됨"),
        mpatches.Patch(color=COLOR_DANGER, label=f"사각지대 ({blind_cnt:,}개)"),
    ]
    ax_map2.legend(handles=patches, loc="lower right", fontsize=8, framealpha=0.85)
    ax_map2.set_title("② 무더위쉼터 15분 도달 사각지대", fontsize=12, fontweight="bold",
                       pad=6, color="#1A1A2E")
    ax_map2.set_axis_off()

    # ── Panel 3: KPI 배너 ────────────────────────────────
    ax_kpi.set_facecolor("#1A1A2E")
    ax_kpi.set_xlim(0, 3)
    ax_kpi.set_ylim(0, 1)
    ax_kpi.set_axis_off()

    kpis = [
        ("서울 평균 보행 격차",
         f"{df_tb1['loss_ratio'].mean():.1%}",
         f"노인은 청년의 {(1-df_tb1['loss_ratio'].mean())*100:.1f}%\n면적만 30분에 접근 가능"),
        ("무더위쉼터 사각지대\n독거노인",
         f"{df_tb3['solo_not_heat'].sum():,.0f}명",
         f"서울 독거노인의 {df_tb3['solo_not_heat'].sum()/df_tb3['solo_senior_est'].sum()*100:.1f}%\n노인 보행속도 기준 15분 내 미도달"),
        ("최대 위험 자치구",
         "강동·강서구",
         "무더위쉼터 미도달 독거노인\n각각 9,852명 / 6,593명"),
    ]

    for i, (label, value, sub) in enumerate(kpis):
        x = 0.17 + i * 1.0
        ax_kpi.text(x, 0.75, label, ha="center", va="center",
                    fontsize=10, color="#94A3B8")
        ax_kpi.text(x, 0.45, value, ha="center", va="center",
                    fontsize=22, fontweight="bold", color="white")
        ax_kpi.text(x, 0.12, sub, ha="center", va="center",
                    fontsize=8.5, color="#94A3B8", linespacing=1.5)
        if i < 2:
            ax_kpi.axvline(x + 0.83, color="#334155", linewidth=1, alpha=0.7)

    # ── Panel 4: 자치구 박스플롯 (간략, Top 12) ──────────
    df_tb1_c = df_tb1.copy()
    df_tb1_c["sgg_name"] = df_tb1_c["sgg_code"].map(SGG_CODE_NAME).fillna(df_tb1_c["sgg_code"])
    top_sgg = (
        df_tb1_c.groupby("sgg_name")["loss_ratio"].median()
        .sort_values(ascending=False).head(12).index.tolist()
    )
    box_data = [
        df_tb1_c[df_tb1_c["sgg_name"] == n]["loss_ratio"].dropna().values
        for n in top_sgg
    ]
    ax_box.set_facecolor("#FAFAFA")
    bp = ax_box.boxplot(
        box_data, patch_artist=True,
        medianprops=dict(color="white", linewidth=2),
        whiskerprops=dict(color="#AAAAAA", linewidth=0.8),
        capprops=dict(color="#AAAAAA"),
        flierprops=dict(marker=".", color="#DDDDDD", markersize=2),
    )
    cmap_b = plt.get_cmap("OrRd")
    meds = [np.median(d) for d in box_data]
    norm_b = plt.Normalize(min(meds), max(meds))
    for patch, med in zip(bp["boxes"], meds):
        patch.set_facecolor(cmap_b(norm_b(med)))

    ax_box.set_xticks(range(1, len(top_sgg)+1))
    ax_box.set_xticklabels(top_sgg, rotation=40, ha="right", fontsize=9)
    ax_box.set_ylabel("보행 격차 지수", fontsize=10)
    ax_box.set_title("③ 자치구별 보행 격차 분포 (격차 큰 순 상위 12개)",
                     fontsize=11, fontweight="bold", color="#1A1A2E")
    ax_box.axhline(df_tb1["loss_ratio"].median(), color="#666666",
                   linestyle="--", linewidth=1, alpha=0.7)
    ax_box.set_ylim(0.3, 1.0)
    ax_box.spines[["top","right"]].set_visible(False)

    # ── Panel 5: 폭염 위험 Top 5 막대 ───────────────────
    df_tb3_c = df_tb3.copy()
    df_tb3_c["sgg_name"] = df_tb3_c["sgg_code"].map(SGG_CODE_NAME).fillna(df_tb3_c["sgg_code"])
    sgg_risk = (
        df_tb3_c.groupby("sgg_name")
        .agg(heat_risk=("heat_risk_score","sum"),
             solo_not_heat=("solo_not_heat","sum"))
        .sort_values("heat_risk", ascending=False)
        .head(5)
        .reset_index()
    )

    ax_bar.set_facecolor("#FAFAFA")
    colors_b = plt.get_cmap("YlOrRd")(np.linspace(0.4, 0.85, len(sgg_risk))[::-1])
    bars = ax_bar.barh(
        sgg_risk["sgg_name"][::-1],
        sgg_risk["heat_risk"][::-1],
        color=colors_b[::-1], edgecolor="white", height=0.55,
    )
    for bar, (_, row) in zip(bars, sgg_risk[::-1].iterrows()):
        ax_bar.text(
            bar.get_width() + sgg_risk["heat_risk"].max() * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{row['solo_not_heat']:,.0f}명",
            va="center", fontsize=10, fontweight="bold", color="#333333",
        )
    ax_bar.set_xlabel("폭염 위험 점수 (미도달 독거노인 × 폭염일수)", fontsize=10)
    ax_bar.set_title("④ 폭염 위험 자치구 Top 5\n(막대 끝: 미도달 독거노인 수)",
                     fontsize=11, fontweight="bold", color="#1A1A2E")
    ax_bar.set_xlim(0, sgg_risk["heat_risk"].max() * 1.3)
    ax_bar.spines[["top","right"]].set_visible(False)

    # ── 저장 ─────────────────────────────────────────────
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info("저장: %s", out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(force=True)
    print(f"저장: {FIGURES_DIR / 'summary_dashboard.png'}")
