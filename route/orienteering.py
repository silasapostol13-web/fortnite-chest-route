"""Most chests in a time limit: the orienteering problem.

You start on one chest, have B seconds, every chest you open costs a stop,
and walking between chests costs real travel time. Pick which chests and in
what order so you open as many as possible. This is the Orienteering Problem
(a "prize-collecting" cousin of the Travelling Salesman Problem). It is
NP-hard: no known algorithm solves every case fast, so

* ``exact_best`` solves it perfectly with dynamic programming over subsets,
  but only for ~15 chests (2^15 subsets x 15 end points), and
* ``ils_best`` is a fast heuristic (greedy insertion + 2-opt + ruin-and-recreate
  iterated local search) for the whole map. Tests compare the two.
"""

from __future__ import annotations

import random

import numpy as np

from . import params as P


def route_time(T, route, stop=P.CHEST_STOP_S):
    """Seconds to land on route[0] and open every chest along the route."""
    legs = sum(T[a, b] for a, b in zip(route, route[1:]))
    return float(legs + stop * len(route))


# --------------------------------------------------------------------------
# Exact: DP over subsets
# --------------------------------------------------------------------------

def exact_best(T, start, candidates, budget, stop=P.CHEST_STOP_S):
    """Optimal route from ``start`` using only ``candidates`` (<= ~16 nodes).

    dp[mask][j] = least time to start at ``start``, open exactly the chests in
    ``mask``, and be standing at chest j. Return the best route found.
    """
    nodes = [start] + [c for c in candidates if c != start]
    k = len(nodes)
    if k > 18:
        raise ValueError("exact_best is exponential; keep it to ~16 chests")
    sub = T[np.ix_(nodes, nodes)] + stop  # moving to j includes opening j
    full = 1 << k
    dp = np.full((full, k), np.inf)
    parent = np.full((full, k), -1, dtype=int)
    dp[1, 0] = stop  # standing on the landing chest, opened it
    best_mask, best_end, best_cnt, best_t = 1, 0, 1, stop
    if stop > budget:
        return [], 0.0
    popcount = [bin(m).count("1") for m in range(full)]
    for mask in range(1, full, 2):  # start (bit 0) always in the mask
        row = dp[mask]
        live = np.nonzero(row <= budget)[0]
        if live.size == 0:
            continue
        cnt = popcount[mask]
        for j in live:
            t = row[j]
            if cnt > best_cnt or (cnt == best_cnt and t < best_t):
                best_mask, best_end, best_cnt, best_t = mask, j, cnt, t
        # extend to every chest not yet in mask
        outside = [n for n in range(1, k) if not mask >> n & 1]
        if not outside:
            continue
        times = row[live][:, None] + sub[np.ix_(live, outside)]  # (live, outside)
        arg = times.argmin(axis=0)
        mins = times[arg, range(len(outside))]
        for col, n in enumerate(outside):
            nm = mask | (1 << n)
            if mins[col] < dp[nm, n]:
                dp[nm, n] = mins[col]
                parent[nm, n] = live[arg[col]]
    # walk parents back
    route, mask, j = [], best_mask, best_end
    while j != -1:
        route.append(nodes[j])
        pj = parent[mask, j]
        mask &= ~(1 << j)
        j = pj
    route.reverse()
    return route, float(best_t)


# --------------------------------------------------------------------------
# Heuristic: iterated local search
# --------------------------------------------------------------------------

def _insert_greedy(T, route, pool, budget, stop, rng=None, noise=0.0):
    """Keep inserting the chest that adds the least time, while it fits.

    With ``noise`` > 0 the choice is randomised a little (each option's cost is
    scaled by 1..1+noise) so repeated runs explore different chest sets.
    """
    route = list(route)
    pool = set(pool) - set(route)
    t = route_time(T, route, stop)
    while pool:
        cand = np.fromiter(pool, dtype=int)
        r = np.asarray(route)
        best = np.inf
        best_pos = best_c = None
        if len(r) >= 2:
            a, b = r[:-1], r[1:]
            delta = T[np.ix_(a, cand)] + T[np.ix_(cand, b)].T - T[a, b][:, None]  # (L-1, m)
            pos = delta.argmin(axis=0)
            vals = delta[pos, range(len(cand))]
            if noise:
                vals = vals * (1 + noise * np.array([rng.random() for _ in vals]))
            m = vals.argmin()
            best, best_pos, best_c = vals[m], int(pos[m]) + 1, int(cand[m])
        end = T[r[-1], cand]
        if noise:
            end = end * (1 + noise * np.array([rng.random() for _ in end]))
        m = end.argmin()
        if end[m] < best:
            best, best_pos, best_c = end[m], len(route), int(cand[m])
        new_route = route[:best_pos] + [best_c] + route[best_pos:]
        new_t = route_time(T, new_route, stop)
        if new_t > budget + 1e-9:
            if noise:  # the noisy pick may not fit; finish deterministically
                return _insert_greedy(T, route, pool, budget, stop)
            break
        route, t = new_route, new_t
        pool.discard(best_c)
    return route


def _two_opt(T, route):
    """Reverse segments while that shortens the walk (start stays fixed)."""
    route = list(route)
    improved = True
    L = len(route)
    while improved:
        improved = False
        for i in range(1, L - 1):
            for j in range(i + 1, L):
                a, b = route[i - 1], route[i]
                c = route[j]
                d = route[j + 1] if j + 1 < L else None
                before = T[a, b] + (T[c, d] if d is not None else 0.0)
                after = T[a, c] + (T[b, d] if d is not None else 0.0)
                if after < before - 1e-9:
                    route[i:j + 1] = reversed(route[i:j + 1])
                    improved = True
    return route


def _or_opt(T, route):
    """Move one chest to a better spot in the route while that saves time."""
    route = list(route)
    improved = True
    while improved and len(route) > 2:
        improved = False
        for i in range(1, len(route)):
            x = route[i]
            prev, nxt = route[i - 1], (route[i + 1] if i + 1 < len(route) else None)
            gain = T[prev, x] + (T[x, nxt] - T[prev, nxt] if nxt is not None else 0.0)
            rest = route[:i] + route[i + 1:]
            for j in range(1, len(rest) + 1):
                a, b = rest[j - 1], (rest[j] if j < len(rest) else None)
                cost = T[a, x] + (T[x, b] - T[a, b] if b is not None else 0.0)
                if cost < gain - 1e-9:
                    route = rest[:j] + [x] + rest[j:]
                    improved = True
                    break
            if improved:
                break
    return route


def _swap_out(T, route, pool, stop):
    """Swap a chest in the route for one outside it when that saves time."""
    route = list(route)
    inside = set(route)
    outside = [c for c in pool if c not in inside]
    if not outside:
        return route
    out = np.asarray(outside)
    for i in range(1, len(route)):
        prev, nxt = route[i - 1], (route[i + 1] if i + 1 < len(route) else None)
        x = route[i]
        old = T[prev, x] + (T[x, nxt] if nxt is not None else 0.0)
        new = T[prev, out] + (T[out, nxt] if nxt is not None else 0.0)
        k = int(new.argmin())
        if new[k] < old - 1e-9:
            route[i] = int(out[k])
            outside[k] = x
            out[k] = x
    return route


def _improve(T, route, pool, budget, stop):
    for _ in range(4):
        before = route_time(T, route, stop)
        before_count = len(route)
        route = _two_opt(T, route)
        route = _or_opt(T, route)
        route = _swap_out(T, route, pool, stop)
        route = _insert_greedy(T, route, pool, budget, stop)
        if route_time(T, route, stop) >= before - 1e-9 and len(route) == before_count:
            break
    return route


def _better(T, r1, r2, stop):
    """True if r1 beats r2: more chests, or same chests in less time."""
    if len(r1) != len(r2):
        return len(r1) > len(r2)
    return route_time(T, r1, stop) < route_time(T, r2, stop) - 1e-9


def ils_best(T, start, candidates, budget, stop=P.CHEST_STOP_S, iters=300, seed=0):
    """Fast near-optimal route (iterated local search)."""
    if stop > budget:
        return [], 0.0
    rng = random.Random(seed)
    pool = [c for c in candidates if c != start and T[start, c] + 2 * stop <= budget]
    best = _improve(T, _insert_greedy(T, [start], pool, budget, stop), pool, budget, stop)
    current = best
    for _ in range(iters):
        r = list(current)
        if len(r) > 2:
            # ruin: drop a random stretch, or random chests
            k = rng.randint(1, max(1, min(8, len(r) // 2)))
            roll = rng.random()
            if roll < 0.35:
                i = rng.randint(1, len(r) - k)
                del r[i:i + k]
            elif roll < 0.7:
                # cut the tail and head for a chest the greedy fill would never pick,
                # so far-but-dense clusters get a chance
                del r[rng.randint(1, len(r) - 1):]
                far = [c for c in pool if c not in r and route_time(T, r + [c], stop) <= budget]
                if far:
                    r.append(rng.choice(far))
            else:
                for idx in sorted(rng.sample(range(1, len(r)), min(k, len(r) - 1)), reverse=True):
                    del r[idx]
        # recreate
        r = _insert_greedy(T, r, pool, budget, stop, rng=rng, noise=0.6)
        r = _improve(T, r, pool, budget, stop)
        if len(r) >= len(current) or rng.random() < 0.05:  # plateau moves allowed
            current = r
        if _better(T, current, best, stop):
            best = current
    return best, route_time(T, best, stop)


def nearest_neighbor(T, start, candidates, budget, stop=P.CHEST_STOP_S):
    """The naive way: always run to the closest unopened chest. Baseline only."""
    if stop > budget:
        return [], 0.0
    left = set(candidates) - {start}
    route, t = [start], stop
    while left:
        cand = np.fromiter(left, dtype=int)
        j = int(cand[T[route[-1], cand].argmin()])
        if t + T[route[-1], j] + stop > budget:
            break
        t += T[route[-1], j] + stop
        route.append(j)
        left.discard(j)
    return route, t
