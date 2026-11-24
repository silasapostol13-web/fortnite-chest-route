"""Whole-map scan: score every landing spot, check how sure the winner is, calibrate.

    .venv/bin/python -m route.scan                 # scan all 860 spots, 2:00 on the ground
    .venv/bin/python -m route.scan --robust        # does the winner survive other guesses?
    .venv/bin/python -m route.scan --calibrate splits.csv

Pirate Shop Token: Epic's published odds are 1 in 137,500 per chest, every chest, no
count or time requirement. So the goal is simply: open as many chests as possible.
There is no natural time window, so we use "most chests in the first N seconds on the
ground", which lets one spot be "the best spot to land" for any bus.

Scale trick: map scale and run speed only multiply every travel time by one factor k
(travel = k x modelled). So "what if the map is 20% bigger" is just T * 1.2, and his real
split times can fit k and the per-chest stop time directly.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from . import params as P
from .orienteering import ils_best, nearest_neighbor
from .travel import load_spawns, travel_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
TOKEN_ODDS = 137_500  # Epic, Nov 7 2026: 1 in 137,500 per chest


def scan(T, budget=120.0, stop=P.CHEST_STOP_S, iters=40, refine=15, refine_iters=300):
    """Best chest count from every landing spot. Returns (counts, routes) with counts[i] for spot i."""
    n = len(T)
    counts = np.zeros(n, dtype=int)
    routes = {}
    for i in range(n):
        cand = np.nonzero(T[i] + stop <= budget)[0].tolist()
        r, _ = ils_best(T, i, cand, budget, stop=stop, iters=iters, seed=i)
        counts[i], routes[i] = len(r), r
    for i in np.argsort(-counts, kind="stable")[:refine]:
        cand = np.nonzero(T[i] + stop <= budget)[0].tolist()
        r, _ = ils_best(T, int(i), cand, budget, stop=stop, iters=refine_iters, seed=0)
        if len(r) > counts[i]:
            counts[i], routes[int(i)] = len(r), r
    return counts, routes


def quick_scan(T, budget, stop, refine=25):
    """Cheaper scan for what-if checks: nearest-first everywhere, full solver on the top ones."""
    n = len(T)
    counts = np.zeros(n, dtype=int)
    for i in range(n):
        cand = np.nonzero(T[i] + stop <= budget)[0].tolist()
        counts[i] = len(nearest_neighbor(T, i, cand, budget, stop)[0])
    for i in np.argsort(-counts, kind="stable")[:refine]:
        cand = np.nonzero(T[i] + stop <= budget)[0].tolist()
        counts[i] = max(counts[i], len(ils_best(T, int(i), cand, budget, stop=stop, iters=120)[0]))
    return counts


def area_ranking(counts, areas, top=5):
    """Best spot per named area, ranked (so the top 5 are 5 different places)."""
    best = {}
    for i, c in enumerate(counts):
        a = areas[i]
        if a == "Unnamed area":
            continue
        if a not in best or c > counts[best[a]]:
            best[a] = i
    return sorted(best.items(), key=lambda kv: -counts[kv[1]])[:top]


def robust(T, areas, budget=120.0):
    rows = []
    for k in (0.8, 1.0, 1.2):           # map 20% smaller / as guessed / 20% bigger (or slower running)
        for stop in (1.5, 2.0, 3.0):    # seconds per chest
            c = quick_scan(T * k, budget, stop)
            rank = area_ranking(c, areas, top=3)
            rows.append((k, stop, [(a, int(c[i])) for a, i in rank]))
    return rows


def fit_calibration(rows):
    """rows: (walk_model_s, chests_opened, real_split_s) per split. Fit real = k*walk + c*chests."""
    A = np.array([[w, n] for w, n, _ in rows], dtype=float)
    y = np.array([s for *_, s in rows], dtype=float)
    (k, c), *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(k), float(c)


def calibrate(csv_path):
    """CSV columns: chest (number on the route card), real_time (m:ss or seconds since landing)."""
    plan = json.loads((OUT / "route_card.json").read_text())
    rows = []
    for row in csv.DictReader(open(csv_path)):
        idx = int(row["chest"])
        t = row["real_time"]
        real = int(t.split(":")[0]) * 60 + float(t.split(":")[1]) if ":" in t else float(t)
        step = plan["steps"][idx - 1]
        rows.append((step["walk_s_cum"], idx, real))
    k, c = fit_calibration(rows)
    print(f"Fitted: real travel = {k:.2f} x model, {c:.2f} s per chest stop.")
    print(f"Put into params.py: METERS_PER_PX = {P.METERS_PER_PX * k:.2f} (or RUN_SPEED / {k:.2f}), "
          f"CHEST_STOP_S = {c:.1f}")
    return k, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--robust", action="store_true")
    ap.add_argument("--calibrate", default=None)
    args = ap.parse_args()
    if args.calibrate:
        calibrate(args.calibrate)
        return
    ids, areas, xy = load_spawns()
    T = travel_matrix()
    if args.robust:
        for k, stop, top in robust(T, areas, args.seconds):
            print(f"travel x{k:.1f}, {stop:.1f} s/chest: " + " | ".join(f"{a} {c}" for a, c in top))
        return
    counts, routes = scan(T, args.seconds)
    best = int(np.argmax(counts))
    rank = area_ranking(counts, areas)
    rand = counts.mean()
    exp = counts[best] * P.EXPECTED_CHESTS_PER_SPOT
    print(f"Scanned {len(counts)} spots, {args.seconds:.0f} s on the ground.")
    for a, i in rank:
        print(f"  {a:16} {counts[i]} chest spots (start {ids[i]})")
    print(f"Random drop averages {rand:.1f}; best is {counts[best]} ({counts[best] / rand:.1f}x).")
    print(f"Token odds per game from the best route: about 1 in {TOKEN_ODDS / exp:,.0f} "
          f"(≈{exp:.0f} real chests x 1/{TOKEN_ODDS:,}).")
    OUT.mkdir(exist_ok=True)
    (OUT / "scan.json").write_text(json.dumps({
        "seconds": args.seconds, "counts": counts.tolist(), "random_mean": rand,
        "top5": [[a, int(i), int(counts[i])] for a, i in rank],
        "best": best, "best_route": [int(v) for v in routes[best]],
    }))
    # best_landing.json drives the route animation and card
    rt = float(sum(T[a, b] for a, b in zip(routes[best], routes[best][1:])) + P.CHEST_STOP_S * len(routes[best]))
    (OUT / "best_landing.json").write_text(json.dumps({
        "bus": None, "fixed_seconds": args.seconds, "landing": ids[best], "area": areas[best],
        "land_s": 0, "budget_s": args.seconds, "route": [ids[i] for i in routes[best]],
        "route_idx": [int(i) for i in routes[best]], "route_s": rt, "naive_count": None,
    }, indent=1))


if __name__ == "__main__":
    main()
