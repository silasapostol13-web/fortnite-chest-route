"""Live re-planning of the whole chest route from wherever the player is right now.

Every update (about once a second) this answers: starting from this spot, which
unopened chests, in what order, open the most chests in the next ``budget``
seconds? That is the orienteering problem; ``route.orienteering.ils_best`` solves
it near-optimally. Travel times come from the same terrain graph and Dijkstra the
arrow uses (land runs, water swims):

* chest-to-chest times: one cached matrix over every chest spot on the map
  (time-limited Dijkstra from each spot, then Floyd-Warshall), built once;
* player-to-chest times: a fresh time-limited Dijkstra from the player's square
  on every re-plan, extended through the matrix to chests farther away.

A small hysteresis keeps the current target unless the new plan opens more
chests or saves real time, so the arrow doesn't flip between two equal choices.

Not every spot spawns a chest, so by default (``weighted=True``) each spot counts as
its spawn chance (``params.SPAWN_P`` by kind: guaranteed 1, regular / buried less) and
the plan maximises EXPECTED chests, which sends him to sure chests first.
``weighted=False`` is the old count-every-spot-as-1 planner.
"""

from __future__ import annotations

import csv
import hashlib
from math import dist
from pathlib import Path
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from route import params, planner_source  # noqa: E402
from route.orienteering import ils_best, route_prize, route_time  # noqa: E402
from route.travel import cell_of, compute_travel_matrix, dijkstra_within  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
SPOT_TYPES = ("regular", "guaranteed", "guaranteed_rare", "buried")


def load_spots(types=SPOT_TYPES):
    """Every chest spot of the given types: (xy, kinds). Buried chests are included because the film
    route is mostly buried treasure; ``planner_source.load_spawns`` keeps only regular and guaranteed."""
    width, height = planner_source.MAP_SIZE
    by_position = {}
    with (planner_source.PLANNER_DIR / "chest_spawns.csv").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["type"] in types:
                xy = float(row["x_percent"]) * width / 100, float(row["y_percent"]) * height / 100
                by_position.setdefault(xy, row["type"])
    return np.array(list(by_position), dtype=float), list(by_position.values())


def chest_matrix(terrain, xy):
    """Seconds between every pair of chest spots on the live terrain graph (cached)."""
    water = np.ascontiguousarray(terrain.cell_water, dtype=bool)
    key = hashlib.sha1(water.tobytes() + xy.tobytes() + repr((
        params.METERS_PER_PX, params.CELL_PX, params.RUN_SPEED, params.SWIM_SPEED, "live-v1")).encode()).hexdigest()[:12]
    path = CACHE_DIR / f"live_chests_{key}.npy"
    if path.exists():
        return np.load(path)
    started = time.monotonic()
    print(f"Building chest travel times for {len(xy)} spots (one time, cached)...", flush=True)
    T = compute_travel_matrix(xy, terrain.graph)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, T)
    print(f"Chest travel times ready in {time.monotonic() - started:.0f} s.", flush=True)
    return T


class Planner:
    """Computes the best chest order from a position. Pure and synchronous."""

    def __init__(self, terrain, budget=120.0, pool=45, reach=75.0, iters=30,
                 switch_seconds=4.0, spots=None, weighted=True, weight_power=1.0):
        self.xy, self.kinds = spots if spots is not None else load_spots()
        self.weighted = weighted
        # expected chests per spot (spawn chance by kind); all 1 = the old objective. weight_power < 1 softens it
        # (p ** power: 0 = count every spot, 1 = pure expected chests).
        self.prize = np.array([params.SPAWN_P.get(k, params.RANDOM_SPAWN_P) ** weight_power if weighted else 1.0
                               for k in self.kinds])
        self.graph = terrain.graph
        self.cells = [cell_of(x, y) for x, y in self.xy]
        self.T = chest_matrix(terrain, self.xy)
        self.budget, self.pool, self.reach, self.iters = budget, pool, reach, iters
        self.switch_seconds = switch_seconds
        self.stop = params.CHEST_STOP_S

    def player_times(self, player):
        """Seconds from the player to every chest spot (inf if unreachable)."""
        reached = dijkstra_within(self.graph, cell_of(*player), self.reach)
        direct = np.full(len(self.xy), np.inf)
        for i, cell in enumerate(self.cells):
            t = reached.get(cell)
            if t is not None:
                straight = dist(player, self.xy[i]) * params.METERS_PER_PX / params.RUN_SPEED
                direct[i] = max(t, straight)
        hubs = np.flatnonzero(np.isfinite(direct))
        if hubs.size == 0:
            return direct
        via = (direct[hubs, None] + self.T[hubs]).min(axis=0)
        return np.minimum(direct, via)

    def _solve(self, times, cands, first=None):
        """Best order over ``cands``. With ``first`` (an index into cands) that chest is forced to be stop one:
        solve from the chest itself with the budget left after reaching it. (Masking the player's other
        edges instead made ``ils_best`` drop every other candidate, since its pool needs a finite first leg.)"""
        if first is not None:
            current = cands[first]
            rest = [c for c in cands if c != current]
            left = self.budget - times[current]
            if left < 0 or not rest:
                return [current], float(times[current] + self.stop)
            nodes = [current] + rest
            M = self.T[np.ix_(nodes, nodes)].copy()
            np.fill_diagonal(M, 0.0)
            order, _ = ils_best(M, 0, list(range(1, len(nodes))), left + self.stop, self.stop,
                                iters=self.iters, seed=0, prize=self.prize[nodes] if self.weighted else None)
            order = order or [0]
            return [nodes[i] for i in order], float(times[current] + route_time(M, order, self.stop))
        n = len(cands)
        M = np.full((n + 1, n + 1), np.inf)
        M[0, 1:] = times[cands]
        M[1:, 1:] = self.T[np.ix_(cands, cands)]
        np.fill_diagonal(M, 0.0)
        # route_time counts a stop at node 0 (the player); add it back to the budget.
        prize = np.concatenate([[0.0], self.prize[cands]]) if self.weighted else None   # node 0 = the player
        order, _ = ils_best(M, 0, list(range(1, n + 1)), self.budget + self.stop, self.stop,
                            iters=self.iters, seed=0, prize=prize)
        order = [cands[i - 1] for i in order[1:]]
        seconds = route_time(M, [0] + [1 + list(cands).index(c) for c in order], self.stop) - self.stop
        return order, seconds

    def plan(self, player, visited, current=None, allow_switch=True):
        """Return (order, seconds, switched). ``order`` is chest-spot indices, best first.

        With ``allow_switch`` False the current target stays first (used for a few seconds after a switch,
        so two near-equal plans can't make the arrow flicker)."""
        times = self.player_times(player)
        open_ = np.array([i for i in np.argsort(times)[: self.pool * 3]
                          if i not in visited and np.isfinite(times[i])], dtype=int)[: self.pool]
        if open_.size == 0:
            return [], 0.0, False
        cands = list(map(int, open_))
        if current is not None and current not in visited and np.isfinite(times[current]) and current not in cands:
            cands.append(int(current))
        best, best_t = self._solve(times, cands)
        if current is None or current in visited or not best or best[0] == current or current not in cands:
            return best, best_t, bool(best) and best[0] != current
        kept, kept_t = self._solve(times, cands, first=cands.index(current))
        # switch for at least half a chest more (unweighted: one more chest), or as many in switch_seconds less time
        gain = route_prize(best, self.prize) - route_prize(kept, self.prize)
        if allow_switch and (gain > 0.5 or (gain > -1e-9 and best_t < kept_t - self.switch_seconds)):
            return best, best_t, True
        return kept, kept_t, False


class LivePlanner:
    """Runs Planner in a background thread on the newest position, about every ``every`` seconds."""

    def __init__(self, planner, every=1.0, hold=3.0):
        self.planner, self.every, self.hold = planner, every, hold
        self.last_switch = float("-inf")
        self.lock = threading.Condition()
        self.request = None
        self.result = None  # (order, seconds, switched, solve_ms, position)
        self.sequence = 0
        self.stopped = False
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def submit(self, player, visited, current, force=False, hold=False):
        """Queue a re-plan from ``player``. ``hold`` keeps ``current`` first (the player asked for it)."""
        with self.lock:
            self.request = (tuple(player), frozenset(visited), current, force, hold)
            self.lock.notify()

    def _loop(self):
        last = float("-inf")
        while True:
            with self.lock:
                while not self.stopped and (self.request is None or
                                            (not self.request[3] and time.monotonic() - last < self.every)):
                    self.lock.wait(timeout=0.05)
                if self.stopped:
                    return
                player, visited, current, _, hold = self.request
                self.request = None
            started = time.monotonic()
            allow = not hold and time.monotonic() - self.last_switch >= self.hold
            order, seconds, switched = self.planner.plan(player, visited, current, allow_switch=allow)
            last = time.monotonic()
            if switched:
                self.last_switch = last
            with self.lock:
                self.result = (order, seconds, switched, (last - started) * 1000, player)
                self.sequence += 1

    def latest(self):
        with self.lock:
            return self.sequence, self.result

    def close(self):
        with self.lock:
            self.stopped = True
            self.lock.notify()
        self.worker.join(timeout=2)
