"""
isochrone.py — 보행 등시선 계산 유틸리티

핵심 함수
---------
isochrone_polygon(G, start_node, speed_mps, time_min)
    → shapely Polygon (WGS84)

batch_isochrones(G, points_df, speed_mps, time_min)
    → GeoDataFrame (한 행 = 출발점 1개의 등시선)

cache 지원: 같은 (start_node, speed_mps, time_min) 조합은 디스크 캐시 사용.
"""

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import unary_union

from .config import (
    ISOCHRONE_ALPHA, ISOCHRONE_CACHE_DIR,
    SPEED_YOUNG_MPS, SPEED_SENIOR_MPS,
    RADIUS_TB1_MIN,
    CRS_WGS84,
)
from .graph_loader import load_walk_graph, nearest_node, node_coords_wgs84

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Alpha Shape (concave hull)
# ──────────────────────────────────────────────────────────

def _alpha_shape(points: list[Point], alpha: float) -> Polygon:
    """
    포인트 집합의 alpha shape (concave hull) 반환.

    alpha가 작을수록 오목하게 (실제 형태에 가깝게),
    크면 convex hull에 가까워짐.

    shapely >= 2.0의 concave_hull 사용, 없으면 convex_hull fallback.
    """
    if len(points) < 3:
        mp = MultiPoint(points)
        return mp.convex_hull

    try:
        from shapely.geometry import MultiPoint as MP
        mp = MP(points)
        # shapely 2.0+ concave_hull
        ratio = min(alpha * 10, 1.0)  # 0~1 비율로 변환
        return mp.concave_hull(ratio=ratio, allow_holes=False)
    except (AttributeError, TypeError):
        pass

    # fallback: convex hull
    return MultiPoint(points).convex_hull


# ──────────────────────────────────────────────────────────
# 단일 등시선 계산
# ──────────────────────────────────────────────────────────

def isochrone_polygon(
    G: nx.MultiDiGraph,
    start_node: int,
    speed_mps: float,
    time_min: float,
    alpha: float = ISOCHRONE_ALPHA,
    use_cache: bool = True,
) -> Polygon:
    """
    단일 출발 노드에서 지정 보행속도·시간의 등시선 Polygon 반환.

    Parameters
    ----------
    G         : 보행 네트워크 그래프 (노드에 x, y 속성 필요)
    start_node: 출발 노드 ID
    speed_mps : 보행속도 (m/s)
    time_min  : 최대 도달 시간 (분)
    alpha     : alpha shape 파라미터
    use_cache : True이면 디스크 캐시 사용

    Returns
    -------
    shapely Polygon (WGS84 좌표, EPSG:4326)
    """
    cache_key = _cache_key(start_node, speed_mps, time_min, alpha)
    if use_cache:
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached

    cutoff_sec = time_min * 60.0

    # Dijkstra로 도달 가능 노드 + 이동시간 계산
    # MultiDiGraph: weight fn receives {edge_key: edge_data} — pick min-weight parallel edge
    def _travel_time(u, v, d):
        return min(
            data.get("length", 1.0) / speed_mps
            for data in d.values()
        )

    reachable: dict[int, float] = nx.single_source_dijkstra_path_length(
        G,
        start_node,
        cutoff=cutoff_sec,
        weight=_travel_time,
    )

    if len(reachable) < 3:
        # 도달 노드 너무 적으면 빈 폴리곤
        logger.debug("노드 %d: 도달 가능 노드 %d개 (너무 적음)", start_node, len(reachable))
        center = G.nodes[start_node]
        return Point(center["x"], center["y"]).buffer(0.001)

    # 노드 좌표 → WGS84 포인트 (EPSG:5179인 경우 변환)
    node_points = [
        Point(*node_coords_wgs84(G, n))
        for n in reachable
    ]

    poly = _alpha_shape(node_points, alpha)

    if use_cache:
        _save_cache(cache_key, poly)

    return poly


def isochrone_from_coords(
    G: nx.MultiDiGraph,
    lon: float,
    lat: float,
    speed_mps: float,
    time_min: float,
    alpha: float = ISOCHRONE_ALPHA,
    use_cache: bool = True,
) -> Polygon:
    """
    경도·위도로 직접 등시선 계산 (nearest node 자동 탐색).
    """
    node = nearest_node(G, lon, lat)
    return isochrone_polygon(G, node, speed_mps, time_min, alpha, use_cache)


# ──────────────────────────────────────────────────────────
# 배치 등시선 계산
# ──────────────────────────────────────────────────────────

def batch_isochrones(
    points_df: pd.DataFrame,
    speed_mps: float,
    time_min: float,
    lon_col: str = "centroid_lon",
    lat_col: str = "centroid_lat",
    id_col:  str = "oa_code",
    alpha: float = ISOCHRONE_ALPHA,
    use_cache: bool = True,
    log_every: int = 500,
) -> gpd.GeoDataFrame:
    """
    여러 출발점에 대한 등시선을 배치 계산.

    Parameters
    ----------
    points_df : 출발점 DataFrame (lon_col, lat_col, id_col 포함)
    speed_mps : 보행속도 (m/s)
    time_min  : 최대 시간 (분)
    ...

    Returns
    -------
    GeoDataFrame: id_col + geometry (Polygon, EPSG:4326)
    """
    G = load_walk_graph()
    results = []

    total = len(points_df)
    for i, (_, row) in enumerate(points_df.iterrows()):
        if i % log_every == 0:
            logger.info("등시선 계산 %d/%d (%.1f%%)", i, total, i / total * 100)

        poly = isochrone_from_coords(
            G, row[lon_col], row[lat_col], speed_mps, time_min, alpha, use_cache
        )
        results.append({id_col: row[id_col], "geometry": poly})

    gdf = gpd.GeoDataFrame(results, crs=CRS_WGS84)
    logger.info("배치 등시선 완료: %d개", len(gdf))
    return gdf


# ──────────────────────────────────────────────────────────
# 두 등시선 면적 격차 계산 (TB1용)
# ──────────────────────────────────────────────────────────

def area_loss_ratio(
    G: nx.MultiDiGraph,
    lon: float,
    lat: float,
    speed_young: float = SPEED_YOUNG_MPS,
    speed_senior: float = SPEED_SENIOR_MPS,
    time_min: float = RADIUS_TB1_MIN,
    crs_proj: str = "EPSG:5179",
) -> dict:
    """
    동일 출발점에서 청년·노인 등시선 면적 격차 계산.

    Returns
    -------
    dict with keys:
        iso_young_area_m2 : 청년 30분권 면적 (m²)
        iso_senior_area_m2: 노인 30분권 면적 (m²)
        loss_ratio        : 1 - senior/young (0~1)
        gap_area_m2       : 격차 면적 (m²)
    """
    from shapely.ops import transform
    import pyproj

    wgs2proj = pyproj.Transformer.from_crs(CRS_WGS84, crs_proj, always_xy=True).transform

    iso_young  = isochrone_from_coords(G, lon, lat, speed_young,  time_min)
    iso_senior = isochrone_from_coords(G, lon, lat, speed_senior, time_min)

    area_young  = transform(wgs2proj, iso_young).area
    area_senior = transform(wgs2proj, iso_senior).area

    loss_ratio = 1.0 - (area_senior / area_young) if area_young > 0 else 0.0

    return {
        "iso_young_area_m2":  area_young,
        "iso_senior_area_m2": area_senior,
        "loss_ratio":         loss_ratio,
        "gap_area_m2":        max(area_young - area_senior, 0),
    }


# ──────────────────────────────────────────────────────────
# 시설 → 등시선 합집합 (TB3·TB4용)
# ──────────────────────────────────────────────────────────

def reachable_area_from_facilities(
    facilities_df: pd.DataFrame,
    speed_mps: float,
    time_min: float,
    lon_col: str = "lon",
    lat_col: str = "lat",
    use_cache: bool = True,
) -> Polygon:
    """
    시설 위치 목록에서 각 시설의 등시선을 합쳐 도달 가능 영역 반환.

    예) 무더위쉼터 전체의 노인 15분 등시선 합집합
    """
    G = load_walk_graph()
    isos = []
    for _, row in facilities_df.iterrows():
        poly = isochrone_from_coords(
            G, row[lon_col], row[lat_col], speed_mps, time_min, use_cache=use_cache
        )
        isos.append(poly)

    if not isos:
        return Polygon()

    return unary_union(isos)


# ──────────────────────────────────────────────────────────
# 캐시 유틸
# ──────────────────────────────────────────────────────────

def _cache_key(start_node: int, speed_mps: float, time_min: float, alpha: float) -> str:
    raw = f"{start_node}_{speed_mps:.4f}_{time_min:.1f}_{alpha:.4f}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    ISOCHRONE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return ISOCHRONE_CACHE_DIR / f"{key}.pkl"


def _load_cache(key: str) -> Optional[Polygon]:
    p = _cache_path(key)
    if p.exists():
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def _save_cache(key: str, poly: Polygon) -> None:
    with open(_cache_path(key), "wb") as f:
        pickle.dump(poly, f)


def clear_cache() -> None:
    """등시선 캐시 전체 삭제."""
    if ISOCHRONE_CACHE_DIR.exists():
        for f in ISOCHRONE_CACHE_DIR.glob("*.pkl"):
            f.unlink()
    logger.info("등시선 캐시 삭제 완료")


# ──────────────────────────────────────────────────────────
# CLI 테스트
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 서울시청 좌표로 테스트
    TEST_LON, TEST_LAT = 126.9779, 37.5665
    G = load_walk_graph()

    print("청년 30분 등시선 계산 중…")
    result = area_loss_ratio(G, TEST_LON, TEST_LAT)
    print(f"  청년 30분권 면적 : {result['iso_young_area_m2']/1e6:.3f} km²")
    print(f"  노인 30분권 면적 : {result['iso_senior_area_m2']/1e6:.3f} km²")
    print(f"  면적 손실 비율   : {result['loss_ratio']*100:.1f}%")
    print(f"  격차 면적       : {result['gap_area_m2']/1e6:.3f} km²")
