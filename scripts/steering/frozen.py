"""Frozen orienteering: plan the most chests in the next ~2 minutes ONCE, then follow it like a maps app.

``replan.Planner`` re-solves every second, so two near-equal plans can trade places while he stands between two
chests. ``tour.py`` (one route through all ~1,000 spots) fixed that but opened ~10% fewer chests, because a full tour
must visit every outlier. This keeps the orienteering objective (nearby, dense chests first) and freezes it:

* Reaching / passing a stop just moves on to the next one. Walking past any other spot drops it silently.
* Finishing the arrow's chest re-picks the plan from there (the arrow moves on then anyway, so it's never a visible
  flip); ``fresh_each_chest=False`` is the strict version that only extends.
* Plan running short (under ``extend_below`` seconds left): EXTEND from the last stop, keeping every stop ahead.
* Off route: he's losing time on the current leg. Time lost = travel time to the target now minus the best it has
  been on this leg (Dijkstra on the terrain graph). Over ``lost_seconds`` for ``off_seconds`` = re-plan from here.
  Standing still in a fight loses no time, so it never re-plans; running off somewhere else does.
* A chest within ``nearby_meters`` that costs at most ``nearby_detour_s`` extra is slotted in first (tour.py's rule),
  whether or not it was on the plan: he never stands next to an unopened chest while the arrow points away.
* A chest he opens off the plan can't be told apart from one he walked past (only the arrow's chest has the arrive
  rule), so both just come off the list; if the side trip cost real time the time-lost test re-plans.
* Back (a pinned chest) is honoured: the pin goes first and the off-route clock restarts.

``rerouted`` is only reported when the chest the arrow points at actually changed.
"""

from __future__ import annotations

from math import dist
import time

import numpy as np

from tour import TourPlanner  # first: it puts the repo root on sys.path

from route import params  # noqa: E402
from route.travel import cell_of  # noqa: E402


class FrozenPlanner(TourPlanner):

    def __init__(self, base, terrain, lost_seconds=5.0, off_seconds=2.5, extend_below=60.0, fresh_each_chest=True, **kwargs):
        super().__init__(base, terrain, **kwargs)
        self.lost_seconds, self.off_seconds, self.extend_below = lost_seconds, off_seconds, extend_below
        self.fresh_each_chest = fresh_each_chest
        self.best_left = None       # least seconds-to-target seen on this leg
        self.extends = []           # (now, ms, stops added)
        self.next_extend = float("-inf")
        self._visited = set()

    # -- solving ------------------------------------------------------------
    def _solve(self, player, visited, warm=None, reason="start", now=None):
        if reason != "start":
            self.reroutes.append((now, reason, tuple(player)))
        self.detour = self.detour_home = None
        started = time.monotonic()
        order, _, _ = self.base.plan(player, visited, None)
        self.solves.append(("reroute" if reason != "start" else "full", (time.monotonic() - started) * 1000, len(order)))
        return list(order)

    def _extend(self, visited, now):
        last = self.order[-1]
        started = time.monotonic()
        more, _, _ = self.base.plan(tuple(self.base.xy[last]), set(visited) | set(self.order), None)
        more = [s for s in more if s not in self.order]
        self.order += more
        self.extends.append((now, (time.monotonic() - started) * 1000, len(more)))
        if not more:
            self.next_extend = now + 5.0      # nothing reachable past the end: don't retry on every fix

    def _seconds_left(self, player):
        """Rough seconds to finish the plan: this leg along its path, then the chest-to-chest table, plus stops."""
        legs = self._seconds_along(player, self.leg_path) if self.leg_path else 0.0
        o = self.order
        legs += sum(self.base.T[a, b] for a, b in zip(o, o[1:]))
        return legs + params.CHEST_STOP_S * len(o)

    def _nearby_ok(self, spot):
        return spot not in self._visited

    def _to_target(self, player, target):
        _, seconds = self.terrain.graph.dijkstra(cell_of(*player), cell_of(*self.base.xy[target]))
        return seconds

    def _new_leg(self, player):
        self.leg_target = self.order[0] if self.order else None
        self.leg_path = self.terrain.path(player, tuple(self.base.xy[self.leg_target])) if self.order else None
        self.best_left = None
        self.off_since = None

    # -- following ----------------------------------------------------------
    def plan(self, player, visited, now, pin=None):
        """Return (order, rerouted). ``rerouted`` = re-planned AND the arrow's chest changed."""
        before = self.order[0] if self.order else None
        self._visited = visited
        self.order = [s for s in self.order if s not in visited]     # reached, skipped or walked past: just drop it
        if pin is not None and pin not in visited:
            if not self.order or self.order[0] != pin:
                self.order = [pin] + [s for s in self.order if s != pin]
                self.detour = self.detour_home = None
                self._new_leg(player)
        replanned = False
        if self.fresh_each_chest and pin is None and before is not None and before in visited:
            # He just finished the arrow's chest, so the arrow moves on anyway: pick the next stop fresh from here
            # (invisible, not a reroute). This is what keeps the plan on chests near him: a plan made a minute ago
            # can't know about the two chests he has since walked up to. Between chests the plan stays frozen.
            started = time.monotonic()
            fresh, _, _ = self.base.plan(player, visited, None)
            self.solves.append(("next chest", (time.monotonic() - started) * 1000, len(fresh)))
            if fresh:
                self.order = list(fresh)
                self.detour = self.detour_home = None
                self._new_leg(player)
        if not self.order:
            self.order = self._solve(player, visited, reason="start" if before is None else "plan used up", now=now)
            replanned = before is not None
            self._new_leg(player)
        elif pin is None:
            if self.leg_target != self.order[0] or self.leg_path is None:
                self._new_leg(player)
            left = self._to_target(player, self.order[0])
            self.best_left = left if self.best_left is None else min(self.best_left, left)
            if left - self.best_left > self.lost_seconds:
                self.off_since = now if self.off_since is None else self.off_since
                if now - self.off_since >= self.off_seconds:
                    self.order = self._solve(player, visited, reason="off route", now=now)
                    replanned = True
                    self._new_leg(player)
            else:
                self.off_since = None
            if not replanned and now >= self.next_extend and self._seconds_left(player) < self.extend_below:
                self._extend(visited, now)
            if not replanned and self.order:
                self._nearby(player, now)
                if self.leg_target != self.order[0]:
                    self._new_leg(player)
        after = self.order[0] if self.order else None
        return self.order, replanned and after != before
