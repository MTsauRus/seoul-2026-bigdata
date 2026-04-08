"""
끊어진 서울 — 합성 데이터 프로토타입
====================================
실제 OSM 데이터 없이 메소드론을 데모하기 위한 미니어처.

가상 도시:
- 10km × 10km
- 격자형 도로망 (250m 간격, 약간의 결손)
- 곡선 철도 한 줄 (지상철도 가정)
- 횡단점은 듬성듬성 (실제 서울처럼 평균 600m 간격, 일부 1.5km 갭)
"""
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
import networkx as nx
from matplotlib.colors import LinearSegmentedColormap

# ============================================================
# [수정 1] 윈도우용 한글 폰트(맑은 고딕) 설정
# ============================================================
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# [수정 2] 저장할 출력 폴더(outputs) 생성
# ============================================================
output_dir = './outputs'
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

rng = np.random.default_rng(42)

# ============================================================
# 1. 가상 도시 만들기
# ============================================================
SIZE_M = 10000          # 10km × 10km
GRID_M = 250            # 격자 간격 250m
N = SIZE_M // GRID_M + 1  # 41 × 41 = 1681 노드

# 1-1. 격자형 보행 도로망
G = nx.Graph()
for i in range(N):
    for j in range(N):
        node = (i, j)
        x, y = i * GRID_M, j * GRID_M
        G.add_node(node, pos=(x, y))

for i in range(N):
    for j in range(N):
        if i + 1 < N:
            G.add_edge((i, j), (i + 1, j), length=GRID_M)
        if j + 1 < N:
            G.add_edge((i, j), (i, j + 1), length=GRID_M)

# 약간의 도로 결손 (실제처럼)
edges_to_remove = rng.choice(list(G.edges()), size=80, replace=False)
G.remove_edges_from([tuple(map(tuple, e)) for e in edges_to_remove])

# ============================================================
# 2. 곡선 철도 (지상)
# ============================================================
# 동서 방향, 약간 곡선
rail_x = np.linspace(500, 9500, 200)
rail_y = 5000 + 800 * np.sin(rail_x / 2500) + 200 * np.cos(rail_x / 800)

# 철도 선분이 가로지르는 도로(에지)는 보행 불가능하게 만들어야 함
# 단, 횡단점에서는 통과 가능
def remove_rail_crossings(G, rail_x, rail_y, exclude_pts):
    """철도가 지나가는 곳의 도로 에지를 제거. 단, exclude_pts 근처는 유지."""
    rail_pts = list(zip(rail_x, rail_y))
    edges_to_remove = []
    for u, v in G.edges():
        ux, uy = G.nodes[u]['pos']
        vx, vy = G.nodes[v]['pos']
        # 에지 중점
        mx, my = (ux + vx) / 2, (uy + vy) / 2
        # 가장 가까운 철도점까지 거리
        dists = [(mx - rx)**2 + (my - ry)**2 for rx, ry in rail_pts]
        min_d = min(dists)**0.5
        if min_d < GRID_M / 2:
            # 횡단점 근처 200m 이내면 제거 안 함
            keep = any(((mx - ex)**2 + (my - ey)**2)**0.5 < 200 for ex, ey in exclude_pts)
            if not keep:
                edges_to_remove.append((u, v))
    G.remove_edges_from(edges_to_remove)
    return len(edges_to_remove)

# 횡단점 (실제 서울처럼 듬성듬성, 일부 큰 갭)
crossing_xs = [800, 1400, 1900, 2300, 3700, 4100, 5400, 6300, 7800, 8500, 9200]
# 위 위치들에서의 철도 y좌표
crossings = []
for cx in crossing_xs:
    idx = np.argmin(np.abs(rail_x - cx))
    crossings.append((rail_x[idx], rail_y[idx]))

n_removed = remove_rail_crossings(G, rail_x, rail_y, crossings)
print(f"철도로 인해 제거된 도로 에지: {n_removed}개")

# ============================================================
# 3. 우회비율 계산 (시각화 1의 핵심 로직)
# ============================================================
# 철도 따라 50개 샘플점, 각 샘플점에서 양옆 200m 떨어진 가상 시민의 N→S 보행거리
sample_idx = np.linspace(10, len(rail_x) - 10, 60).astype(int)

results = []
for idx in sample_idx:
    rx, ry = rail_x[idx], rail_y[idx]
    # 철도의 진행방향
    dx = rail_x[idx + 1] - rail_x[idx - 1]
    dy = rail_y[idx + 1] - rail_y[idx - 1]
    norm = (dx**2 + dy**2) ** 0.5
    # 수직 단위벡터
    nx_, ny_ = -dy / norm, dx / norm
    # 양쪽 200m 점
    n_pt = (rx + nx_ * 200, ry + ny_ * 200)
    s_pt = (rx - nx_ * 200, ry - ny_ * 200)
    # 가장 가까운 그래프 노드
    def nearest(pt):
        best, best_d = None, float('inf')
        px, py = pt
        for node, data in G.nodes(data=True):
            qx, qy = data['pos']
            d = (px - qx)**2 + (py - qy)**2
            if d < best_d:
                best_d, best = d, node
        return best
    n_node = nearest(n_pt)
    s_node = nearest(s_pt)
    try:
        walk = nx.shortest_path_length(G, n_node, s_node, weight='length')
        ratio = walk / 400
    except nx.NetworkXNoPath:
        walk = float('inf')
        ratio = 10.0  # 캡
    results.append({'idx': idx, 'rx': rx, 'ry': ry, 'walk': walk, 'ratio': ratio})

print(f"샘플점 {len(results)}개 우회비율 계산 완료")
print(f"  중앙값: {np.median([r['ratio'] for r in results]):.2f}")
print(f"  최댓값: {max(r['ratio'] for r in results):.2f}")

# ============================================================
# FIG 1 — 단절 지도
# ============================================================
SEOUL_GREEN = '#00B894'
SEOUL_DARK = '#2D3436'
RED = '#E84545'
ORANGE = '#FF9F43'

cmap = LinearSegmentedColormap.from_list('disc', [SEOUL_GREEN, '#FFEAA7', ORANGE, RED, '#8B0000'])

fig, ax = plt.subplots(figsize=(11, 11), facecolor='white')
ax.set_facecolor('#F8F9FA')

# 도로망 (옅게)
for u, v in G.edges():
    x1, y1 = G.nodes[u]['pos']
    x2, y2 = G.nodes[v]['pos']
    ax.plot([x1, x2], [y1, y2], color='#DFE6E9', linewidth=0.6, zorder=1)

# 철도 — 우회비율로 색칠
for r in results:
    color_val = min(r['ratio'] / 6.0, 1.0)
    ax.scatter(r['rx'], r['ry'], c=[cmap(color_val)], s=180, zorder=3, edgecolors='white', linewidth=0.5)

# 철도 라인 자체 (어둡게)
ax.plot(rail_x, rail_y, color=SEOUL_DARK, linewidth=2.2, zorder=2, alpha=0.4)

# 횡단점
for cx, cy in crossings:
    ax.scatter(cx, cy, marker='s', s=140, c='white', edgecolors=SEOUL_DARK, linewidth=2, zorder=4)
    ax.scatter(cx, cy, marker='+', s=80, c=SEOUL_DARK, linewidth=2.5, zorder=5)

ax.set_xlim(0, SIZE_M)
ax.set_ylim(0, SIZE_M)
ax.set_aspect('equal')
ax.set_xticks([])
ax.set_yticks([])
for spine in ax.spines.values():
    spine.set_visible(False)

ax.set_title('끊어진 서울  |  지상철도 단절 지도 (프로토타입)',
             fontsize=18, fontweight='bold', pad=20, color=SEOUL_DARK, loc='left')
ax.text(0, SIZE_M + 200, '점 색깔 = 우회 페널티 (직선 400m → 실제 보행거리 비율)   |   ◻+ = 횡단 가능 지점',
        fontsize=10, color='#636E72')

# 컬러바
cbar_ax = fig.add_axes([0.15, 0.06, 0.7, 0.018])
import matplotlib.cm as cm
import matplotlib.colors as mcolors
norm = mcolors.Normalize(vmin=1, vmax=6)
sm = cm.ScalarMappable(cmap=cmap, norm=norm)
cbar = fig.colorbar(sm, cax=cbar_ax, orientation='horizontal')
cbar.set_label('우회비율 (1.0 = 단절 없음, 6.0 = 6배 우회)', fontsize=9, color='#636E72')
cbar.outline.set_visible(False)

# [수정 3] 상대 경로로 저장
plt.savefig(f'{output_dir}/fig1_disconnection_map.png', dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print("fig1 saved")

# ============================================================
# FIG 2 — Top 10 우회 페널티 막대그래프
# ============================================================
sorted_r = sorted(results, key=lambda r: -r['ratio'])[:10]
labels = [f"구간 {chr(65+i)}  ({int(r['rx'])}m, {int(r['ry'])}m)" for i, r in enumerate(sorted_r)]
ratios = [r['ratio'] for r in sorted_r]
walks = [r['walk'] for r in sorted_r]

fig, ax = plt.subplots(figsize=(12, 7), facecolor='white')
ax.set_facecolor('white')

colors = [RED if i < 3 else ORANGE if i < 6 else '#FDCB6E' for i in range(10)]
bars = ax.barh(range(10), ratios, color=colors, edgecolor='white', linewidth=2)

for i, (r, w) in enumerate(zip(ratios, walks)):
    ax.text(r + 0.08, i, f'{r:.1f}배   ({int(w)}m 우회)',
            va='center', fontsize=11, color=SEOUL_DARK, fontweight='bold')

ax.set_yticks(range(10))
ax.set_yticklabels(labels, fontsize=10, color=SEOUL_DARK)
ax.invert_yaxis()
ax.set_xlim(0, max(ratios) * 1.35)
ax.set_xlabel('우회비율 (실제 보행거리 ÷ 직선거리 400m)', fontsize=11, color='#636E72')
ax.set_title('직선 400m, 실제 보행거리 ___m  —  단절 페널티 Top 10',
             fontsize=16, fontweight='bold', color=SEOUL_DARK, loc='left', pad=15)
ax.axvline(1.0, color=SEOUL_GREEN, linestyle='--', linewidth=1.5, alpha=0.6)
ax.text(1.05, -0.5, '단절 없음', color=SEOUL_GREEN, fontsize=9, fontweight='bold')

for s in ['top', 'right', 'left']:
    ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#DFE6E9')
ax.tick_params(axis='x', colors='#636E72')
ax.tick_params(axis='y', length=0)
ax.grid(axis='x', alpha=0.3, linestyle=':')

plt.tight_layout()

# [수정 3] 상대 경로로 저장
plt.savefig(f'{output_dir}/fig2_top10_detour.png', dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print("fig2 saved")

# ============================================================
# FIG 3 — 횡단점 간격 strip chart
# ============================================================
# 노선 시점 0m부터 누적거리 따라
cum_dist = [0]
for i in range(1, len(rail_x)):
    d = ((rail_x[i] - rail_x[i-1])**2 + (rail_y[i] - rail_y[i-1])**2) ** 0.5
    cum_dist.append(cum_dist[-1] + d)

# 횡단점들의 노선 시점 누적거리 계산
crossing_dists = []
for cx, cy in crossings:
    idx = np.argmin([(cx - x)**2 + (cy - y)**2 for x, y in zip(rail_x, rail_y)])
    crossing_dists.append(cum_dist[idx])

total_len = cum_dist[-1]

fig, ax = plt.subplots(figsize=(14, 4), facecolor='white')
ax.set_facecolor('white')

# 노선 띠
ax.barh([0], [total_len], height=0.4, color='#DFE6E9', edgecolor='none')

# 갭 음영 (횡단점 사이 간격이 800m 이상이면 빨갛게)
sorted_cd = sorted(crossing_dists)
gaps = [(sorted_cd[i], sorted_cd[i+1]) for i in range(len(sorted_cd)-1)]
gaps = [(0, sorted_cd[0])] + gaps + [(sorted_cd[-1], total_len)]
for g_start, g_end in gaps:
    gap_len = g_end - g_start
    if gap_len > 800:
        intensity = min((gap_len - 800) / 1500, 1.0)
        color = (1, 0.4 - 0.3*intensity, 0.4 - 0.3*intensity, 0.5 + 0.3*intensity)
        ax.barh([0], [gap_len], left=g_start, height=0.4, color=color, edgecolor='none')
        ax.text((g_start + g_end)/2, 0.35, f'{int(gap_len)}m\n갭', ha='center', va='bottom',
                fontsize=9, color='#8B0000', fontweight='bold')

# 횡단점 마커
for cd in crossing_dists:
    ax.scatter(cd, 0, marker='|', s=600, c=SEOUL_DARK, linewidth=3, zorder=5)

ax.set_xlim(-100, total_len + 100)
ax.set_ylim(-0.6, 1.2)
ax.set_yticks([])
ax.set_xlabel('노선 시점부터의 거리 (m)', fontsize=10, color='#636E72')
ax.set_title('가상 노선  —  횡단 가능 지점 분포 (| = 횡단점, 빨강 = 800m+ 갭)',
             fontsize=14, fontweight='bold', color=SEOUL_DARK, loc='left', pad=15)

for s in ['top', 'right', 'left']:
    ax.spines[s].set_visible(False)
ax.spines['bottom'].set_color('#DFE6E9')
ax.tick_params(axis='x', colors='#636E72')

plt.tight_layout()

# [수정 3] 상대 경로로 저장
plt.savefig(f'{output_dir}/fig3_strip_chart.png', dpi=180, bbox_inches='tight', facecolor='white')
plt.close()
print("fig3 saved")

print("\n=== 요약 ===")
print(f"가상 도시: {SIZE_M/1000}km × {SIZE_M/1000}km, 도로 노드 {N*N}개")
print(f"가상 철도: {total_len/1000:.1f}km")
print(f"횡단점: {len(crossings)}개")
print(f"평균 우회비율: {np.mean([r['ratio'] for r in results]):.2f}")
print(f"최악 구간 우회비율: {max(r['ratio'] for r in results):.2f}배")