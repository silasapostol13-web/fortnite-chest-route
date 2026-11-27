"""Measure the arrow against the footage it ran on, from a live.py --metrics file.

    python scripts/steering/live.py --input CLIP --duration 60 --chest 1 --headless --metrics run.json
    python scripts/steering/accuracy.py run.json

Heading check: over 1 s windows where the minimap fix moved more than 5 m, the direction he actually moved
against the OCR compass heading. The compass shows where the camera looks, so strafing or running with the
camera turned counts as error here even when both readings are right.
Arrow check: the bearing the arrow commanded against a fresh Dijkstra path from the same position, 12 m ahead.
"""

import argparse
import json
from math import atan2, degrees, dist
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from route import params, planner_source
from route.travel import LegPather


def wrap(angle):
    return (angle + 180) % 360 - 180


def bearing(a, b):
    return degrees(atan2(b[0] - a[0], a[1] - b[1])) % 360


def point_ahead(path, meters):
    left = meters / params.METERS_PER_PX
    for a, b in zip(path, path[1:]):
        step = dist(a, b)
        if step >= left and step > 0:
            return a[0] + (b[0] - a[0]) * left / step, a[1] + (b[1] - a[1]) * left / step
        left -= step
    return path[-1]


def spread(values):
    values = np.abs(np.array(values, dtype=float))
    return {"n": len(values), "median": round(float(np.median(values)), 1), "p90": round(float(np.percentile(values, 90)), 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.metrics.read_text())
    tracked = [r for r in rows if r.get("tracked")]
    report = {"frames": len(rows), "tracked": len(tracked), "coverage_pct": round(100 * len(tracked) / len(rows), 1)}

    # (a) movement direction against compass heading
    fixes = [(r["t"], r["position"]) for r in tracked if r.get("position_update")]
    errors = []
    for i, (t0, p0) in enumerate(fixes):
        later = [(t, p) for t, p in fixes[i + 1:] if .8 <= t - t0 <= 1.2]
        if not later:
            continue
        t1, p1 = later[0]
        if dist(p0, p1) * params.METERS_PER_PX <= 5:
            continue
        headings = [r["heading"] for r in tracked if t0 <= r["t"] <= t1]
        mean = degrees(atan2(np.mean([np.sin(np.radians(h)) for h in headings]),
                             np.mean([np.cos(np.radians(h)) for h in headings])))
        errors.append(wrap(bearing(p0, p1) - mean))
    if errors:
        report["heading_vs_movement_deg"] = {**spread(errors),
                                             "off_by_45_pct": round(100 * np.mean(np.abs(errors) > 45), 1)}

    # (b), (c) commanded bearing against a fresh path from the same spot
    terrain = LegPather(planner_source.MAP_IMAGE, planner_source.MAP_SIZE)
    cache, differences = {}, []
    for r in tracked:
        key = tuple(r["position"]), tuple(r["target"])
        if key not in cache:
            path = terrain.path(r["position"], r["target"])
            cache[key] = None if dist(r["position"], r["target"]) * params.METERS_PER_PX < 12 else \
                bearing(r["position"], point_ahead(path, 12))
        if cache[key] is not None:
            differences.append(wrap(r["waypoint_bearing"] - cache[key]))
    if differences:
        report["arrow_vs_path_deg"] = spread(differences)
        report["wrong_way_pct"] = round(100 * np.mean(np.abs(differences) > 90), 2)

    # (d) lag inside the process
    def pair(name, source):
        values = [r[name] for r in source if name in r]
        return {"p50": round(float(np.percentile(values, 50)), 1), "p95": round(float(np.percentile(values, 95)), 1)}
    report["frame_to_hud_ms"] = pair("frame_age_ms", rows)
    report["heading_age_ms"] = pair("heading_age_ms", tracked)
    report["position_age_ms"] = pair("position_age_ms", tracked)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
