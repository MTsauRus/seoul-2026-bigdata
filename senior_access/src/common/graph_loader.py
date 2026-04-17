"""
graph_loader.py — OSM 보행 그래프 로드

기존 cache/walk_graph.pkl 재활용.
networkx MultiDiGraph를 반환하며, 노드에 x(lon)·y(lat) 속성 보장.
"""

import pickle
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import networkx as nx
import pyproj
from scipy.spatial import cKDTree

from .config import WALK_GRAPH_PKL, CRS_WGS84

# walk_graph.pkl 노드 좌표계: EPSG:5179 (한국 좌표계, meter 단위)
# nearest_node 함수에서 WGS84 입력을 EPSG:5179로 변환하여 사용
_WGS84_TO_5179 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_5179_TO_WGS84 = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

GRAPH_CRS = "EPSG:5179"  # 그래프 노드 좌표계

logger = logging.getLogger(__name__)

_GRAPH_CACHE: Optional[nx.MultiDiGraph] = None
_KDTREE_CACHE: Optional[tuple] = None   # (cKDTree, node_ids_array)


def load_walk_graph(path: Optional[Path] = None, force_reload: bool = False) -> nx.MultiDiGraph:
    """
    서울 보행 네트워크 그래프 반환 (싱글턴 캐시).

    Parameters
    ----------
    path : Path, optional
        그래프 pkl 파일 경로. 기본값은 config.WALK_GRAPH_PKL.
    force_reload : bool
        True이면 캐시를 무시하고 파일에서 다시 로드.

    Returns
    -------
    nx.MultiDiGraph
        노드에 'x'(경도), 'y'(위도) 속성 포함.
    """
    global _GRAPH_CACHE

    if _GRAPH_CACHE is not None and not force_reload:
        return _GRAPH_CACHE

    graph_path = path or WALK_GRAPH_PKL
    if not graph_path.exists():
        raise FileNotFoundError(
            f"walk_graph.pkl 없음: {graph_path}\n"
            "cache/ 디렉토리에 파일이 있는지 확인하세요."
        )

    logger.info("그래프 로드 중: %s", graph_path)
    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    _validate_graph(G)
    _GRAPH_CACHE = G
    logger.info("그래프 로드 완료 — 노드: %d, 엣지: %d", G.number_of_nodes(), G.number_of_edges())
    return G


def _validate_graph(G: nx.MultiDiGraph) -> None:
    """그래프 기본 품질 검증"""
    if G.number_of_nodes() < 50_000:
        raise ValueError(
            f"그래프 노드 수 {G.number_of_nodes()}개 — 서울 전역 그래프가 아닐 수 있음 "
            "(최소 100,000개 기대)"
        )

    # 노드에 x(경도), y(위도) 속성이 있어야 함
    sample_node = next(iter(G.nodes(data=True)))
    node_data = sample_node[1]
    if "x" not in node_data or "y" not in node_data:
        raise ValueError("그래프 노드에 'x'(경도), 'y'(위도) 속성이 없습니다.")

    # 좌표 범위 검증
    # EPSG:5179 (한국 좌표계, meter) 또는 WGS84 모두 허용
    x_vals = [d.get("x", 0) for _, d in G.nodes(data=True)]
    y_vals = [d.get("y", 0) for _, d in G.nodes(data=True)]
    x_min, x_max = min(x_vals), max(x_vals)
    y_min, y_max = min(y_vals), max(y_vals)

    # EPSG:5179 범위 (서울): x 930,000~980,000 / y 1,920,000~1,970,000
    is_5179 = (900_000 < x_min and x_max < 1_100_000)
    # WGS84 범위: x 126~128 / y 37~38
    is_wgs84 = (126.0 < x_min and x_max < 128.0)

    if not (is_5179 or is_wgs84):
        raise ValueError(
            f"노드 좌표 범위 이상: x=[{x_min:.0f}, {x_max:.0f}], y=[{y_min:.0f}, {y_max:.0f}]\n"
            "EPSG:5179 또는 WGS84 범위에 해당하지 않음"
        )
    logger.info("그래프 좌표계: %s", "EPSG:5179 (meter)" if is_5179 else "WGS84")


def _build_kdtree(G: nx.MultiDiGraph) -> tuple:
    """그래프 노드 좌표로 cKDTree 빌드 (최초 1회만 생성)."""
    global _KDTREE_CACHE
    if _KDTREE_CACHE is not None:
        return _KDTREE_CACHE

    node_ids = np.array(list(G.nodes()))
    coords = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in node_ids])
    tree = cKDTree(coords)
    _KDTREE_CACHE = (tree, node_ids)
    logger.info("KD-Tree 빌드 완료 (%d 노드)", len(node_ids))
    return _KDTREE_CACHE


def nearest_node(G: nx.MultiDiGraph, lon: float, lat: float) -> int:
    """
    WGS84 경도·위도에 가장 가까운 그래프 노드 ID 반환.

    그래프 좌표계(EPSG:5179 또는 WGS84)를 자동 감지하여
    입력 좌표를 그래프 좌표계로 변환한 뒤 cKDTree로 최근접 노드 탐색.
    """
    # 그래프 좌표계 감지 (첫 번째 노드 x 값으로 판단)
    sample = next(iter(G.nodes(data=True)))[1]
    is_5179 = sample.get("x", 0) > 10_000  # EPSG:5179이면 수십만

    if is_5179:
        # WGS84 → EPSG:5179 변환
        x, y = _WGS84_TO_5179.transform(lon, lat)
    else:
        x, y = lon, lat

    tree, node_ids = _build_kdtree(G)
    _, idx = tree.query([x, y])
    return int(node_ids[idx])


def node_coords_wgs84(G: nx.MultiDiGraph, node: int) -> tuple[float, float]:
    """
    노드 ID → WGS84 (lon, lat) 좌표 반환.
    그래프가 EPSG:5179이면 변환.
    """
    data = G.nodes[node]
    x, y = data["x"], data["y"]
    if x > 10_000:  # EPSG:5179
        return _5179_TO_WGS84.transform(x, y)
    return x, y


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    G = load_walk_graph()
    print(f"노드: {G.number_of_nodes():,}")
    print(f"엣지: {G.number_of_edges():,}")
    print("그래프 검증 통과")
