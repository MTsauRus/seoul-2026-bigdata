"""
00_build_graph.py
-----------------
osmnx로 서울 전체 보행 네트워크 그래프를 새로 다운로드하고,
new-workspace 전용 캐시에 저장합니다.

기존 cache/walk_graph.pkl은 서울 일부 구역만 커버 (102,200 노드)하는
불완전한 캐시임이 확인됨 → 이 스크립트로 완전한 그래프를 새로 구축.

출력: ../cache/seoul_walk_full.graphml  (약 200-400MB, 10-20분 소요)
"""

import time
import logging
from pathlib import Path

import osmnx as ox
import networkx as nx

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH     = WORKSPACE_ROOT / "cache"
CACHE_PATH.mkdir(exist_ok=True)

GRAPHML_PATH = CACHE_PATH / "seoul_walk_full.graphml"

def build_graph():
    if GRAPHML_PATH.exists():
        logger.info("기존 graphml 로드: %s", GRAPHML_PATH)
        G = ox.load_graphml(str(GRAPHML_PATH))
        logger.info("로드 완료 — 노드: %d, 엣지: %d",
                    G.number_of_nodes(), G.number_of_edges())
        return G

    logger.info("서울 전체 보행 네트워크 다운로드 시작 (osmnx)…")
    logger.info("예상 소요 시간: 10-20분 (네트워크 환경에 따라 상이)")

    t0 = time.time()
    G = ox.graph_from_place(
        "Seoul, South Korea",
        network_type="walk",
        simplify=True,
        retain_all=False,
    )
    elapsed = time.time() - t0
    logger.info("다운로드 완료 (%.1f초) — 노드: %d, 엣지: %d",
                elapsed, G.number_of_nodes(), G.number_of_edges())

    logger.info("graphml 저장 중: %s", GRAPHML_PATH)
    ox.save_graphml(G, str(GRAPHML_PATH))
    logger.info("저장 완료")

    return G


def verify_coverage(G: nx.MultiDiGraph):
    """서울 주요 지점 커버리지 확인"""
    import numpy as np
    import pyproj

    logger.info("\n=== 커버리지 검증 ===")
    checkpoints = [
        ("강동구 길동사거리", 127.1435, 37.5415),
        ("노원구 상계역",    127.0655, 37.6561),
        ("서울시청",        126.9779, 37.5665),
        ("관악구 신림역",   126.9228, 37.4845),
        ("강서구 화곡역",   126.8551, 37.5493),
    ]

    for name, lon, lat in checkpoints:
        node = ox.distance.nearest_nodes(G, lon, lat)
        nx_, ny_ = G.nodes[node]["x"], G.nodes[node]["y"]
        dist = ((nx_ - lon) ** 2 + (ny_ - lat) ** 2) ** 0.5 * 111000
        flag = "✅" if dist < 500 else "⚠️"
        logger.info("  %s %s: 최근접 노드 %.0fm", flag, name, dist)


if __name__ == "__main__":
    G = build_graph()
    verify_coverage(G)
    print(f"\n✅ 그래프 준비 완료: {GRAPHML_PATH}")
    print(f"   노드: {G.number_of_nodes():,}개  |  엣지: {G.number_of_edges():,}개")
