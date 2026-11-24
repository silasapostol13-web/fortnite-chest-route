# Fortnite chest route

Where to drop on Crossbones Isle, and which path opens the most chests before the storm.
A personal side project built on top of Silas's ITSC 2214 Project 2. **Not coursework**: nothing
here goes back into the class.

## Who wrote what

**Silas (the class project, in `class/`, untouched):** the `Graph` class (adjacency list), BFS,
DFS and Dijkstra in `class/main.py`, plus the class tests and writeup. It's the copy as submitted
on 2026-11-23 (first commit). AI set up the data files and the map drawing for that version, as the
writeup says.

**Claude (everything outside `class/`):** the walk grid, the route solvers, the landing finder,
the tests, the animation and the research notes.

His code is still doing real work here:
- the whole map becomes a grid of ~8.5 m squares stored in **his `Graph` class**,
- every chest-to-chest travel time comes from **his Dijkstra** (a copy that stops after 60 s and
  finds every chest in reach, in `route/travel.py`),
- every leg of the drawn route is walked by **his own `Graph.dijkstra(start, end)`**, unchanged.

## The problem, in plain words

1. **How long does it take to get from chest A to chest B?** Not a straight line: you run around
   water or swim it. The map picture is turned into land and water squares, and Dijkstra finds the
   fastest way. 860 chest spots, about 740,000 pairs, built in ~7 seconds.
2. **Which chests, in what order, in the time you have?** This is the *orienteering problem*
   (a cousin of the travelling salesman problem). It's **NP-hard**: nobody knows a fast way to
   solve it perfectly, and every extra chest doubles the work for the perfect method.
   - **Exact:** dynamic programming over every subset of chests. Perfect, but only for about 16
     chests: 16 takes 0.35 s, 18 takes 1.4 s, 40 would take weeks.
   - **Heuristic (whole map):** build a route greedily, then keep breaking and rebuilding it
     (2-opt, moving and swapping chests, cutting the tail to try a far cluster). Milliseconds.
   - **Result** (`run.py compare --k 16 --cases 40`): the heuristic matched the perfect answer
     **40 out of 40** times; "run to the nearest chest" got 9.9 vs 11.1 in a minute. With the
     whole map open the heuristic averages 12.1, which the exact method can't even attempt.
3. **Where do I land?** For a bus path, every chest you can reach is a possible landing. Landing
   time depends on how far it is from the bus line. Loot time runs until the first storm closes.
   All 700+ landings are screened, the best 20 get the full solver.

## Results (with the guessed numbers in RESEARCH.md)

| Bus path | Best landing | Chest spawns hit | ≈ real chests |
|---|---|---|---|
| Top to bottom, through the middle | Fortunes Fort | 38 in 2:30 | 26 |
| West to east, through the middle | Lantern Landing | 37 in 2:35 | 25 |
| South-west to north-east | Loguetown | 32 in 2:22 | 21 |
| South-east to north-west | Plunder Port | 31 in 2:11 | 21 |
| Any bus, exactly 2:00 on the ground | Fortunes Fort | 31 | 21 |

The bus path changes the answer, which is the point: there's no single "best drop".
"Chest spawns hit" are spots on the route; about 2 in 3 have a chest in a real game.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pillow pytest
```

The map picture isn't in git (it's Epic's art). Put it in `data/`:

```bash
curl -L -o data/crossbones-isle-43.00.webp https://fortnitepirateshoptoken.org/site/maps/crossbones-isle-43.00.webp
```

```bash
.venv/bin/python run.py land
```

```bash
.venv/bin/python run.py land --bus 600,60,600,1250 --seconds 120
```

```bash
.venv/bin/python run.py compare
```

```bash
.venv/bin/python -m route.render --draft
```

```bash
.venv/bin/python -m pytest -q
```

`--bus x1,y1,x2,y2` is the bus line in map pixels (1212 x 1298 map, 0,0 top-left).
`run.py land` saves `out/best_landing.json`; the renderer animates that.

## Tests (40)

Silas's 7 class checks still pass; his Dijkstra and the "within 60 s" copy agree; the real travel
table is symmetric, never faster than a straight-line sprint, and detours around water; a
hand-checked route on a line; the exact solver matches brute force; the heuristic matches the exact
solver on 20 random maps and 5 real-map spots that once fooled it; routes never go over time; bus
landing times; the landing finder picks the dense cluster.

## What's rough

Map scale, bus, glide and storm numbers are guesses (see RESEARCH.md). No buildings, floors,
other players or re-planning when a chest doesn't spawn.
