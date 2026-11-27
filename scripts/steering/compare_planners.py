"""Compare the live planner (``replan.Planner``, orienteering + hold rule) with the full-map tour (``tour.py``).

Two tests, no game needed:

replay   his real positions from a ``live.py --metrics`` file, fed through both planners on the file's own
         clock with the same arrive / walked-past rules as ``live.py``. He was NOT following either arrow in
         these recordings, so this measures how stable the arrow is under real movement, not chests opened.
sim      a simulated player who runs the Dijkstra path to whatever the arrow says (optionally wandering off
         to the nearest chest 20% of the time), 10 minutes from several starts: chests opened per 10 min.

    python scripts/steering/compare_planners.py replay TRACE.json [...] --out out/steering/planner-compare.json
    python scripts/steering/compare_planners.py sim --out out/steering/planner-sim.json
"""

from __future__ import annotations

import argparse
import json
from math import dist
from pathlib import Path
import random
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from route import params, planner_source  # noqa: E402
from route.travel import LegPather, cell_of  # noqa: E402
from replan import Planner  # noqa: E402
from tour import TourPlanner  # noqa: E402

M = params.METERS_PER_PX
ARRIVE_M, ARRIVE_S, PASS_M, PASS_S = 8.0, 1.5, 6.0, 1.5
HOLD_S, PLAN_EVERY = 3.0, 1.0
PLANNERS = ["now", "frozen"]


def arrive_radius(target, last_reached, meters=ARRIVE_M):
    """Same rule as ``live.arrive_radius`` (copied so this script doesn't need the capture stack)."""
    if last_reached is None:
        return meters
    gap = dist(target, last_reached) * M
    return min(meters, max(4.0, .45 * gap)) if gap < 2 * meters else meters


class Arm:
    """One planner plus the bookkeeping live.py does around it."""

    def __init__(self, name, base, terrain):
        self.name, self.base, self.terrain = name, base, terrain
        if name == "frozen":
            from frozen import FrozenPlanner
            self.tour = FrozenPlanner(base, terrain)
        else:
            self.tour = TourPlanner(base, terrain) if name == "tour" else None
        self.visited, self.opened = set(), 0
        self.target = None
        self.last_plan = float("-inf")
        self.last_switch = float("-inf")
        self.near_since = None
        self.last_reached = None
        self.passing = {}
        self.events = []        # (t, kind, old, new)
        self.plan_ms = []
        self.tick_ms = []       # every planner call (frozen/tour run cheap checks on every fix)
        self.first_stop_m = []  # metres from him to each new arrow target
        self.ignored = []       # (t, spot, metres, detour_s): an unopened spot within 8 m while the arrow points elsewhere

    def deal(self, spot, opened, now, why):
        self.visited.add(spot)
        self.opened += opened
        if self.tour:
            self.tour.mark(spot)
        if spot == self.target:
            if opened:
                self.last_reached = tuple(self.base.xy[spot])
            self.target = None
            self.near_since = None
        self.events.append((now, why, spot, None))

    def step(self, player, now):
        """One position fix."""
        xy = self.base.xy
        # walked past another regular/guaranteed spot
        near = np.flatnonzero(np.hypot(*(xy - np.asarray(player)).T) * M <= PASS_M)
        near = {int(i) for i in near if self.base.kinds[i] != "buried"} - self.visited - {self.target}
        self.passing = {s: t for s, t in self.passing.items() if s in near}
        for s in near:
            if now - self.passing.setdefault(s, now) >= PASS_S:
                self.deal(s, False, now, "passed")
        # reached the target
        if self.target is not None:
            tgt = tuple(xy[self.target])
            if dist(player, tgt) * M <= arrive_radius(tgt, self.last_reached):
                self.near_since = now if self.near_since is None else self.near_since
                if now - self.near_since >= ARRIVE_S:
                    self.deal(self.target, True, now, "reached")
            else:
                self.near_since = None
        # plan
        old = self.target
        if self.tour:
            started = time.monotonic()
            order, rerouted = self.tour.plan(player, self.visited, now)
            ms = (time.monotonic() - started) * 1000
            self.tick_ms.append(ms)
            if rerouted or old is None:
                self.plan_ms.append(ms)
            new = order[0] if order else None
            if new is not None and new == self.tour.detour and new != old:
                self.events.append((now, "nearby", old, new))
        else:
            if old is not None and now - self.last_plan < PLAN_EVERY:
                return
            started = time.monotonic()
            allow = now - self.last_switch >= HOLD_S
            order, _, switched = self.base.plan(player, self.visited, old, allow_switch=allow)
            self.plan_ms.append((time.monotonic() - started) * 1000)
            self.last_plan = now
            new = order[0] if order else None
        if new != old and new is not None:
            self.first_stop_m.append(float(np.hypot(*(xy[new] - np.asarray(player))) * M))
        if new != old:
            if old is not None:
                self.last_switch = now
                self.events.append((now, "switch", old, new))
            self.target = new
            self.near_since = None
        if self.target is not None:
            d = np.hypot(*(xy - np.asarray(player)).T) * M
            tgt = self.target
            if d[tgt] <= 10.0:
                return            # the arrow already points at a chest he's next to (clusters): not "ignoring" one
            straight = d[tgt] / params.RUN_SPEED
            for c in np.flatnonzero(d <= 8.0):
                c = int(c)
                if c != tgt and c not in self.visited:
                    self.ignored.append((now, c, round(float(d[c]), 1),
                                         round(float(d[c] / params.RUN_SPEED + self.base.T[c, tgt] - straight), 1)))


def displacement(history, now, window):
    """Metres between his position ``window`` seconds ago and now (max over that window)."""
    past = [p for t, p in history if now - window <= t <= now]
    if len(past) < 2:
        return 0.0
    return max(dist(past[0], p) for p in past) * M


def summarise(arm, history, seconds):
    nearby = {(e[0], e[3]) for e in arm.events if e[1] == "nearby"}
    switches = [e for e in arm.events if e[1] == "switch" and (e[0], e[3]) not in nearby]   # detours counted apart
    still = [e for e in switches if displacement(history, e[0], 3.0) < 5.0]
    minutes = seconds / 60
    ms = np.asarray(arm.plan_ms) if arm.plan_ms else np.zeros(1)
    out = {"switches": len(switches), "switches_per_min": round(len(switches) / minutes, 2),
           "switches_moving_under_5m": len(still), "still_switches_per_min": round(len(still) / minutes, 2),
           "reached": sum(e[1] == "reached" for e in arm.events),
           "passed": sum(e[1] == "passed" for e in arm.events),
           "plans": len(arm.plan_ms), "plan_ms_p50": round(float(np.median(ms)), 1),
           "plan_ms_p95": round(float(np.percentile(ms, 95)), 1), "plan_ms_max": round(float(ms.max()), 1)}
    spots = {}
    for t, c, m, detour in arm.ignored:
        spots.setdefault(c, []).append((t, m, detour))
    out["ignored_spots"] = len(spots)                      # distinct unopened spots he was within 8 m of, arrow elsewhere
    out["ignored_fixes"] = len(arm.ignored)
    out["ignored_detail"] = [{"spot": c, "kind": arm.base.kinds[c], "first_t": round(v[0][0], 1), "fixes": len(v),
                              "closest_m": min(x[1] for x in v), "detour_s_min": min(x[2] for x in v)}
                             for c, v in spots.items()]
    if arm.tour:
        out["solves"] = [(k, round(v), n) for k, v, n in arm.tour.solves]
        out["reroutes"] = len(arm.tour.reroutes)
        out["reroutes_per_min"] = round(len(arm.tour.reroutes) / minutes, 2)
        tick = np.asarray(arm.tick_ms) if arm.tick_ms else np.zeros(1)
        out["tick_ms_p50"], out["tick_ms_p95"] = round(float(np.median(tick)), 1), round(float(np.percentile(tick, 95)), 1)
        out["extend_ms"] = [round(ms) for _, ms, _ in getattr(arm.tour, "extends", [])][:20]
        out["reroute_detail"] = [{"t": round(t, 1), "reason": why, "moved_10s_m": round(displacement(history, t, 10.0))}
                                 for t, why, _ in arm.tour.reroutes]
        out["extends"] = len(getattr(arm.tour, "extends", []))
        out["first_stop_m"] = [round(m) for m in arm.first_stop_m[:12]]
        out["nearby_detours"] = sum(k == "nearby" for _, k, _ in arm.tour.log)
        out["detours_dropped"] = sum(k == "dropped" for _, k, _ in arm.tour.log)
        drops = {round(t, 3) for t, k, _ in arm.tour.log if k == "dropped"}
        reroute_t = {round(t, 3) for t, _, _ in arm.tour.reroutes}
        out["switch_causes"] = {"reroute": sum(round(e[0], 3) in reroute_t for e in switches),
                                "detour dropped": sum(round(e[0], 3) in drops for e in switches)}
    return out


def replay(paths, base, terrain):
    results = {}
    for path in paths:
        rows = json.loads(Path(path).read_text())
        fixes = [(r["t"], tuple(r["position"])) for r in rows if r.get("position") and r.get("position_update")]
        if not fixes:
            fixes = [(r["t"], tuple(r["position"])) for r in rows if r.get("position")]
        dedup = []
        for t, p in fixes:
            if not dedup or p != dedup[-1][1]:
                dedup.append((t, p))
        seconds = dedup[-1][0] - dedup[0][0]
        arms = [Arm(name, base, terrain) for name in PLANNERS]
        history = []
        for t, p in dedup:
            history.append((t, p))
            for arm in arms:
                arm.step(p, t)
        moved = sum(dist(a, b) for (_, a), (_, b) in zip(dedup, dedup[1:])) * M
        results[Path(path).name] = {"seconds": round(seconds, 1), "fixes": len(dedup), "walked_m": round(moved),
                                    **{arm.name: summarise(arm, history, seconds) for arm in arms}}
        print(Path(path).name, json.dumps(results[Path(path).name]), flush=True)
    return results


# ---------------------------------------------------------------------------
# Simulated player
# ---------------------------------------------------------------------------

def walk_path(terrain, a, b):
    """Polyline from a to b and the seconds it takes on the terrain graph."""
    cells, seconds = terrain.graph.dijkstra(cell_of(*a), cell_of(*b))
    pts = [((c + 0.5) * params.CELL_PX, (r + 0.5) * params.CELL_PX) for r, c in cells]
    line = [tuple(a)] + pts[1:-1] + [tuple(b)] if len(pts) >= 2 else [tuple(a), tuple(b)]
    length = sum(dist(p, q) for p, q in zip(line, line[1:]))
    straight = dist(a, b) * M / params.RUN_SPEED
    return line, max(seconds, straight), length


def simulate(name, base, terrain, start, seconds=600, dt=0.5, wander=0.0, seed=0, noise_m=1.2):
    rng = random.Random(seed)
    arm = Arm(name, base, terrain)
    pos = tuple(start)
    goal = line = None
    speed = 0.0
    stop_left = 0.0
    own_goal = False
    history = []
    opened = 0
    opened_at = []
    t = 0.0
    while t < seconds:
        seen = (pos[0] + rng.gauss(0, noise_m / M), pos[1] + rng.gauss(0, noise_m / M))
        history.append((t, seen))
        arm.step(seen, t)
        if stop_left > 0:
            stop_left -= dt
            t += dt
            continue
        close = goal is not None and dist(pos, tuple(base.xy[goal])) * M <= ARRIVE_M
        if not own_goal and arm.target != goal and not close:   # he finishes the last few metres to a chest he's at
            goal = arm.target
            line = None
        if goal is None:
            t += dt
            continue
        if line is None:
            line, secs, length = walk_path(terrain, pos, tuple(base.xy[goal]))
            speed = length / secs if secs > 0 else 1.0   # map px per second along this leg
        # move along the polyline
        left = speed * dt
        while left > 0 and len(line) > 1:
            step = dist(line[0], line[1])
            if step <= left:
                left -= step
                line = line[1:]
            else:
                f = left / step
                line[0] = (line[0][0] + (line[1][0] - line[0][0]) * f, line[0][1] + (line[1][1] - line[0][1]) * f)
                left = 0
        pos = line[0]
        if len(line) == 1:       # at the goal: open it
            stop_left = params.CHEST_STOP_S
            if goal not in arm.visited:
                if goal == arm.target:
                    arm.deal(goal, True, t, "reached")
                else:
                    arm.deal(goal, True, t, "found")
            opened += 1
            opened_at.append(t)
            line = None
            own_goal = False
            goal = None
            if wander and rng.random() < wander:
                d = np.hypot(*(base.xy - np.asarray(pos)).T)
                for i in np.argsort(d):
                    i = int(i)
                    if i not in arm.visited and i != arm.target and base.kinds[i] != "buried":
                        goal, own_goal = i, True
                        break
        t += dt
    out = summarise(arm, history, seconds)
    out["opened"] = opened
    out["opened_2_5_10"] = [sum(x <= m * 60 for x in opened_at) for m in (2, 5, 10)]
    return out


def drift(base, terrain, pairs=120, seed=3, noise_m=1.2):
    """His worry, staged: stand between two chests 25-50 m apart and drift from 35% to 65% of the way toward
    the other one, 0.5 m per second (wobbling in place, not leaving). Count how often each arrow changes chest."""
    rng = random.Random(seed)
    land = [i for i, k in enumerate(base.kinds) if k != "buried"]
    xy = base.xy
    found = []
    while len(found) < pairs:
        a = rng.choice(land)
        d = np.hypot(*(xy - xy[a]).T) * M
        options = [int(j) for j in np.flatnonzero((d >= 25) & (d <= 50)) if base.kinds[j] != "buried"]
        if options:
            found.append((a, rng.choice(options)))
    out = {}
    for name in PLANNERS:
        changes, flipped = [], 0
        for k, (a, b) in enumerate(found):
            arm = Arm(name, base, terrain)
            noise = random.Random(k)
            targets = []
            for step in range(61):                       # 30 m of drift at most, 0.5 m/s
                f = 0.35 + 0.30 * step / 60
                p = xy[a] + (xy[b] - xy[a]) * f
                seen = (p[0] + noise.gauss(0, noise_m / M), p[1] + noise.gauss(0, noise_m / M))
                arm.step(seen, float(step))
                targets.append(arm.target)
            # only real switches: the old target is still unopened (25+ m pairs keep him out of the 8 m / 6 m rules)
            n = sum(e[1] == "switch" for e in arm.events)
            changes.append(n)
            flipped += n > 0
        out[name] = {"pairs": len(found), "pairs_with_a_change": flipped,
                     "pct_pairs_changed": round(100 * flipped / len(found), 1),
                     "changes_total": int(sum(changes)), "changes_max": int(max(changes))}
        print(name, json.dumps(out[name]), flush=True)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("replay", "sim", "drift"))
    parser.add_argument("traces", nargs="*")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--starts", type=int, default=6)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--planners", default="now,frozen", help="Comma list of now, frozen, tour")
    args = parser.parse_args()
    global PLANNERS
    PLANNERS = args.planners.split(",")
    terrain = LegPather(planner_source.MAP_IMAGE, planner_source.MAP_SIZE)
    base = Planner(terrain)
    if args.mode == "replay":
        result = replay(args.traces, base, terrain)
    elif args.mode == "drift":
        result = drift(base, terrain)
    else:
        rng = random.Random(7)
        land = [i for i, k in enumerate(base.kinds) if k != "buried"]
        starts = [tuple(base.xy[i] + 3) for i in rng.sample(land, args.starts)]
        result = {"starts": [list(map(float, s)) for s in starts], "runs": []}
        for wander in (0.0, 0.2):
            for k, start in enumerate(starts):
                for name in PLANNERS:
                    r = simulate(name, base, terrain, start, seconds=args.minutes * 60, wander=wander, seed=k)
                    r.update({"planner": name, "start": k, "wander": wander})
                    result["runs"].append(r)
                    print(json.dumps({key: r[key] for key in ("planner", "start", "wander", "opened_2_5_10",
                                                              "switches_per_min", "plan_ms_p50", "plan_ms_p95")}),
                          flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
