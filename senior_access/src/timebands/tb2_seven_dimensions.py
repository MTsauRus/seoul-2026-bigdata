"""
tb2_seven_dimensions.py — 7개 차원 시설 도달 분석

노인 보행속도(0.78 m/s)로 30분 내 도달 가능한
7개 차원 시설 수를 집계구별로 계산.

7개 차원
--------
1. medical   : 의료·보건 (의원, 보건소, 약국)
2. transport : 교통·이동 (저상버스 정류장, 지하철 엘리베이터)
3. welfare   : 복지·커뮤니티 (경로당, 노인복지관)
4. infra     : 생활 인프라 (전통시장, 슈퍼마켓)
5. safety    : 안전·치안 (주민센터, CCTV)
6. climate   : 기후재난 (무더위쉼터, 한파쉼터)
7. social    : 사회적 관계망 (공원, 종교시설)

산출물
------
data/processed/tb2_seven_dims.csv
    oa_code, dong_code, sgg_code,
    cnt_medical, cnt_transport, cnt_welfare, cnt_infra,
    cnt_safety, cnt_climate, cnt_social,
    dim_count : 최소 1개 이상 도달 가능 차원 수 (0~7)
"""

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from ..common.config import (
    PROCESSED_DIR, INTERIM_DIR,
    SPEED_SENIOR_MPS, RADIUS_TB2_MIN,
    CRS_WGS84, RANDOM_SEED,
)
from ..common.admin_master import build_oa_master
from ..common.graph_loader import load_walk_graph, nearest_node
from ..common.facility_loader import load_dimension, DIMENSIONS

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROCESSED_DIR / "tb2_seven_dims.csv"


# ──────────────────────────────────────────────────────────
# 메인 분석 함수
# ──────────────────────────────────────────────────────────

def run(
    sample_n: int = 0,
    force: bool = False,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    TB2 7개 차원 시설 도달 분석 실행.

    각 집계구 centroid에서 노인 30분권 내 각 차원별 시설 수 계산.
    시설 좌표를 nearest_node로 변환 후 Dijkstra로 도달 시간 계산.

    Parameters
    ----------
    sample_n : 계산 대표 집계구 수 (0=전체)
    force    : 기존 결과 무시
    use_cache: 등시선 캐시 사용 여부

    Returns
    -------
    DataFrame: 집계구별 7차원 시설 카운트
    """
    if OUTPUT_PATH.exists() and not force:
        logger.info("기존 tb2_seven_dims.csv 로드")
        return pd.read_csv(OUTPUT_PATH, dtype={"oa_code": str, "dong_code": str})

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("=== TB2 7개 차원 시설 도달 분석 시작 ===")

    # ── 1. 시설 데이터 로드 ───────────────────────────────
    dim_facilities: dict[str, pd.DataFrame] = {}
    for dim in DIMENSIONS:
        df = load_dimension(dim)
        if not df.empty:
            dim_facilities[dim] = df
            logger.info("차원 '%s': %d건", dim, len(df))
        else:
            logger.warning("차원 '%s': 데이터 없음", dim)

    if not dim_facilities:
        logger.error("사용 가능한 시설 데이터 없음. TB2 중단.")
        return pd.DataFrame()

    # ── 2. 그래프 로드 + 시설 nearest_node 사전 계산 ─────
    G = load_walk_graph()

    # 차원별 시설의 nearest_node set 생성 (빠른 도달 판정용)
    dim_node_sets: dict[str, set[int]] = {}
    for dim, df_fac in dim_facilities.items():
        nodes = set()
        for _, row in df_fac.iterrows():
            try:
                n = nearest_node(G, row["lon"], row["lat"])
                nodes.add(n)
            except Exception:
                pass
        dim_node_sets[dim] = nodes
        logger.info("차원 '%s' 시설 노드: %d개 (unique)", dim, len(nodes))

    # ── 3. 집계구 마스터 로드 ─────────────────────────────
    oa_master_path = INTERIM_DIR / "oa_master.gpkg"
    if not oa_master_path.exists():
        gdf_oa = build_oa_master()
    else:
        gdf_oa = gpd.read_file(oa_master_path)

    df_oa = pd.DataFrame({
        "oa_code":      gdf_oa["oa_code"],
        "dong_code":    gdf_oa["dong_code"],
        "sgg_code":     gdf_oa["sgg_code"],
        "centroid_lon": gdf_oa["centroid_lon"],
        "centroid_lat": gdf_oa["centroid_lat"],
    })

    # 샘플 선정
    if sample_n > 0 and sample_n < len(df_oa):
        rng = np.random.default_rng(RANDOM_SEED)
        idx = rng.choice(len(df_oa), size=sample_n, replace=False)
        df_sample = df_oa.iloc[idx].copy()
        logger.info("샘플: %d / %d 집계구", len(df_sample), len(df_oa))
    else:
        df_sample = df_oa.copy()

    # ── 4. 집계구별 각 차원 시설 수 계산 ─────────────────
    cutoff_sec = RADIUS_TB2_MIN * 60.0  # 30분 = 1800초
    speed = SPEED_SENIOR_MPS

    def travel_time(u, v, d):
        return min(data.get("length", 1.0) / speed for data in d.values())

    records = []
    total = len(df_sample)

    for i, (_, row) in enumerate(df_sample.iterrows()):
        if i % 200 == 0:
            logger.info("TB2 진행: %d/%d (%.1f%%)", i, total, i / total * 100)

        start_node = nearest_node(G, row["centroid_lon"], row["centroid_lat"])

        # 30분 내 도달 가능 노드 집합
        try:
            reachable_nodes = set(
                nx_dijkstra(G, start_node, cutoff_sec, travel_time)
            )
        except Exception as e:
            logger.debug("OA %s Dijkstra 오류: %s", row["oa_code"], e)
            reachable_nodes = set()

        # 차원별 도달 시설 수 (교집합 크기)
        row_data = {
            "oa_code":   row["oa_code"],
            "dong_code": row["dong_code"],
            "sgg_code":  row["sgg_code"],
        }
        dim_count = 0
        for dim in DIMENSIONS:
            if dim in dim_node_sets:
                cnt = len(reachable_nodes & dim_node_sets[dim])
                row_data[f"cnt_{dim}"] = cnt
                if cnt > 0:
                    dim_count += 1
            else:
                row_data[f"cnt_{dim}"] = 0
        row_data["dim_count"] = dim_count
        records.append(row_data)

    df_calc = pd.DataFrame(records)

    # 샘플인 경우 전체로 보간
    if sample_n > 0 and sample_n < len(df_oa):
        df_full = _interpolate_to_all(df_oa, df_calc)
    else:
        df_full = df_calc

    df_full.to_csv(OUTPUT_PATH, index=False)
    _print_summary(df_full)
    logger.info("TB2 저장: %s", OUTPUT_PATH)
    return df_full


# ──────────────────────────────────────────────────────────
# Dijkstra 래퍼
# ──────────────────────────────────────────────────────────

def nx_dijkstra(G, start_node: int, cutoff: float, weight_fn) -> dict:
    """단일 출발 노드 Dijkstra, 도달 가능 노드 dict 반환."""
    try:
        import networkx as nx
        return nx.single_source_dijkstra_path_length(
            G, start_node, cutoff=cutoff, weight=weight_fn
        )
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────
# 유틸 — 전체 집계구로 보간
# ──────────────────────────────────────────────────────────

def _interpolate_to_all(
    df_all: pd.DataFrame,
    df_calc: pd.DataFrame,
) -> pd.DataFrame:
    """KD-Tree 최근접 보간으로 샘플 → 전체 집계구."""
    from scipy.spatial import cKDTree

    df_sampled = df_all.merge(df_calc, on="oa_code", how="inner")
    df_rest = df_all[~df_all["oa_code"].isin(df_calc["oa_code"])].copy()

    if df_rest.empty:
        return df_sampled

    src_coords = df_sampled[["centroid_lon", "centroid_lat"]].values
    tree = cKDTree(src_coords)
    dst_coords = df_rest[["centroid_lon", "centroid_lat"]].values
    _, idx = tree.query(dst_coords, k=1)

    cnt_cols = [f"cnt_{dim}" for dim in DIMENSIONS] + ["dim_count"]
    for col in cnt_cols:
        if col in df_sampled.columns:
            df_rest[col] = df_sampled.iloc[idx][col].values

    return pd.concat([df_sampled, df_rest], ignore_index=True)


# ──────────────────────────────────────────────────────────
# 요약 출력
# ──────────────────────────────────────────────────────────

def _print_summary(df: pd.DataFrame) -> None:
    available_dims = [d for d in DIMENSIONS if f"cnt_{d}" in df.columns]
    print("\n" + "="*55)
    print("TB2 7개 차원 시설 도달 분석 결과")
    print("="*55)
    print(f"  분석 집계구 수   : {len(df):,}개")
    print(f"  분석 차원 수     : {len(available_dims)}개 / 7개")
    print()
    for dim in available_dims:
        col = f"cnt_{dim}"
        zero_pct = (df[col] == 0).mean() * 100
        avg = df[col].mean()
        print(f"  {dim:12s}: 평균 {avg:.1f}건, 도달불가 {zero_pct:.1f}%")
    print()
    print(f"  dim_count 평균 : {df['dim_count'].mean():.2f}개 (최대 {len(available_dims)})")
    zero_all = (df["dim_count"] == 0).sum()
    print(f"  모든 차원 0    : {zero_all:,}개 ({zero_all/len(df)*100:.1f}%)")
    print("="*55)


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="TB2 7개 차원 시설 도달 분석")
    parser.add_argument("--sample", type=int, default=0,
                        help="샘플 집계구 수 (0=전체)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    df = run(sample_n=args.sample, force=args.force)
    print(f"\n산출물: {OUTPUT_PATH}")
