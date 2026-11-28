"""Tracking numbers for one live.py --metrics file (a live take or a replay of one).

    .venv/bin/python scripts/steering/take_stats.py out/live-test-2026-11-28/replay-take1b.json

Prints: frames, fully tracked share, heading/position update rates, how long the untracked stretches are (and when),
chests reached, arrow (target) changes, frame age. Used to prove each tracking fix with before/after numbers.
"""
import json
import sys
from math import dist


def stats(path):
    rows = json.load(open(path))
    if not rows:
        return {"frames": 0}
    t0, t1 = rows[0]["t"], rows[-1]["t"]
    span = max(t1 - t0, 1e-6)
    tracked = [r.get("tracked") for r in rows]
    heads = sum(1 for r in rows if r.get("heading_update"))
    poss = sum(1 for r in rows if r.get("position_update"))
    gaps, start = [], None
    for r, ok in zip(rows, tracked):
        if not ok and start is None:
            start = r["t"]
        if ok and start is not None:
            gaps.append((start, r["t"] - start))
            start = None
    if start is not None:
        gaps.append((start, t1 - start))
    # a reached chest = opened count going up
    opened = max((r.get("opened", 0) for r in rows), default=0)
    targets, changes, still_changes = None, 0, 0
    last = []
    for r in rows:
        tgt = r.get("spot")
        if r.get("position"):
            last.append((r["t"], r["position"]))
            last = [(t, p) for t, p in last if r["t"] - t <= 3]
        if targets is not None and tgt != targets:
            changes += 1
            if len(last) > 1 and dist(last[0][1], last[-1][1]) * 6.0 < 5:   # ~6 m per map px is rough; still = <5 m
                still_changes += 1
        targets = tgt
    ages = sorted(r.get("frame_age_ms", 0) for r in rows)
    long_gaps = [(round(s, 1), round(d, 1)) for s, d in gaps if d >= 2.0]
    return {
        "frames": len(rows), "seconds": round(span, 1),
        "tracked_pct": round(100 * sum(1 for x in tracked if x) / len(rows), 1),
        "heading_hz": round(heads / span, 2), "position_hz": round(poss / span, 2),
        "untracked_stretches_over_2s": len(long_gaps),
        "untracked_seconds_in_those": round(sum(d for _, d in long_gaps), 1),
        "longest_untracked_s": round(max((d for _, d in gaps), default=0), 1),
        "long_gaps_at_s": long_gaps[:25],
        "chests_reached": opened, "arrow_changes": changes,
        "frame_age_ms_p50": round(ages[len(ages) // 2], 1), "frame_age_ms_p95": round(ages[int(len(ages) * .95)], 1),
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p)
        for k, v in stats(p).items():
            print(f"  {k}: {v}")
