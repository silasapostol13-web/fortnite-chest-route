# Build brief: the drop planner page (for Codex or Claude)

Read README.md and RESEARCH.md first. The hard part (chest data, travel times, route solver, landing
finder) already exists in Python. This job is a page on top of it. Keep it small.

## What it does
1. **Plan:** the full Crossbones Isle map (`data/crossbones-isle-43.00.webp`) fills the screen. The user
   click-drags a straight line across it = the battle bus path (start point to end point, so direction counts).
   The best landing spot pulses with its name, and the route for that bus appears.
2. **Flyover (the core, build this first and make it smooth):** the map is one big canvas. The view zooms in on
   the landing spot, then on each key press (Space / right arrow) it **glides across the map to the next chest**
   while a line draws itself from the last chest to the next one. Ease in/out, ~0.8-1.2 s per hop, 60 fps.
   Previous legs stay drawn, chests are numbered dots. On screen: "Chest 4 / 31", compass heading in degrees
   (same convention as Fortnite's top compass, 0 = north, clockwise; `route/card.py: compass()`), about how many
   meters, and "about N s". Left arrow goes back one hop. Escape zooms out to the whole route.
3. Nothing else (no accounts, no learning, no squad mode).

## How to build it (suggested)
- **Precompute in Python, page only looks up.** Write `scripts/export_planner.py`: for bus paths every 10
  degrees in both directions across the island (36 headings; pick a sensible fixed offset through the middle,
  plus 2-3 parallel offsets per heading if cheap), run `route/landing.py: best_landing(...)` and export to
  `planner/data.json`: per bus path the landing (name, x, y), the ordered chest list (x, y in map-image pixels),
  and each leg's travel seconds (from the travel matrix in `route/travel.py`). On drag, the page snaps the drawn
  line to the nearest precomputed bus path (heading first, then offset).
- **Page:** `planner/index.html` + one JS file, plain canvas or a tiny lib from a CDN, no build step, opens by
  double-click or `python3 -m http.server`. Dark UI like `~/Brand/library/screen/2026-11-24-fortnite-chest-route-top5-still.png`:
  white bold text, yellow accent, red #1 pin.
- Coordinates: chest CSV pixels are on a 1212x1298 map; the image is 1400x1500 (x1.155). `route/travel.py:
  load_spawns()` already handles this; reuse it.

## Rules
- Do NOT touch `class/` (Silas's graded class code, handed in as is).
- Numbers are estimates (map scale, bus, storm): the page says "about", never exact.
- Done = it runs locally, a drag gives a route, 10+ hops glide smoothly with no jumps, and you checked it with
  your own eyes or a screen recording, not just "it loads". Say plainly what you did and didn't check.
- Commit in small steps with plain messages.
