"""
tb1_walking_gap.py — 보행 시간 격차 분석

집계구 중심점마다 청년(1.20 m/s) vs 노인(0.78 m/s)의
30분 등시선 면적을 계산해 격차(loss_ratio)를 구한다.

산출물
------
processed/tb1_walking_gap.csv
    컬럼: oa_code, dong_code, sgg_code,
          centroid_lon, centroid_lat, pop_65plus,
          iso_young_area_m2, iso_senior_area_m2,
          loss_ratio, gap_area_m2

실행 시간 예측
--------------
집계구 19,097개 × 2회 Dijkstra ≈ 수 시간.
sample_n 옵션으로 대표 샘플만 계산 후 IDW/최근접 보간.
기본 sample_n = 2000 (약 30~60분 소요, 캐시 이후엔 즉시).
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR,
    SPEED_YOUNG_MPS, SPEED_SENIOR_MPS,
    RADIUS_TB1_MIN, CRS_WGS84, CRS_KOREA, RANDOM_SEED,
)
from ..common.admin_master import build_oa_master, build_admin_master
from ..common.graph_loader import load_walk_graph, nearest_node
from ..common.isochrone import area_loss_ratio

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROCESSED_DIR / "tb1_walking_gap.csv"


# ──────────────────────────────────────────────────────────
# 메인 분석 함수
# ──────────────────────────────────────────────────────────

def run_tb1(
    sample_n: int = 2000,
    force: bool = False,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    TB1 보행 격차 분석 실행.

    Parameters
    ----------
    sample_n  : 계산할 대표 집계구 수 (전체 19,097 중). 0이면 전체.
    force     : 기존 결과 파일 무시하고 재계산.
    use_cache : 등시선 캐시 사용 여부.

    Returns
    -------
    DataFrame: 집계구별 격차 지표
    """
    if OUTPUT_PATH.exists() and not force:
        logger.info("기존 TB1 결과 로드: %s", OUTPUT_PATH)
        return pd.read_csv(OUTPUT_PATH, dtype={"oa_code": str, "dong_code": str})

    logger.info("TB1 분석 시작 (sample_n=%d)", sample_n)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # 집계구 마스터 로드
    try:
        df_master = build_admin_master()
    except Exception:
        logger.warning("admin_master 없음, oa_master만 사용")
        gdf = build_oa_master()
        df_master = pd.DataFrame({
            "oa_code":       gdf["oa_code"],
            "dong_code":     gdf["dong_code"],
            "sgg_code":      gdf["sgg_code"],
            "centroid_lon":  gdf["centroid_lon"],
            "centroid_lat":  gdf["centroid_lat"],
            "area_m2":       gdf["area_m2"],
            "pop_65plus":    0.0,
            "pop_total":     0.0,
        })

    # 중복 좌표 제거 — 같은 위치에서 계산 중복 방지
    df_master = df_master.dropna(subset=["centroid_lon", "centroid_lat"])
    df_master = df_master.reset_index(drop=True)

    # 그래프 로드
    G = load_walk_graph()

    # 대표 샘플 선정
    if sample_n > 0 and sample_n < len(df_master):
        rng = np.random.default_rng(RANDOM_SEED)
        # 공간적으로 고르게 — 격자 기반 층화 샘플링
        sample_idx = _stratified_sample(df_master, sample_n, rng)
        df_sample = df_master.iloc[sample_idx].copy()
        logger.info("층화 샘플: %d / %d 집계구", len(df_sample), len(df_master))
    else:
        df_sample = df_master.copy()
        logger.info("전체 집계구 계산: %d", len(df_sample))

    # 가장 가까운 노드로 중복 제거
    df_sample = _dedup_by_node(G, df_sample)
    logger.info("노드 중복 제거 후 계산 포인트: %d", len(df_sample))

    # ── 격차 계산 ───────────────────────────────────────────
    results = []
    total = len(df_sample)

    for i, (_, row) in enumerate(df_sample.iterrows()):
        if i % 100 == 0:
            logger.info("TB1 진행: %d/%d (%.1f%%)", i, total, i / total * 100)

        try:
            gap = area_loss_ratio(
                G,
                lon=row["centroid_lon"],
                lat=row["centroid_lat"],
                speed_young=SPEED_YOUNG_MPS,
                speed_senior=SPEED_SENIOR_MPS,
                time_min=RADIUS_TB1_MIN,
            )
        except Exception as e:
            logger.debug("OA %s 계산 오류: %s", row["oa_code"], e)
            gap = {
                "iso_young_area_m2":  np.nan,
                "iso_senior_area_m2": np.nan,
                "loss_ratio":         np.nan,
                "gap_area_m2":        np.nan,
            }

        results.append({
            "oa_code":     row["oa_code"],
            **gap,
        })

    df_calc = pd.DataFrame(results)

    # ── 전체 집계구로 보간 (샘플인 경우) ───────────────────
    if sample_n > 0 and sample_n < len(df_master):
        df_full = _interpolate_to_all(df_master, df_calc)
    else:
        df_full = df_master.merge(df_calc, on="oa_code", how="left")

    # 결측 채우기
    for col in ["iso_young_area_m2", "iso_senior_area_m2", "loss_ratio", "gap_area_m2"]:
        df_full[col] = df_full[col].fillna(df_full[col].median())

    # 정리 & 저장
    out_cols = [
        "oa_code", "dong_code", "sgg_code",
        "centroid_lon", "centroid_lat", "pop_65plus",
        "iso_young_area_m2", "iso_senior_area_m2",
        "loss_ratio", "gap_area_m2",
    ]
    df_out = df_full[[c for c in out_cols if c in df_full.columns]]
    df_out.to_csv(OUTPUT_PATH, index=False)
    logger.info(
        "TB1 저장: %s  loss_ratio 평균=%.3f, 중앙값=%.3f",
        OUTPUT_PATH,
        df_out["loss_ratio"].mean(),
        df_out["loss_ratio"].median(),
    )
    return df_out


# ──────────────────────────────────────────────────────────
# 유틸 — 층화 샘플링
# ──────────────────────────────────────────────────────────

def _stratified_sample(
    df: pd.DataFrame,
    n: int,
    rng: np.random.Generator,
    lon_col: str = "centroid_lon",
    lat_col: str = "centroid_lat",
) -> list[int]:
    """
    서울 범위를 격자로 나눠 각 격자에서 균등 샘플.
    공간 편향 최소화.
    """
    grid_size = max(1, int(np.sqrt(n)))
    lon_vals = df[lon_col].values
    lat_vals = df[lat_col].values

    lon_bins = np.linspace(lon_vals.min(), lon_vals.max(), grid_size + 1)
    lat_bins = np.linspace(lat_vals.min(), lat_vals.max(), grid_size + 1)

    lon_idx = np.digitize(lon_vals, lon_bins) - 1
    lat_idx = np.digitize(lat_vals, lat_bins) - 1
    cell = lon_idx * grid_size + lat_idx

    selected = []
    per_cell = max(1, n // (grid_size * grid_size))
    for c in np.unique(cell):
        idxs = np.where(cell == c)[0]
        take = min(per_cell, len(idxs))
        chosen = rng.choice(idxs, size=take, replace=False)
        selected.extend(chosen.tolist())

    if len(selected) > n:
        selected = rng.choice(selected, size=n, replace=False).tolist()

    return selected


# ──────────────────────────────────────────────────────────
# 유틸 — 노드 중복 제거
# ──────────────────────────────────────────────────────────

def _dedup_by_node(G, df: pd.DataFrame) -> pd.DataFrame:
    """
    여러 집계구가 같은 nearest node에 매핑되면 첫 번째만 남긴다.
    계산 후 보간 단계에서 나머지에게 값 전파.
    """
    df = df.copy()
    nodes = [
        nearest_node(G, row["centroid_lon"], row["centroid_lat"])
        for _, row in df.iterrows()
    ]
    df["_node"] = nodes
    df = df.drop_duplicates(subset="_node", keep="first")
    df = df.drop(columns=["_node"])
    return df


# ──────────────────────────────────────────────────────────
# 유틸 — 전체 집계구로 보간
# ──────────────────────────────────────────────────────────

def _interpolate_to_all(
    df_all: pd.DataFrame,
    df_calc: pd.DataFrame,
) -> pd.DataFrame:
    """
    계산된 샘플 결과를 KD-Tree 최근접 보간으로 전체 집계구에 전파.
    """
    df_sample_full = df_all.merge(df_calc, on="oa_code", how="inner")
    df_rest = df_all[~df_all["oa_code"].isin(df_calc["oa_code"])].copy()

    if df_rest.empty:
        return df_sample_full

    # KD-Tree on (lon, lat)
    src_coords = df_sample_full[["centroid_lon", "centroid_lat"]].values
    tree = cKDTree(src_coords)

    dst_coords = df_rest[["centroid_lon", "centroid_lat"]].values
    _, idx = tree.query(dst_coords, k=1)

    gap_cols = ["iso_young_area_m2", "iso_senior_area_m2", "loss_ratio", "gap_area_m2"]
    for col in gap_cols:
        df_rest[col] = df_sample_full.iloc[idx][col].values

    return pd.concat([df_sample_full, df_rest], ignore_index=True)


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="TB1 보행 격차 분석")
    parser.add_argument("--sample", type=int, default=2000,
                        help="계산 대표 집계구 수 (0=전체, 기본 2000)")
    parser.add_argument("--force", action="store_true",
                        help="기존 결과 무시하고 재계산")
    parser.add_argument("--no-cache", action="store_true",
                        help="등시선 캐시 미사용")
    args = parser.parse_args()

    df = run_tb1(
        sample_n=args.sample,
        force=args.force,
        use_cache=not args.no_cache,
    )

    print(f"\n[TB1 결과 요약]")
    print(f"  집계구 수       : {len(df):,}")
    print(f"  loss_ratio 평균 : {df['loss_ratio'].mean():.3f}")
    print(f"  loss_ratio 중앙 : {df['loss_ratio'].median():.3f}")
    print(f"  loss_ratio 최대 : {df['loss_ratio'].max():.3f}")
    print(f"  출력 파일       : {OUTPUT_PATH}")
