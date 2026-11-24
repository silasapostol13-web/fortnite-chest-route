"""Real walking times between chests, around water, using Silas's Graph and Dijkstra.

1. The map image is cut into a grid of ~8.5 m cells. Each cell is land (run) or
   deep water (swim), read from the pixel colours.
2. The grid goes into Silas's ``Graph`` class from the class project, unchanged.
   Each cell is a node, each step to one of its 8 neighbours is an edge whose
   weight is the seconds that step takes.
3. From every chest a time-limited Dijkstra (same algorithm as his, see
   ``dijkstra_within``) finds the chests you can reach in under a minute.
4. Floyd-Warshall (numpy) fills in every other chest-to-chest time.
5. When a route is drawn, each leg's exact walking path comes from his own
   ``Graph.dijkstra(start, end)``.
"""

from __future__ import annotations

import hashlib
import sys
from heapq import heappop, heappush
from math import dist, hypot
from pathlib import Path

import numpy as np
from PIL import Image

from . import params as P

ROOT = Path(__file__).resolve().parent.parent
CLASS_DIR = ROOT / "class"
if str(CLASS_DIR) not in sys.path:
    sys.path.insert(0, str(CLASS_DIR))

from main import Graph  # noqa: E402  Silas's class code, imported as-is
from chest_data import CHEST_SPAWNS  # noqa: E402

MAP_IMAGE = ROOT / "data" / "crossbones-isle-43.00.webp"
CACHE_DIR = ROOT / "data" / "cache"
LOCAL_LIMIT_S = 60.0  # how far each per-chest Dijkstra looks before Floyd-Warshall takes over


def load_spawns():
    """Return (ids, areas, xy) with xy an (n, 2) array of logical map pixels."""
    ids = [row[0] for row in CHEST_SPAWNS]
    areas = [row[1] for row in CHEST_SPAWNS]
    xy = np.array([(row[2], row[3]) for row in CHEST_SPAWNS], dtype=float)
    return ids, areas, xy


def water_mask_image(image_path=MAP_IMAGE):
    """Boolean array, True where the map image shows deep water."""
    im = np.asarray(Image.open(image_path).convert("RGB")).astype(int)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    return (r < 90) & (b > 110) & (b > r + 60) & (b >= g - 25)


def build_cell_water(image_path=MAP_IMAGE, cell_px=P.CELL_PX):
    """(rows, cols) bool grid in logical-pixel cells: True = mostly water."""
    water = water_mask_image(image_path)
    lw, lh = P.MAP_LOGICAL_SIZE
    cols, rows = int(np.ceil(lw / cell_px)), int(np.ceil(lh / cell_px))
    sx, sy = water.shape[1] / lw, water.shape[0] / lh
    out = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        y0, y1 = int(r * cell_px * sy), max(int(r * cell_px * sy) + 1, int((r + 1) * cell_px * sy))
        for c in range(cols):
            x0, x1 = int(c * cell_px * sx), max(int(c * cell_px * sx) + 1, int((c + 1) * cell_px * sx))
            out[r, c] = water[y0:y1, x0:x1].mean() > 0.5
    return out


def cell_of(x, y, cell_px=P.CELL_PX):
    return (int(y // cell_px), int(x // cell_px))


def build_grid_graph(cell_water, cell_px=P.CELL_PX):
    """Silas's Graph over grid cells. Edge weight = seconds to walk/swim that step."""
    rows, cols = cell_water.shape
    step_m = cell_px * P.METERS_PER_PX
    sec_per_m = np.where(cell_water, 1 / P.SWIM_SPEED, 1 / P.RUN_SPEED)
    graph = Graph()
    for r in range(rows):
        for c in range(cols):
            graph.add_node((r, c))
    # Each undirected edge added once (his add_edge stores both directions).
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                r2, c2 = r + dr, c + dc
                if 0 <= r2 < rows and 0 <= c2 < cols:
                    length = step_m * hypot(dr, dc)
                    seconds = length * (sec_per_m[r, c] + sec_per_m[r2, c2]) / 2
                    graph.add_edge((r, c), (r2, c2), seconds)
    return graph


def dijkstra_within(graph, start, limit):
    """Silas's Dijkstra, changed to find every node within ``limit`` seconds.

    Same heap, same stale-entry skip, same relax step as ``Graph.dijkstra`` in
    class/main.py. The differences: no single destination, and it stops
    expanding past ``limit``.
    """
    distances = {start: 0.0}
    queue = [(0.0, start)]
    while queue:
        current_distance, current = heappop(queue)
        if current_distance > distances[current]:
            continue
        for neighbor_id, edge_distance in graph.neighbor_lookup(current):
            new_distance = current_distance + edge_distance
            if new_distance <= limit and new_distance < distances.get(neighbor_id, float("inf")):
                distances[neighbor_id] = new_distance
                heappush(queue, (new_distance, neighbor_id))
    return distances


def floyd_warshall(matrix):
    """All-pairs shortest times, in place on a float numpy matrix."""
    d = matrix
    for k in range(d.shape[0]):
        np.minimum(d, d[:, k, None] + d[None, k, :], out=d)
    return d


def _cache_key():
    text = repr((P.METERS_PER_PX, P.CELL_PX, P.RUN_SPEED, P.SWIM_SPEED, LOCAL_LIMIT_S, len(CHEST_SPAWNS), "v1"))
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def travel_matrix(use_cache=True, verbose=False):
    """(n, n) seconds to walk from chest i to chest j (no chest-open time)."""
    path = CACHE_DIR / f"travel_{_cache_key()}.npy"
    if use_cache and path.exists():
        return np.load(path)
    ids, _, xy = load_spawns()
    n = len(ids)
    cell_water = build_cell_water()
    graph = build_grid_graph(cell_water)
    cells = [cell_of(x, y) for x, y in xy]
    by_cell = {}
    for i, cell in enumerate(cells):
        by_cell.setdefault(cell, []).append(i)

    T = np.full((n, n), np.inf)
    np.fill_diagonal(T, 0.0)
    for count, (cell, members) in enumerate(by_cell.items()):
        reach = dijkstra_within(graph, cell, LOCAL_LIMIT_S)
        for other_cell, others in by_cell.items():
            t = reach.get(other_cell)
            if t is None:
                continue
            for i in members:
                for j in others:
                    if i != j:
                        straight = dist(xy[i], xy[j]) * P.METERS_PER_PX / P.RUN_SPEED
                        T[i, j] = min(T[i, j], max(t, straight))
        if verbose and count % 100 == 0:
            print(f"  dijkstra {count}/{len(by_cell)}")
    T = np.minimum(T, T.T)  # walking is symmetric; removes rounding asymmetry
    floyd_warshall(T)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, T)
    return T


class LegPather:
    """Exact walking path for one leg, from Silas's own Graph.dijkstra."""

    def __init__(self):
        self.cell_water = build_cell_water()
        self.graph = build_grid_graph(self.cell_water)

    def path(self, a_xy, b_xy):
        start, end = cell_of(*a_xy), cell_of(*b_xy)
        cells, _seconds = self.graph.dijkstra(start, end)
        pts = [((c + 0.5) * P.CELL_PX, (r + 0.5) * P.CELL_PX) for r, c in cells]
        return [tuple(a_xy)] + pts[1:-1] + [tuple(b_xy)] if len(pts) >= 2 else [tuple(a_xy), tuple(b_xy)]
