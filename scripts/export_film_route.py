"""Build a fixed 33-stop route from the northeast buried-chest island."""

from functools import lru_cache
from math import hypot
from pathlib import Path
import csv
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from route import params, planner_source as source
from route.travel import LegPather, cell_of


def main():
    with (source.PLANNER_DIR / "chest_spawns.csv").open(newline="", encoding="utf-8") as file:
        records = [(float(r["x_percent"]), float(r["y_percent"]), r["type"]) for r in csv.DictReader(file)]
    def pixels(x, y):
        return x * source.MAP_SIZE[0] / 100, y * source.MAP_SIZE[1] / 100

    island_sites = {pixels(x, y): kind for x, y, kind in records if 75 < x < 79 and 28 < y < 33}
    # Northeastern mainland cluster, immediately west of the isolated island.
    mainland = list(dict.fromkeys(pixels(x, y) for x, y, kind in records
                                 if kind in {"regular", "guaranteed"} and 55 < x < 72 and 42 < y < 55))
    if not island_sites or not 0 < 33 - len(island_sites) <= len(mainland):
        raise ValueError("The source does not contain the island and mainland stops for this route")
    grid = LegPather(source.MAP_IMAGE, source.MAP_SIZE)

    @lru_cache(maxsize=None)
    def pairs(a, b):
        return grid.graph.dijkstra(cell_of(*a), cell_of(*b))

    def cost(a, b):
        direct = hypot(b[0] - a[0], b[1] - a[1]) * params.METERS_PER_PX / params.RUN_SPEED
        _, seconds = pairs(*sorted((a, b)))
        return max(direct, seconds)

    def grow(start, pool, count):
        order = [start]
        remaining = set(pool) - {start}
        while len(order) < count:
            stop = min(remaining, key=lambda p: (cost(order[-1], p), p))
            order.append(stop)
            remaining.remove(stop)
        return order

    def distance(order):
        return sum(cost(a, b) for a, b in zip(order, order[1:]))

    # Sweep the island from its northeast edge, then cross toward the mainland.
    start = min(island_sites, key=lambda p: p[1] - p[0])
    island = grow(start, island_sites, len(island_sites))
    entry_points = sorted(mainland, key=lambda p: (cost(island[-1], p), p))[:6]
    stop_order = min((island + grow(entry, mainland, 33 - len(island)) for entry in entry_points),
                     key=distance)
    legs = []
    for a, b in zip(stop_order, stop_order[1:]):
        path = grid.path(a, b)
        meters = sum(hypot(v[0] - u[0], v[1] - u[1]) for u, v in zip(path, path[1:]))
        legs.append({"path": [list(p) for p in path], "meters": round(meters * params.METERS_PER_PX),
                     "seconds": round(cost(a, b), 2)})
    route = {
        "name": "Northeast Treasure Island", "film": True, "island": len(island),
        "buried": sum(kind == "buried" for kind in island_sites.values()),
        "types": [island_sites.get(p, "standard") for p in stop_order],
        "chests": stop_order, "legs": legs,
        "seconds": round(distance(stop_order) + sum(4 if island_sites.get(p) == "buried" else params.CHEST_STOP_S for p in stop_order), 2),
    }
    (source.PLANNER_DIR / "film-route.js").write_text(
        "window.DROP_FILM_ROUTE=" + json.dumps(route, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
