"""Run from the repo root with .venv/bin/python scripts/export_planner.py."""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from math import cos, hypot, radians, sin
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from route import params as P, planner_source as source
from route.landing import BusPath, best_landing
from route.travel import LegPather, compute_travel_matrix

HEADING_STEP = 10
OFFSETS = (-240, 0, 240)


def bus_line(heading, offset):
    """Clip an offset infinite bus line to the map edges."""
    angle = radians(heading)
    dx, dy = sin(angle), -cos(angle)
    width, height = source.MAP_SIZE
    center = (width / 2 + cos(angle) * offset, height / 2 + sin(angle) * offset)
    reach = [
        sorted((-position / direction, (edge - position) / direction))
        for position, direction, edge in zip(center, (dx, dy), (width, height))
        if abs(direction) > 1e-9
    ]
    first = max(pair[0] for pair in reach)
    last = min(pair[1] for pair in reach)
    return BusPath(
        (center[0] + dx * first, center[1] + dy * first),
        (center[0] + dx * last, center[1] + dy * last),
    )


def point(xy):
    return [round(float(value), 2) for value in xy]


def setup_worker(matrix, xy, iters):
    global travel, coordinates, iterations
    travel, coordinates, iterations = matrix, xy, iters


def solve_bus(pair):
    heading, offset = pair
    bus = bus_line(heading, offset)
    landing, _ = best_landing(travel, coordinates, bus, iters=iterations)
    if landing is None:
        raise ValueError(f"No landing available for {heading}° at offset {offset}")
    return heading, offset, bus, landing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--iters", type=int, default=200)
    args = parser.parse_args()
    if args.workers < 1 or args.iters < 1:
        parser.error("--workers and --iters must be positive")
    _, areas, xy = source.load_spawns()
    pather = LegPather(source.MAP_IMAGE, source.MAP_SIZE)
    matrix = compute_travel_matrix(xy, pather.graph, verbose=True)
    combinations = [(heading, offset) for heading in range(0, 360, HEADING_STEP) for offset in OFFSETS]

    @lru_cache(maxsize=None)
    def leg_path(a, b):
        return [point(p) for p in pather.path(xy[a], xy[b])]

    def build_leg(a, b):
        path = leg_path(a, b) if a <= b else leg_path(b, a)[::-1]
        meters = sum(hypot(v[0] - u[0], v[1] - u[1]) for u, v in zip(path, path[1:])) * P.METERS_PER_PX
        return {"path": path, "meters": round(meters), "seconds": round(float(matrix[a, b]), 2)}

    routes = []
    with ProcessPoolExecutor(
        max_workers=args.workers, initializer=setup_worker, initargs=(matrix, xy, args.iters)
    ) as workers:
        for heading, offset, bus, landing in workers.map(solve_bus, combinations):
            indices = landing.route
            routes.append({
                "heading": heading,
                "offset": offset,
                "bus": [point(bus.start), point(bus.end)],
                "name": areas[landing.chest],
                "seconds": round(float(landing.route_s), 2),
                "chests": [point(xy[i]) for i in indices],
                "legs": [build_leg(a, b) for a, b in zip(indices, indices[1:])],
            })
            if len(routes) % 12 == 0:
                print(f"  routes {len(routes)}/{len(combinations)}", flush=True)

    payload = {
        "width": source.MAP_SIZE[0], "height": source.MAP_SIZE[1],
        "version": f"v{source.MAP_VERSION}", "count": len(xy),
        "snapshotDate": source.SNAPSHOT_DATE, "headingStep": HEADING_STEP, "routes": routes,
    }
    json_text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    (source.PLANNER_DIR / "data.json").write_text(json_text + "\n", encoding="utf-8")
    # A local script loads the same snapshot when opening index.html via file://.
    (source.PLANNER_DIR / "data.js").write_text("window.DROP_DATA=" + json_text + ";\n", encoding="utf-8")


if __name__ == "__main__":
    main()
