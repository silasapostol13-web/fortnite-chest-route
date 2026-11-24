"""Command line.

    .venv/bin/python run.py land                 # best landing for the default bus path
    .venv/bin/python run.py land --bus 60,1250,1150,80 --seconds 90
    .venv/bin/python run.py compare              # exact vs heuristic vs naive
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from route import params as P
from route.landing import BusPath, best_landing
from route.orienteering import exact_best, ils_best, nearest_neighbor
from route.travel import load_spawns, travel_matrix

DEFAULT_BUS = (60, 1250, 1150, 80)  # south-west corner to north-east corner
OUT = Path(__file__).resolve().parent / "out"


def cmd_land(args):
    ids, areas, xy = load_spawns()
    T = travel_matrix()
    bus = BusPath(tuple(args.bus[:2]), tuple(args.bus[2:]))
    t0 = time.time()
    best, ranked = best_landing(T, xy, bus, fixed_budget=args.seconds, refine=args.refine)
    took = time.time() - t0
    budget = f"{args.seconds:.0f} s on the ground" if args.seconds else "until the first storm closes"
    print(f"Bus {bus.start} -> {bus.end}. Checked {len(ranked)} landing spots ({budget}) in {took:.1f} s.")
    print(f"Land on {ids[best.chest]} in {areas[best.chest]}: on the ground at {best.land_s:.0f} s, "
          f"{best.budget_s:.0f} s to loot.")
    n = len(best.route)
    print(f"Route opens {n} chest spots in {best.route_s:.0f} s "
          f"(about {n * P.EXPECTED_CHESTS_PER_SPOT:.0f} real chests, since not every spot spawns one).")
    print(f"Nearest-chest-first from the same spot: {best.naive_count}.")
    print("Runner-up drops:")
    for L in ranked[1:6]:
        print(f"  {ids[L.chest]:5} {areas[L.chest]:16} {len(L.route)} spots")
    OUT.mkdir(exist_ok=True)
    result = {
        "bus": [list(bus.start), list(bus.end)],
        "fixed_seconds": args.seconds,
        "landing": ids[best.chest], "area": areas[best.chest],
        "land_s": best.land_s, "budget_s": best.budget_s,
        "route": [ids[i] for i in best.route], "route_idx": [int(i) for i in best.route],
        "route_s": best.route_s, "naive_count": best.naive_count,
    }
    (OUT / "best_landing.json").write_text(json.dumps(result, indent=1))
    print(f"Saved {OUT / 'best_landing.json'}")


def cmd_compare(args):
    """Exact DP vs heuristic vs naive, on the real map, around many landing spots."""
    ids, areas, xy = load_spawns()
    T = travel_matrix()
    rng = np.random.default_rng(0)
    starts = rng.choice(len(ids), size=args.cases, replace=False)
    rows = []
    for s in starts:
        cluster = np.argsort(T[s])[: args.k].tolist()  # the k closest chest spots, incl. s
        budget = args.budget
        t0 = time.time(); ex, _ = exact_best(T, int(s), cluster, budget); te = time.time() - t0
        t0 = time.time(); h, _ = ils_best(T, int(s), cluster, budget, iters=300); th = time.time() - t0
        nn, _ = nearest_neighbor(T, int(s), cluster, budget)
        full_cand = np.nonzero(T[s] <= budget)[0].tolist()
        hf, _ = ils_best(T, int(s), full_cand, budget, iters=150)
        rows.append((len(ex), len(h), len(nn), len(hf), te, th))
    a = np.array(rows, dtype=float)
    print(f"{args.cases} landing spots, {args.budget:.0f} s budget, exact limited to the {args.k} nearest spots")
    print(f"  heuristic == exact on the small cluster: {(a[:, 1] == a[:, 0]).sum():.0f}/{len(a)}")
    print(f"  average chests  exact {a[:, 0].mean():.2f}  heuristic {a[:, 1].mean():.2f}  "
          f"nearest-first {a[:, 2].mean():.2f}")
    print(f"  heuristic with the whole map open: {a[:, 3].mean():.2f} (exact can't do this: 2^n blows up)")
    print(f"  time per case  exact {a[:, 4].mean():.2f} s   heuristic {a[:, 5].mean():.3f} s")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    land = sub.add_parser("land")
    land.add_argument("--bus", type=lambda s: [float(v) for v in s.split(",")], default=list(DEFAULT_BUS))
    land.add_argument("--seconds", type=float, default=None, help="fixed loot time instead of the storm model")
    land.add_argument("--refine", type=int, default=20)
    land.set_defaults(fn=cmd_land)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--cases", type=int, default=30)
    cmp_.add_argument("--k", type=int, default=14)
    cmp_.add_argument("--budget", type=float, default=60.0)
    cmp_.set_defaults(fn=cmd_compare)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
