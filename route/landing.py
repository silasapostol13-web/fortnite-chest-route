"""Where to land: for a battle bus path, which drop opens the most chests.

Model (numbers in params.py, most are guesses):
* The bus flies a straight line at BUS_SPEED. Game clock 0 = bus at the start of the line.
* You can land on any chest within MAX_DROP_REACH_M of the line. Landing time =
  jump time + FALL_BASE_S + sideways distance / GLIDE_SPEED. You jump a bit early
  and glide diagonally when that is faster (the bus outruns your glide).
* Loot time = when the first storm starts closing - when you land.
  Or pass ``fixed_budget`` to give every landing the same N seconds.
Every reachable chest is screened with the cheap nearest-neighbour route, then
the best ``refine`` landings get the full iterated local search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, sqrt

import numpy as np

from . import params as P
from .orienteering import ils_best, nearest_neighbor


@dataclass
class BusPath:
    start: tuple  # logical map pixels
    end: tuple

    def length_m(self):
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1]) * P.METERS_PER_PX


def land_time(bus: BusPath, xy):
    """Seconds after the bus starts until you are on the ground at xy, or None if out of reach."""
    (x0, y0), (x1, y1) = bus.start, bus.end
    vx, vy = x1 - x0, y1 - y0
    seg = hypot(vx, vy)
    ux, uy = vx / seg, vy / seg
    px, py = xy[0] - x0, xy[1] - y0
    along = (px * ux + py * uy) * P.METERS_PER_PX       # metres along the bus line
    side = abs(px * uy - py * ux) * P.METERS_PER_PX      # metres off the line
    k = P.GLIDE_SPEED / P.BUS_SPEED
    lead = k * side / sqrt(1 - k * k)                    # jump this far before the closest point
    jump = min(max(along - lead, 0.0), bus.length_m())
    glide = hypot(along - jump, side)
    if glide > P.MAX_DROP_REACH_M:
        return None
    return jump / P.BUS_SPEED + P.FALL_BASE_S + glide / P.GLIDE_SPEED


@dataclass
class Landing:
    chest: int
    land_s: float
    budget_s: float
    route: list = field(default_factory=list)
    route_s: float = 0.0
    naive_count: int = 0


def best_landing(T, xy, bus: BusPath, fixed_budget=None, refine=12, iters=200, seed=0):
    """Return (best Landing, all screened Landings sorted best-first)."""
    n = len(xy)
    screened = []
    for i in range(n):
        lt = land_time(bus, xy[i])
        if lt is None:
            continue
        budget = fixed_budget if fixed_budget is not None else P.STORM1_CLOSES_S - lt
        if budget < P.CHEST_STOP_S:
            continue
        cand = np.nonzero(T[i] + P.CHEST_STOP_S <= budget)[0].tolist()
        route, rt = nearest_neighbor(T, i, cand, budget)
        screened.append(Landing(i, lt, budget, route, rt, naive_count=len(route)))
    screened.sort(key=lambda L: (-len(L.route), L.route_s))
    for L in screened[:refine]:
        cand = np.nonzero(T[L.chest] + P.CHEST_STOP_S <= L.budget_s)[0].tolist()
        route, rt = ils_best(T, L.chest, cand, L.budget_s, iters=iters, seed=seed)
        if len(route) > len(L.route) or (len(route) == len(L.route) and rt < L.route_s):
            L.route, L.route_s = route, rt
    top = sorted(screened[:refine], key=lambda L: (-len(L.route), L.route_s))
    return (top[0] if top else None), top + screened[refine:]
