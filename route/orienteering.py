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

Prize-collecting: not every spot spawns a chest, so both take an optional ``prize``
(one number per node of ``T``, e.g. the chance a chest spawns there) and maximise the
total prize (expected chests) instead of the count, ties going to the shorter route.
``prize=None`` (the default) is every node worth 1: exactly the old behaviour.
"""

from __future__ import annotations

import random

import numpy as np

from . import params as P


def route_time(T, route, stop=P.CHEST_STOP_S):
    """Seconds to land on route[0] and open every chest along the route."""
    legs = sum(T[a, b] for a, b in zip(route, route[1:]))
    return float(legs + stop * len(route))


def route_prize(route, prize=None):
    """Total prize of a route: its length when every node is worth 1 (``prize=None``)."""
    if prize is None:
        return len(route)
    return float(sum(prize[c] for c in route))


# --------------------------------------------------------------------------
# Exact: DP over subsets
# --------------------------------------------------------------------------

def exact_best(T, start, candidates, budget, stop=P.CHEST_STOP_S, prize=None):
    """Optimal route from ``start`` using only ``candidates`` (<= ~16 nodes).

    dp[mask][j] = least time to start at ``start``, open exactly the chests in
    ``mask``, and be standing at chest j. Return the best route found (most
    prize, then least time; prize None = every chest worth 1).
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
    worth = np.ones(k) if prize is None else np.asarray([prize[n] for n in nodes], dtype=float)
    bits = np.arange(full)
    popcount = np.zeros(full)
    for b in range(k):
        popcount[(bits >> b) & 1 == 1] += worth[b]
    best_cnt = worth[0]
    for mask in range(1, full, 2):  # start (bit 0) always in the mask
        row = dp[mask]
        live = np.nonzero(row <= budget)[0]
        if live.size == 0:
            continue
        cnt = popcount[mask]
        for j in live:
            t = row[j]
            if cnt > best_cnt + 1e-9 or (cnt > best_cnt - 1e-9 and t < best_t):
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

def _insert_greedy(T, route, pool, budget, stop, rng=None, noise=0.0, prize=None):
    """Keep inserting the chest that adds the least time, while it fits.

    With ``noise`` > 0 the choice is randomised a little (each option's cost is
    scaled by 1..1+noise) so repeated runs explore different chest sets. With a
    ``prize`` it inserts the chest with the most prize per added second instead.
    """
    if prize is not None:
        return _insert_greedy_prize(T, route, pool, budget, stop, rng, noise, prize)
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


def _insert_greedy_prize(T, route, pool, budget, stop, rng, noise, prize):
    """Prize-collecting greedy: among chests that still fit, insert (at its cheapest spot) the one with the most
    prize per added second, added second = extra walking + the stop."""
    route = list(route)
    pool = set(pool) - set(route)
    t = route_time(T, route, stop)
    while pool:
        cand = np.fromiter(pool, dtype=int)
        r = np.asarray(route)
        add = T[r[-1], cand].astype(float)               # append at the end
        where = np.full(len(cand), len(route))
        if len(r) >= 2:
            a, b = r[:-1], r[1:]
            delta = T[np.ix_(a, cand)] + T[np.ix_(cand, b)].T - T[a, b][:, None]  # (L-1, m)
            pos = delta.argmin(axis=0)
            ins = delta[pos, range(len(cand))]
            inner = ins <= add                           # ties go inside, like the unweighted version
            add = np.where(inner, ins, add)
            where = np.where(inner, pos + 1, where)
        fits = t + add + stop <= budget + 1e-9
        if not fits.any():
            break
        score = (add + stop) / np.maximum(prize[cand], 1e-9)   # seconds per expected chest: lower is better
        if noise:
            score = score * (1 + noise * np.array([rng.random() for _ in score]))
        score[~fits] = np.inf
        m = int(score.argmin())
        c, at = int(cand[m]), int(where[m])
        route = route[:at] + [c] + route[at:]
        t = route_time(T, route, stop)
        pool.discard(c)
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


def _swap_out(T, route, pool, stop, budget=None, prize=None):
    """Swap a chest in the route for one outside it when that saves time (with a ``prize``: when it gains prize
    and still fits the budget, or keeps the prize and saves time)."""
    route = list(route)
    inside = set(route)
    outside = [c for c in pool if c not in inside]
    if not outside:
        return route
    out = np.asarray(outside)
    if prize is not None:
        t = route_time(T, route, stop)
        p_out = prize[out]
        if len(route) < 2:
            return route
        # one vectorised pass finds the positions with any swap worth trying (usually none at a local optimum)
        r = np.asarray(route)
        prev, xs = r[:-1], r[1:]
        tail = np.zeros((1, len(out)))
        old_all = T[prev, xs] + np.append(T[xs[:-1], r[2:]], 0.0)
        new_all = T[np.ix_(prev, out)] + np.vstack([T[np.ix_(out, r[2:])].T, tail])
        gain_all = p_out[None, :] - prize[xs][:, None]
        ok_all = (new_all <= budget + 1e-9 - t + old_all[:, None]) & (
            (gain_all > 1e-9) | ((gain_all > -1e-9) & (new_all < old_all[:, None] - 1e-9)))
        for i in (np.flatnonzero(ok_all.any(axis=1)) + 1).tolist():
            prev, nxt = route[i - 1], (route[i + 1] if i + 1 < len(route) else None)
            x = route[i]
            old = T[prev, x] + (T[x, nxt] if nxt is not None else 0.0)
            new = T[prev, out] + T[out, nxt] if nxt is not None else T[prev, out]
            gain = p_out - prize[x]
            ok = (new <= budget + 1e-9 - t + old) & ((gain > 1e-9) | ((gain > -1e-9) & (new < old - 1e-9)))
            if not ok.any():
                continue
            gain = np.where(ok, gain, -np.inf)
            top = gain >= gain.max() - 1e-9                          # most prize gained, then least time
            k = int(np.where(top, new, np.inf).argmin())
            t += new[k] - old
            route[i] = int(out[k])
            out[k], p_out[k] = x, prize[x]
        return route
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


def _improve(T, route, pool, budget, stop, prize=None):
    for _ in range(4):
        before = route_time(T, route, stop)
        before_prize = route_prize(route, prize)
        route = _two_opt(T, route)
        route = _or_opt(T, route)
        route = _swap_out(T, route, pool, stop, budget, prize)
        route = _insert_greedy(T, route, pool, budget, stop, prize=prize)
        if route_time(T, route, stop) >= before - 1e-9 and route_prize(route, prize) <= before_prize + 1e-9:
            break
    return route


def _better(T, r1, r2, stop, prize=None):
    """True if r1 beats r2: more prize (chests), or the same in less time."""
    p1, p2 = route_prize(r1, prize), route_prize(r2, prize)
    if abs(p1 - p2) > 1e-9:
        return p1 > p2
    return route_time(T, r1, stop) < route_time(T, r2, stop) - 1e-9


def ils_best(T, start, candidates, budget, stop=P.CHEST_STOP_S, iters=300, seed=0, prize=None):
    """Fast near-optimal route (iterated local search).

    ``prize``: optional array indexed like ``T`` (e.g. spawn chance per spot); the route then maximises total
    prize (expected chests), ties to the shorter route. None = every chest worth 1 (the old objective)."""
    if stop > budget:
        return [], 0.0
    if prize is not None:
        prize = np.asarray(prize, dtype=float)
    rng = random.Random(seed)
    pool = [c for c in candidates if c != start and T[start, c] + 2 * stop <= budget]
    best = _improve(T, _insert_greedy(T, [start], pool, budget, stop, prize=prize), pool, budget, stop, prize)
    if prize is not None:
        # also start from the plain least-time fill (dense clusters): per-second greedy alone often misses it
        plain = _improve(T, _insert_greedy(T, [start], pool, budget, stop), pool, budget, stop, prize)
        if _better(T, plain, best, stop, prize):
            best = plain
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
        # weighted: recreate half the time by least added time, then let swaps/inserts trade for prize
        fill = prize if prize is None or rng.random() < 0.5 else None
        r = _insert_greedy(T, r, pool, budget, stop, rng=rng, noise=0.6, prize=fill)
        r = _improve(T, r, pool, budget, stop, prize)
        if route_prize(r, prize) >= route_prize(current, prize) - 1e-9 or rng.random() < 0.05:  # plateau moves
            current = r
        if _better(T, current, best, stop, prize):
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
