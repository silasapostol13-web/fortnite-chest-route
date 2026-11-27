"""Full-map chest route: one tour through every unopened chest spot, followed like a maps app.

PROTOTYPE beside ``replan.py`` (2026-11-27). Not the live default.

``replan.Planner`` asks every second "which chests open the most in the next 2 minutes?" over ~45 nearby
spots, so two near-equal answers can trade places while he stands still. This module instead answers once
"what is the shortest way to open every chest spot from here?" (an open travelling-salesman path over ~1,000
spots), then just follows that order. It re-plans only when:

* he clearly leaves the route: more than ``off_meters`` from the path to his current target for
  ``off_seconds`` (a maps app's "off-route" check), or
* he opens/checks a chest that isn't one of the next few stops (he went his own way).

Reaching the target just moves to the next stop; nothing is re-solved.

Solver: nearest neighbour, then 2-opt and Or-opt (move 1-3 stops elsewhere, either way round) until neither
helps. Vectorised with numpy. A re-plan warm-starts from the old order, so it stays close to what he saw.
Travel times are the same Dijkstra-on-terrain seconds ``replan.py`` uses (``chest_matrix``).
"""

from __future__ import annotations

from math import dist
from pathlib import Path
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from route import params  # noqa: E402
from replan import Planner  # noqa: E402


# ---------------------------------------------------------------------------
# Open-path TSP from a fixed start (node 0) with a free end.
# D is symmetric with an extra last row/column of zeros (a dummy end), so the
# path is [0, ..., dummy] with both ends fixed and plain 2-opt / Or-opt apply.
# ---------------------------------------------------------------------------

def _matrix(first_leg, T, nodes):
    n = len(nodes)
    D = np.zeros((n + 2, n + 2))
    D[1:n + 1, 1:n + 1] = T[np.ix_(nodes, nodes)]
    D[0, 1:n + 1] = D[1:n + 1, 0] = first_leg[nodes]
    return D


def nearest_neighbour(D):
    n = len(D) - 2
    left = np.ones(n + 2, bool)
    left[0] = left[-1] = False
    path, here = [0], 0
    for _ in range(n):
        row = np.where(left, D[here], np.inf)
        here = int(row.argmin())
        path.append(here)
        left[here] = False
    return path + [n + 1]


def path_cost(D, path):
    p = np.asarray(path)
    return float(D[p[:-1], p[1:]].sum())


def two_opt(D, path, deadline):
    p = np.asarray(path)
    L = len(p)
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for i in range(1, L - 2):
            a, b = p[i - 1], p[i]
            c, d = p[i + 1:L - 1], p[i + 2:L]          # j = i+1 .. L-2
            delta = D[a, c] + D[b, d] - D[a, b] - D[c, d]
            k = int(delta.argmin())
            if delta[k] < -1e-9:
                j = i + 1 + k
                p[i:j + 1] = p[i:j + 1][::-1].copy()
                improved = True
    return p.tolist()


def or_opt(D, path, deadline, max_seg=3):
    p = list(path)
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for s in range(1, max_seg + 1):
            i = 1
            while i + s < len(p) and time.monotonic() < deadline:   # p[i+s] exists, so seg never holds the dummy end
                seg = p[i:i + s]
                prev, nxt = p[i - 1], p[i + s]
                gain = D[prev, seg[0]] + D[seg[-1], nxt] - D[prev, nxt]
                rest = np.asarray(p[:i] + p[i + s:])
                a, b = rest[:-1], rest[1:]                 # insert between a[k] and b[k]
                fwd = D[a, seg[0]] + D[seg[-1], b] - D[a, b]
                rev = D[a, seg[-1]] + D[seg[0], b] - D[a, b]
                kf, kr = int(fwd.argmin()), int(rev.argmin())
                best, k, flip = (fwd[kf], kf, False) if fwd[kf] <= rev[kr] else (rev[kr], kr, True)
                if best < gain - 1e-9:
                    ins = seg[::-1] if flip else seg
                    rest = rest.tolist()
                    p = rest[:k + 1] + ins + rest[k + 1:]
                    improved = True
                else:
                    i += 1
    return p


def improve(D, path, seconds=2.0):
    deadline = time.monotonic() + seconds
    before = path_cost(D, path)
    while time.monotonic() < deadline:
        path = two_opt(D, path, deadline)
        path = or_opt(D, path, deadline)
        after = path_cost(D, path)
        if after >= before - 1e-9:
            break
        before = after
    return path


def solve(first_leg, T, nodes, warm=None, seconds=2.0):
    """Order of ``nodes`` (chest indices) from the player. ``warm``: previous order to start from."""
    nodes = list(nodes)
    if not nodes:
        return [], 0.0
    D = _matrix(first_leg, T, nodes)
    if warm:
        pos = {c: i + 1 for i, c in enumerate(nodes)}
        kept = [pos[c] for c in warm if c in pos]
        missing = sorted(set(range(1, len(nodes) + 1)) - set(kept))
        path = [0] + kept + missing + [len(nodes) + 1]
        # the start moved: keep the old order and let 2-opt / Or-opt repair it from the new start
        path = improve(D, path, seconds)
    else:
        path = improve(D, nearest_neighbour(D), seconds)
    order = [nodes[i - 1] for i in path[1:-1]]
    return order, path_cost(D, path)


def mst_cost(D):
    """Minimum spanning tree weight (Prim). An open path through every node is a spanning tree, so the
    optimal route can't be shorter than this: route/MST bounds how far from optimal we are."""
    n = len(D)
    inside = np.zeros(n, bool)
    best = D[0].copy()
    inside[0] = True
    total = 0.0
    for _ in range(n - 1):
        cand = np.where(inside, np.inf, best)
        j = int(cand.argmin())
        total += cand[j]
        inside[j] = True
        best = np.minimum(best, D[j])
    return float(total)


# ---------------------------------------------------------------------------
# Following the tour (the maps-app part)
# ---------------------------------------------------------------------------

def distance_to_path(point, path):
    """Metres from ``point`` to the polyline ``path`` (map pixels in, metres out)."""
    if not path:
        return float("inf")
    if len(path) == 1:
        return dist(point, path[0]) * params.METERS_PER_PX
    P = np.asarray(path, float)
    a, b = P[:-1], P[1:]
    ab = b - a
    length2 = (ab ** 2).sum(1)
    t = np.clip(((np.asarray(point) - a) * ab).sum(1) / np.where(length2 > 0, length2, 1), 0, 1)
    nearest = a + ab * t[:, None]
    return float(np.hypot(*(nearest - point).T).min() * params.METERS_PER_PX)


class TourPlanner:
    """Same inputs as ``replan.Planner.plan``; keeps one full-map order and only re-solves on leaving it."""

    def __init__(self, base: Planner, terrain, off_meters=25.0, off_seconds=3.0, near_stops=3,
                 solve_seconds=2.0, reroute_seconds=2.0, nearby_meters=10.0, nearby_detour_s=6.0):
        self.base, self.terrain = base, terrain
        self.nearby_meters, self.nearby_detour_s = nearby_meters, nearby_detour_s
        self.detour = None          # a chest slotted in first because he's right next to it ("CHEST NEARBY")
        self.detour_home = None     # where it sat in the route, to put it back if he walks away from it
        self.reroutes = []          # (now, reason, player) for every re-plan after the first
        self.log = []               # (now, kind, spot): "nearby" detours and "dropped" ones he walked away from
        self.off_meters, self.off_seconds, self.near_stops = off_meters, off_seconds, near_stops
        self.solve_seconds, self.reroute_seconds = solve_seconds, reroute_seconds
        self.order = []
        self.leg_path = None
        self.leg_target = None
        self.off_since = None
        self.reroute_reason = None
        self.solves = []   # (kind, ms, stops)

    def _solve(self, player, visited, warm, reason="start", now=None):
        if warm:
            self.reroutes.append((now, reason, tuple(player)))
        self.detour = self.detour_home = None
        started = time.monotonic()
        times = self.base.player_times(player)
        nodes = [i for i in range(len(self.base.xy)) if i not in visited and np.isfinite(times[i])]
        order, _ = solve(times, self.base.T, nodes, warm=warm,
                         seconds=self.reroute_seconds if warm else self.solve_seconds)
        self.solves.append(("reroute" if warm else "full", (time.monotonic() - started) * 1000, len(order)))
        return order

    def mark(self, spot):
        """Kept for callers; ``plan`` sees dealt spots in ``visited`` and decides about re-planning there."""

    def plan(self, player, visited, now, pin=None):
        """Return (order, rerouted). Cheap unless a re-plan is due. (``pin`` is handled by ``frozen.py``;
        this prototype leaves it to ``live.LiveRoute``.)"""
        # A spot dealt with anywhere on the list (reached, opened or walked past) just comes off it. Walking past
        # one is not a reason to re-plan; a real side trip shows up as being off the route line instead.
        before = self.order[0] if self.order else None
        self.order = [s for s in self.order if s not in visited]
        rerouted = False
        if not self.order:
            self.order = self._solve(player, visited, warm=None)
            rerouted = True
        elif self.reroute_reason:
            self.order = self._solve(player, visited, warm=self.order, reason=self.reroute_reason, now=now)
            rerouted = True
        else:
            target = self.order[0]
            if self.leg_target != target:
                self.leg_target = target
                self.leg_path = self.terrain.path(player, tuple(self.base.xy[target]))
                self.off_since = None
            off = distance_to_path(player, self.leg_path)
            if pin is None and off > self.off_meters:     # never re-plan under a Back pin he chose
                self.off_since = now if self.off_since is None else self.off_since
                if now - self.off_since >= self.off_seconds:
                    self.order = self._solve(player, visited, warm=self.order, reason="off route", now=now)
                    rerouted = True
            else:
                self.off_since = None
        if not rerouted and self.order:
            self._nearby(player, now)
        if rerouted:
            self.reroute_reason = None
            self.leg_target = None
            if self.order:
                self.leg_target = self.order[0]
                self.leg_path = self.terrain.path(player, tuple(self.base.xy[self.order[0]]))
            self.off_since = None
        # REROUTING only when the arrow's chest actually changed
        return self.order, rerouted and before is not None and bool(self.order) and self.order[0] != before

    def _nearby_ok(self, spot):
        """Which spots may be slotted in as CHEST NEARBY: the tour holds every spot, so any still on it."""
        return spot in self.order

    def _seconds_along(self, player, path):
        """Rough seconds left along ``path`` from the point on it nearest the player (running speed)."""
        if not path or len(path) < 2:
            return 0.0
        P = np.asarray(path, float)
        k = int(np.hypot(*(P - np.asarray(player)).T).argmin())
        rest = np.hypot(*np.diff(P[k:], axis=0).T).sum() + dist(player, P[k])
        return float(rest * params.METERS_PER_PX / params.RUN_SPEED)

    def _nearby(self, player, now=None):
        """If an unopened chest spot is within ``nearby_meters`` and going there first costs at most
        ``nearby_detour_s`` extra, make it the next stop (cheapest insertion at the front, no re-solve).
        Walking away from a nearby chest (twice the radius) puts it back where it was."""
        xy, here = self.base.xy, np.asarray(player)
        d = np.hypot(*(xy - here).T) * params.METERS_PER_PX
        if self.detour is not None:
            if self.order and self.order[0] == self.detour:
                away = d[self.detour]
                if away <= self.nearby_meters:
                    return                                    # still on his way to the nearby chest
                if away <= 2 * self.nearby_meters and not any(
                        d[i] <= self.nearby_meters and i != self.detour and self._nearby_ok(i) for i in np.argsort(d)[:8]):
                    return                                    # drifting, nothing closer: keep it
                spot = self.order.pop(0)                      # walked away, or another chest is right next to him
                if self.detour_home is not None:              # back where it was (one not on the plan just goes)
                    self.order.insert(min(self.detour_home, len(self.order)), spot)
                self.log.append((now, "dropped", spot))
            self.detour = self.detour_home = None
            self.leg_target = None
        close = [int(i) for i in np.argsort(d)[:8] if d[i] <= self.nearby_meters]
        target = self.order[0]
        close = [i for i in close if i != target and self._nearby_ok(i)]
        if not close:
            return
        if self.leg_target != target or self.leg_path is None:
            self.leg_target = target
            self.leg_path = self.terrain.path(player, tuple(xy[target]))
        to_target = self._seconds_along(player, self.leg_path)
        best, cost = None, self.nearby_detour_s
        for c in close:
            via = d[c] / params.RUN_SPEED + self.base.T[c, target] - to_target
            if via <= cost:
                best, cost = c, via
        if best is not None:
            self.detour_home = self.order.index(best) if best in self.order else None
            if best in self.order:
                self.order.remove(best)
            self.order.insert(0, best)
            self.detour = best
            self.log.append((now, "nearby", best))
            self.leg_target = best
            self.leg_path = self.terrain.path(player, tuple(xy[best]))
            self.off_since = None


class TourWorker:
    """``TourPlanner`` in a background thread, with the same submit/latest/close interface as
    ``replan.LivePlanner`` so ``live.LiveRoute`` can use either. A reroute (0.3-0.8 s) never blocks a frame."""

    def __init__(self, tour: TourPlanner, every=0.2):
        self.tour, self.every = tour, every
        self.lock = threading.Condition()
        self.request = None
        self.result = None  # (order, seconds, rerouted, solve_ms, position)
        self.sequence = 0
        self.stopped = False
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def submit(self, player, visited, current, force=False, hold=False):
        with self.lock:
            self.request = (tuple(player), frozenset(visited), force, current if hold else None)
            self.lock.notify()

    def _loop(self):
        last = float("-inf")
        while True:
            with self.lock:
                while not self.stopped and (self.request is None or
                                            (not self.request[2] and time.monotonic() - last < self.every)):
                    self.lock.wait(timeout=0.05)
                if self.stopped:
                    return
                player, visited, _, pin = self.request
                self.request = None
            started = time.monotonic()
            before = list(self.tour.order)
            order, rerouted = self.tour.plan(player, set(visited), started, pin=pin)
            last = time.monotonic()
            if order == before and not rerouted:
                continue                       # nothing new to publish
            with self.lock:
                self.result = (list(order), 0.0, rerouted, (last - started) * 1000, player)
                self.sequence += 1

    def latest(self):
        with self.lock:
            return self.sequence, self.result

    def close(self):
        with self.lock:
            self.stopped = True
            self.lock.notify()
        self.worker.join(timeout=2)
