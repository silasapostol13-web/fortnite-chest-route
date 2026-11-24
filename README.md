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

## Pass 2: the Pirate Shop Token goal (2026-11-24)

**Goal:** Epic's published odds are 1 in 137,500 per chest, any chest, with no chest count or time
limit (RESEARCH.md). So the job is just "open the most chests". There's no natural time window, so
the objective is **most chests in the first 2:00 on the ground, any bus**. That's what lets one place
be "the best spot to land".

**Whole-map scan** (`python -m route.scan`, ~80 s): every one of the 860 spots is scored with the
full solver.

| Rank | Place | Chest spots in 2:00 |
|---|---|---|
| 1 | Fortunes Fort | 31 (1:58.3) |
| 2 | Rubber Resort | 31 (1:58.5) |
| 3 | Lantern Landing | 29 |
| 4 | The Rocky | 29 |
| 5 | Plunder Port | 29 |

An average drop gets 24 (the mean over all 860 spots). 31 chest spots is about 21 real chests,
which puts the token at about 1 in 6,600 games. The route raises your odds; it doesn't promise a token.

**How sure** (`python -m route.scan --robust`): I re-scored with travel 20% faster or slower (which
covers the map-scale guess and the missing building slowdown) and with 1.5, 2 or 3 s per chest.
**Fortunes Fort was never beaten in any of the 9 cases.** Rubber Resort tied it in 5 and fell behind
in 4; with 3 s per chest, The Rocky ties it in 2 of 3 cases. Honest claim: Fortunes Fort is the best spot or
tied for it under every guess we tested. Rubber Resort is a strong second choice when the Fort is contested.

**Calibration:** after he plays the route, put his times in a CSV (`chest,real_time`, with chest
numbers from the route card and times like `0:43` since landing) and run
`python -m route.scan --calibrate splits.csv`. It fits "real travel = k × model" plus seconds per
chest and prints the new numbers for `params.py`.

**Route card** (`python -m route.card`): `docs/route_card.png` / `.md` has numbered circles on the
map, direction, metres and a target time for each chest. The spawn data has no landmark names
smaller than the area, so the numbered map is the landmark.

**Show-off clip** (`python -m route.scan_render --draft`): the scan sweep and heat map, the top 5,
the winner's route drawing itself with the counter, then "average drop 24 / this route 31".
Ideas for the editor are in `docs/overlay-ideas.md` (a list only, nothing built).

## Drop planner

Open [planner/index.html](planner/index.html) in a browser. Drag the Battle Bus
line in its direction of travel or use the sample bus. Start the flyover,
then press Space or → to advance, ← to go back, and Esc for the route overview.
The controls work with touch as well.

The planner uses the November 24, 2026 Crossbones Isle v43.11 game minimap and a
matching [SequeLariFN chest snapshot](https://www.sequelarifn.com.br/dados/mapa-objetos).
It precomputes 108 routes from 36 directed headings and three offsets each.
Of the 1,007 chest records, 901 are standard chests at 900 unique map positions.
Rare and buried records are retained in the CSV for reference. Landing labels
use the nearest named POI. Chest availability varies by match. Movement,
storm timing and distances are model estimates.

The minimap is kept out of Git. In a fresh checkout with the Python dependencies
above, download the pinned game asset before opening the page:

```bash
.venv/bin/python -c 'from urllib.request import urlopen; from PIL import Image; from io import BytesIO; from route.planner_source import MAP_IMAGE, MAP_IMAGE_URL; Image.open(BytesIO(urlopen(MAP_IMAGE_URL).read())).save(MAP_IMAGE, lossless=True)'
```

The browser loads the precomputed snapshot directly, including when opened as a
local file. Regenerate both the JSON and browser snapshot after model changes:

```bash
.venv/bin/python scripts/export_planner.py
```

**Reliable loot** ranks routes by expected chest openings, counting each
guaranteed spawn as one and weighting each random spawn by the slider. The
recommendation can stay the same if it already scores highest among the
routes the heuristic evaluates. In **Edit bus**, the blue line is the path you
drew. The dashed white line is the snapped path used by the route model.

Click numbered pins or use **Jump to** to inspect a route stop. During the
flyover, press **X** or **Empty chest** to record a miss and replan from that
location using the estimated time left. The route keeps the previous stops and
marks the missing chest with an ×. It assumes the other visited chests were opened.

Regenerate the browser’s travel network after changing the map, spawn data,
or movement model:

```bash
.venv/bin/python scripts/export_planner_network.py
```

Set **Drop style** before drawing a bus path or using the sample bus.
**Standard** uses the normal loot objective. **Quiet Drop** favors landings
farther from the drawn bus line and **Hot Drop** favors nearer landings.
Both keep at least 85% of the top modeled loot score among reachable candidates
and can be combined with Reliable Loot. Distance is a proxy for competition.
