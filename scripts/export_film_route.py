"""Follow nearest unvisited chests by distance from a pinned northeast start."""

import csv
import json
from math import dist
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from route import params, planner_source as source
from route.travel import LegPather, build_grid_graph, cell_of, dijkstra_within


def main():
    width, height = source.MAP_SIZE
    sites = {}
    with (source.PLANNER_DIR / "chest_spawns.csv").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            x = float(row["x_percent"]) * width / 100
            y = float(row["y_percent"]) * height / 100
            sites.setdefault((x, y), row["type"])

    coordinates = np.array(list(sites), dtype=float)
    types = list(sites.values())
    island = {
        i for i, (x, y) in enumerate(coordinates)
        if .75 < x / width < .79 and .28 < y / height < .33
    }
    start = min(island, key=lambda i: coordinates[i, 1] - coordinates[i, 0])
    terrain = LegPather(source.MAP_IMAGE, source.MAP_SIZE)
    # Give land and water the same distance weight. The graph stores these in
    # run-equivalent seconds, a constant conversion that preserves distance order.
    terrain.graph = build_grid_graph(np.zeros_like(terrain.cell_water))
    cells = [cell_of(*point) for point in coordinates]
    target = 33
    remaining = set(range(len(coordinates))) - {start}
    order = [start]
    while len(order) < target:
        current = order[-1]
        limit = 30
        while True:
            distances = dijkstra_within(terrain.graph, cells[current], limit)
            options = []
            for i in remaining:
                if cells[i] in distances:
                    straight = dist(coordinates[current], coordinates[i]) * params.METERS_PER_PX
                    modeled = distances[cells[i]] * params.RUN_SPEED
                    options.append((max(straight, modeled), straight, i))
            if options:
                nearest, _, stop = min(options)
                if nearest <= limit * params.RUN_SPEED:
                    break
            limit *= 2
        order.append(stop)
        remaining.remove(stop)

    chests = coordinates[order].tolist()
    legs = []
    for a, b in zip(chests, chests[1:]):
        path = terrain.path(a, b)
        meters = sum(dist(u, v) for u, v in zip(path, path[1:]))
        legs.append({"path": path, "meters": round(meters * params.METERS_PER_PX)})
    kinds = [types[i] for i in order]
    route = {
        "name": "Northeast Treasure Island", "film": True,
        "onStartIsland": [i in island for i in order],
        "types": kinds, "chests": chests, "legs": legs,
    }
    (source.PLANNER_DIR / "film-route.js").write_text(
        "window.DROP_FILM_ROUTE=" + json.dumps(route, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
