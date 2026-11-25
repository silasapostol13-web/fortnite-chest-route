"""Build a recording route with the normal solver and a pinned northeast start."""

import csv
import json
from math import dist
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from route import params, planner_source as source
from route.orienteering import ils_best
from route.travel import LegPather, compute_travel_matrix


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
    travel = compute_travel_matrix(coordinates, terrain.graph)
    candidates = list(range(len(coordinates)))
    target = 33
    # Find a budget that yields the desired number of stops. The route search
    # is the same iterated local search used for standard drop planning.
    low, high = 0, 360
    order, _ = ils_best(travel, start, candidates, high, iters=200)
    if len(order) < target:
        raise ValueError("The recording route did not reach the target stop count")
    for _ in range(8):
        budget = (low + high) / 2
        trial, _ = ils_best(travel, start, candidates, budget, iters=200)
        if len(trial) >= target:
            high = budget
            order = trial
        else:
            low = budget
    order = order[:target]

    chests = coordinates[order].tolist()
    legs = []
    for index, (a, b) in enumerate(zip(chests, chests[1:])):
        path = terrain.path(a, b)
        meters = sum(dist(u, v) for u, v in zip(path, path[1:]))
        legs.append({"path": path, "meters": round(meters * params.METERS_PER_PX),
                     "seconds": round(float(travel[order[index], order[index + 1]]), 2)})
    kinds = [types[i] for i in order]
    route = {
        "name": "Northeast Treasure Island", "film": True,
        "onStartIsland": [i in island for i in order],
        "types": kinds, "chests": chests, "legs": legs,
        "seconds": round(sum(leg["seconds"] for leg in legs) +
                         sum(4 if kind == "buried" else params.CHEST_STOP_S for kind in kinds), 2),
    }
    (source.PLANNER_DIR / "film-route.js").write_text(
        "window.DROP_FILM_ROUTE=" + json.dumps(route, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
