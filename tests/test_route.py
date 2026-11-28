import itertools
import random
import subprocess
import sys
from math import inf
from pathlib import Path

import numpy as np
import pytest

from route import params as P
from route.landing import BusPath, best_landing, land_time
from route.orienteering import exact_best, ils_best, nearest_neighbor, route_time
from route.travel import Graph, dijkstra_within, floyd_warshall

ROOT = Path(__file__).resolve().parent.parent


def line_matrix(points):
    pts = np.asarray(points, dtype=float)
    return np.abs(pts[:, None] - pts[None, :])


def random_instance(n, seed):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 100, size=(n, 2))
    T = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1)) / 6.0
    return T


def brute_force(T, start, candidates, budget, stop):
    others = [c for c in candidates if c != start]
    for k in range(len(others), -1, -1):
        best = None
        for combo in itertools.permutations(others, k):
            r = [start, *combo]
            t = route_time(T, r, stop)
            if t <= budget and (best is None or t < best[1]):
                best = (r, t)
        if best:
            return best
    return [], 0.0


# --- Silas's class code still works, untouched -------------------------------

def test_class_tests_still_pass():
    out = subprocess.run([sys.executable, "test_graph.py"], cwd=ROOT / "class", capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.count("PASS") == 7


# --- travel ------------------------------------------------------------------

def test_dijkstra_within_matches_his_dijkstra():
    g = Graph()
    g.add_edge("A", "B", 8)
    g.add_edge("A", "C", 2)
    g.add_edge("B", "D", 3)
    g.add_edge("C", "B", 2)
    g.add_edge("C", "D", 10)
    d = dijkstra_within(g, "A", 100)
    for node in "BCD":
        assert d[node] == g.dijkstra("A", node)[1]
    assert "D" not in dijkstra_within(g, "A", 6)  # D costs 7, over the limit


def test_floyd_warshall_small():
    m = np.array([[0, 1, inf], [1, 0, 2], [inf, 2, 0]], dtype=float)
    floyd_warshall(m)
    assert m[0, 2] == 3 and m[2, 0] == 3


def test_real_travel_matrix_is_sane():
    from route.travel import load_spawns, travel_matrix
    _, _, xy = load_spawns()
    T = travel_matrix()
    assert np.isfinite(T).all()
    assert np.allclose(T, T.T)
    assert (np.diag(T) == 0).all()
    straight = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1)) * P.METERS_PER_PX / P.RUN_SPEED
    assert (T >= straight - 1e-6).all()  # never faster than running in a straight line
    # some pairs must detour around water (otherwise the grid did nothing)
    assert ((T - straight) > 20).sum() > 1000
    # triangle inequality on a sample
    rng = np.random.default_rng(1)
    for i, j, k in rng.integers(0, len(T), size=(500, 3)):
        assert T[i, k] <= T[i, j] + T[j, k] + 1e-6


# --- orienteering --------------------------------------------------------------

def test_hand_checked_line():
    # chests at 0, 10, 20, 50 seconds along a line; stop 1 s; budget 24 s
    # 0 -> 10 -> 20 costs 20 walking + 3 stops = 23 <= 24. Adding 50 is far too much.
    T = line_matrix([0, 10, 20, 50])
    route, t = exact_best(T, 0, [1, 2, 3], 24, stop=1)
    assert route == [0, 1, 2] and t == 23
    route2, t2 = ils_best(T, 0, [1, 2, 3], 24, stop=1)
    assert route2 == [0, 1, 2] and t2 == 23


def test_start_in_middle_goes_short_side_first():
    # start at 10; chests at 0, 4 and 18, 20 (stop 0.5 s).
    # Short side first: 10->4->0 = 10 s, then 0->18->20 = 20 s: 30 s walking + 2.5 s stops = 32.5.
    # Long side first: 10->18->20 = 10 s, then 20->4->0 = 20 s: also 32.5. Budget 32 fits only 4.
    T = line_matrix([10, 0, 4, 18, 20])
    route, t = exact_best(T, 0, [1, 2, 3, 4], 32.5, stop=0.5)
    assert len(route) == 5 and t == 32.5
    route, t = exact_best(T, 0, [1, 2, 3, 4], 32, stop=0.5)
    assert len(route) == 4


@pytest.mark.parametrize("seed", range(6))
def test_exact_matches_brute_force(seed):
    T = random_instance(7, seed)
    budget = 25.0
    r1, t1 = exact_best(T, 0, list(range(7)), budget, stop=1)
    r2, t2 = brute_force(T, 0, list(range(7)), budget, stop=1)
    assert len(r1) == len(r2)
    assert t1 == pytest.approx(t2)


@pytest.mark.parametrize("seed", range(20))
def test_heuristic_matches_exact_on_small_cases(seed):
    T = random_instance(13, seed)
    budget = 40.0
    re_, _ = exact_best(T, 0, list(range(13)), budget, stop=1)
    rh, th = ils_best(T, 0, list(range(13)), budget, stop=1, iters=150, seed=seed)
    rn, _ = nearest_neighbor(T, 0, list(range(13)), budget, stop=1)
    assert th <= budget + 1e-9
    assert len(rh) == len(re_)            # heuristic finds the optimum count
    assert len(rh) >= len(rn)             # and never loses to the naive route
    assert len(set(rh)) == len(rh) and rh[0] == 0


def test_prize_prefers_sure_chest():
    # from 0: a sure chest 10 s one way, or two 50% chests 10 and 12 s the other way; budget fits only one side.
    # Count says go for the two; expected chests (1.0 vs 0.5 + 0.5, tie -> shorter) says the sure one.
    xy = [0, 10, -10, -12]
    T = line_matrix(xy)
    prize = np.array([1.0, 1.0, 0.5, 0.5])
    assert len(exact_best(T, 0, [1, 2, 3], 16, stop=1)[0]) == 3
    for solve in (exact_best, ils_best):
        route, _ = solve(T, 0, [1, 2, 3], 16, stop=1, prize=prize)
        assert route == [0, 1]


@pytest.mark.parametrize("seed", range(12))
def test_prize_heuristic_matches_exact(seed):
    T = random_instance(13, seed)
    prize = np.random.default_rng(seed).choice([1.0, 0.6, 0.5], size=13)
    re_, _ = exact_best(T, 0, list(range(13)), 40.0, stop=1, prize=prize)
    rh, th = ils_best(T, 0, list(range(13)), 40.0, stop=1, iters=150, seed=seed, prize=prize)
    assert th <= 40.0 + 1e-9 and rh[0] == 0 and len(set(rh)) == len(rh)
    assert sum(prize[rh]) == pytest.approx(sum(prize[re_]))


def test_routes_respect_budget_on_real_map():
    from route.travel import travel_matrix
    T = travel_matrix()
    for start in (0, 100, 400, 800):
        cand = np.nonzero(T[start] <= 90)[0].tolist()
        r, t = ils_best(T, start, cand, 90, iters=40)
        assert t <= 90 + 1e-9 and t == pytest.approx(route_time(T, r))
        assert r[0] == start and len(set(r)) == len(r)


# --- landing ------------------------------------------------------------------

def test_land_time_under_bus_and_out_of_reach():
    bus = BusPath((0, 0), (1000, 0))
    under = land_time(bus, (300, 0))
    assert under == pytest.approx(300 * P.METERS_PER_PX / P.BUS_SPEED + P.FALL_BASE_S)
    side = land_time(bus, (300, 100))
    assert side > under
    assert land_time(bus, (300, P.MAX_DROP_REACH_M / P.METERS_PER_PX + 50)) is None


def test_best_landing_picks_dense_cluster():
    # 12 chests packed together far down the bus line vs 3 spread near the start
    rng = np.random.default_rng(0)
    dense = np.array([500, 20]) + rng.uniform(-5, 5, size=(12, 2))
    sparse = np.array([[50, 0], [150, 0], [250, 0]], dtype=float)
    xy = np.vstack([sparse, dense])
    T = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1)) * P.METERS_PER_PX / P.RUN_SPEED
    best, _ = best_landing(T, xy, BusPath((0, 0), (1000, 0)), fixed_budget=60)
    assert best.chest >= 3 and len(best.route) == 12


@pytest.mark.parametrize("start", [62, 147, 236, 546, 572])
def test_heuristic_matches_exact_on_real_map_clusters(start):
    # these five spots once beat the heuristic by one chest (far, dense clusters)
    from route.travel import travel_matrix
    T = travel_matrix()
    cluster = np.argsort(T[start])[:16].tolist()
    ex, _ = exact_best(T, start, cluster, 60)
    h, _ = ils_best(T, start, cluster, 60, iters=300)
    assert len(h) == len(ex)


# --- calibration and route card ---------------------------------------------------

def test_calibration_recovers_speed_and_stop_time():
    from route.scan import fit_calibration
    # true world: travel takes 1.3x the model, each chest stop takes 2.6 s
    rows = [(w, n, 1.3 * w + 2.6 * n) for w, n in [(0, 1), (4.1, 2), (9.7, 4), (20.2, 7), (35.0, 12), (61.3, 20)]]
    k, c = fit_calibration(rows)
    assert k == pytest.approx(1.3) and c == pytest.approx(2.6)


def test_card_splits_match_route_time_and_compass():
    from route.card import build_steps, compass
    T = line_matrix([0, 10, 25])
    xy = np.array([[0, 0], [10, 0], [10, 15]], dtype=float)
    steps = build_steps([0, 1, 2], T, xy)
    assert steps[-1]["split_s"] == pytest.approx(route_time(T, [0, 1, 2]))
    assert steps[-1]["walk_s_cum"] == pytest.approx(25)
    assert compass((0, 0), (10, 0)) == "E" and compass((0, 0), (0, -5)) == "N"
    assert compass((0, 0), (-3, 3)) == "SW"
