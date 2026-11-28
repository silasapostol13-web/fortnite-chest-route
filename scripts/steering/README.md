# Recorded chest steering

The proof plays source seconds 8–44 of the provided 1920×1080 PlayStation
recording. It uses the planner's existing map and 33 chest waypoints. The
fixed render points to chest 19 throughout the excerpt so camera-turn
behavior can be compared against a stable target. The replay lets you pick
a waypoint, mark it Found or Missing, and advance manually.

Position comes from matching the minimap's land and water silhouette to
the atlas at 2 Hz. Apple Vision reads the center compass value at 12 Hz.
The overlay uses the shortest signed angle from compass heading to the
waypoint's map bearing. It withholds the arrow across tracking gaps and
switches to a search-area cue within about 5 m. The measurements are
estimates from HUD pixels. The prototype is calibrated for this recording's
HUD geometry and minimap scale. The gold styling is original.

## Verification

The 36-second excerpt yielded 72 usable minimap matches and 369 accepted
compass samples out of 432 sampled frames. Eight rendered cues were compared
with their source compass crops in `out/steering/verification.png`. For
example, at 12 seconds the visible 128° heading and 90° target bearing produce
a 38° left turn. At 20 seconds, 70° and 103° produce a 33° right turn.
Chrome playback, waypoint advancement for both marks, and Reset were exercised.
The prototype has no automatic chest detection, floor-specific target placement,
or live capture integration.

## Rebuild

Requires macOS with Swift and Vision, FFmpeg, and a Python environment with
OpenCV and NumPy. Set `recording` to the original footage path.

```bash
mkdir -p out/steering
python scripts/steering/track.py "$recording" out/steering/telemetry.js
ffmpeg -ss 8 -t 36 -i "$recording" -vf 'scale=1280:720,fps=30' \
  -c:v libx264 -preset veryfast -crf 20 -c:a aac -movflags +faststart out/steering/gameplay.mp4
python scripts/steering/render.py out/steering/gameplay.mp4 out/steering/telemetry.js out/steering/steering-demo.mp4
cp scripts/steering/replay.html out/steering/index.html
open out/steering/index.html
```

## First live Remote Play test (2026-11-27, Wi-Fi)

PS5 on Wi-Fi (84 Mbps), Mac on 6 GHz Wi-Fi, PS5 connection banner hidden, Remote Play app at 1080p / High,
window full screen, squads match. `live.py --remote-play --hud --headless --metrics out/steering/live-test-2026-11-27.json`.
- Locked on as soon as he landed; HUD drawn over the game (screenshot checked). Tracked 89.5% of frames after
  the first lock (83.7% of the whole run), vs 291/2,996 frames with the banner on Nov 25.
- About 30 fps between frames (p50 gap 0.03 s), 13 fps average over 82 s because of one 25 s capture stall.
  Going full screen changed the window ID; capture dropped once and reopened by itself.
- Arrow vs path 12 m ahead: median 0°, p90 3.6°, wrong way 0%. Frame to HUD p95 29 ms. Plans 44 ms p50, 70 ms p95
  (slower than on the recording; still off the frame loop).
- Five chests "reached" by the arrive rule in 32 s, two of them 1.6 s apart (spots next to each other): the
  arrive rule may over-count clustered spots. He said: "the concept itself is working", not perfect yet.
- Not checked: the Ctrl-Opt-N/B hot keys; the 3D arrow (this run used the 2D single-arrow build `dd0dffd` via
  `--hud-binary`).

## Live re-planning (`--route live`, the default until 2026-11-27 evening)

`live.py` now plans over every chest spot on the map (1,006 spots: regular, guaranteed, rare and buried)
instead of the fixed 33-chest film list. About once a second, in a background thread, it answers: from where
he is right now, which unopened chests, in what order, open the most in the next `--budget` seconds (default
120)? That is the orienteering problem (NP-hard); `route.orienteering.ils_best` (iterated local search)
solves it on the same terrain graph and Dijkstra travel times the arrow uses. The arrow always points at the
first stop of the newest plan. Use `--route film --chest N` for the old fixed list.

- Reaching the active chest (within `--arrive-meters` for `--arrive-seconds`), F or Ctrl-Opt-N's skip
  takes it off the plan; B / Ctrl-Opt-B restores the last one and keeps it first until it's dealt with.
- Standing within 6 m of any other regular or guaranteed spot for 1.5 s counts it as checked. Buried spots
  only count when they're the target (walking over one proves nothing).
- The target only switches when the new plan opens one more chest or saves 4 s, at most once per 3 s.
- New HUD snapshot fields: `planned` (chests in the current plan), `replanned` (snaps the metres),
  `ahead` ([turn°, metres] at 12/30/50 m down the path). `chest` = chests opened + 1, `total` = opened +
  planned. All old fields unchanged.

Measured on the 60 s PS5 test clip (`ps5-part1.mp4`, recorded footage, `--metrics out/steering/replan-ps5-part1.json`):
61 plans, 27 ms median, 34 ms p95, 37 ms max per plan, off the frame loop (frame to HUD p95 25 ms, same as
before). 14–19 chests per 2-minute plan. The target switched twice in 60 s. Six buried chests he dug were
each the active target when he reached them. Coverage 94%. The chest-to-chest travel table builds once in
~6 s and is cached in `data/cache/`.

What this doesn't prove: in this clip he was playing without the overlay, so the plan was following him, not
the other way round. Whether following the arrow opens more chests needs a real run over Remote Play. Fixed
along the way: holding the current target used to collapse the plan to that one chest (`ils_best` dropped
every candidate when the player's other edges were masked); it now plans onward from the held chest.

## Frozen route (`--route frozen`, DEFAULT since 2026-11-27 evening, `frozen.py`)

Plans the most chests in the next 2 minutes (same orienteering solver as `--route live`), then follows that plan like
a maps app instead of re-solving every second:

- **Between chests the plan doesn't change.** It is re-solved only when he is losing time on the leg (Dijkstra seconds
  to the arrow's chest now minus the best this leg, over 5 s for 2.5 s: standing still in a fight loses nothing), or
  the plan runs out. Every re-solve after the first logs "Rerouting" and the HUD shows REROUTING, but only if the
  arrow's chest changed.
- **When a chest is finished** the next stop is picked fresh from where he is. The arrow moves on then anyway, so it's
  never a visible flip, and it is why plans stay on chests near him (a 1-minute-old plan once sent him 153 m past two
  chests 29 and 31 m away).
- **CHEST NEARBY:** an unopened chest within 8 m, at most 60% as far as the arrow's chest, and at most 6 s of detour is
  slotted in first. It is kept until he is 16 m away or another chest is clearly closer; a dropped one can't come back
  for 8 s (unless within 5 m); nothing is slotted in while he moves faster than 1.3x running (gliding, cars).
- Walking past a chest spot drops it silently (never a reroute). Back pins a chest first and pauses rerouting.

Measured vs `--route live` (`compare_planners.py`, `out/steering/compare-v4-*.json`):

| | live (old default) | frozen |
|---|---|---|
| Drift test (his worry: wobble between two chests 25-50 m apart, 120 pairs): pairs where the arrow changed | 50.8% (107 changes) | **42.5% (74)** |
| Sim, follows the arrow, 12 starts: chests at 2 / 5 / 10 min | 22.5 / 52.2 / 98.6 | 22.0 / 51.8 / **100.2** |
| Sim, wanders off 20% of the time: chests at 10 min | **99.4** | 97.0 |
| Sim: chests within 8 m he was left standing next to (per 10 min) | 7.3 / 12.8 | **2.2 / 2.2** |
| Sim, wandering: arrow changes while still, per run | 1.7 | **0.8** |
| Replay of his real positions (7.5 min, not following any arrow): changes while still / all changes | 4 / **19** | **2** / 24 |
| Reroutes (replay) | n/a | 8, every one after he moved 44-131 m in 10 s |
| Plan time p50 / p95 (off the frame loop) | 36 / 57 ms | 32 / 47 ms |

Caveats: chests are a tie on average, but frozen's worst start is lower (77-78 vs 89-90 per 10 min: one early
different choice sends it to another area). The extra "all changes" on the replay are CHEST NEARBY moments where he
walked up to chests. End-to-end `live.py` on PS5 part 3 (recording): locks on, reaches chests, 0 reroutes. **Not yet
proven in a live game** (no PS5 until he's home).

### Expected chests, not spots (2026-11-28, live default)

Not every spot spawns a chest, so the planner now counts each spot as its spawn chance (`params.SPAWN_P`: guaranteed
and guaranteed rare 1.0, regular 0.60, buried 0.5 guess; sources in `params.py`) and maximises **expected chests** in
the 2 minutes, which sends him to sure chests first. `ils_best(..., prize=)` is the prize-collecting version (greedy
inserts the most expected chests per added second, also tries the plain least-time fill, swaps trade a regular for a
guaranteed when it fits); `prize=None` is the old count, bit-identical. `Planner(weighted=False)` = the old planner.

`compare_planners.py spawn`: every run first draws which spots really have a chest (per-kind chance, seeded); only
those open (2 s), an empty spot costs the walk plus 1 s. Same 12 starts x 4 spawn draws for both planners
(`out/steering/spawn-v3.json`):

| frozen, follows the arrow | count every spot (old) | expected chests (new) |
|---|---|---|
| Chests opened at 2 / 5 / 10 min | 14.8 / 36.5 / 70.0 | **16.0 / 37.1 / 72.1** (+8% / +2% / +3%) |
| Worst start vs old (mean of 4 draws, 10 min) | | -4.6% (8 starts better, 3 worse) |
| Plan time p50 / p95 | 33 / 48 ms | 35 / 50 ms |

If the real regular rate differs from the planner's 0.60 (12 starts x 3 draws, `spawn-v3-regular*.json`): at 0.45
+6.3% at 10 min, worst start -2.4%; at 0.67 only +1.3%, worst start **-8.9%** (6 of 12 starts worse).

Caveat: one early choice can still send a run to a different area, so single starts swing -5% to +20%. A softer
weighting (spawn chance ^ 0.5) was worse (+1% at 10 min) and isn't used.

## Full-map route prototype (`--route tour`, 2026-11-27, NOT the default)

`tour.py`: one open travelling-salesman path through all 1,006 spots (nearest-first, then 2-opt + Or-opt in numpy,
0.56-0.9 s), followed like a maps app: reroute only when >25 m off the leg path for 3 s, or a chest >50 m from it gets
dealt; a chest within 10 m that costs at most 6 s extra is slotted in first (`nearby` snapshot field, HUD "CHEST
NEARBY"); `rerouting` snapshot field shows the REROUTING card. `compare_planners.py` measures it against `replan.py`
(`replay` on real traces, `drift` = standing between two chests 25-50 m apart, `sim` = a simulated follower):
- Drift, 120 pairs: old planner changed chest in 51% (107 changes), tour 9% (14). (Before the nearby rule.)
- Replay, 7.5 min of his real movement (he followed no arrow): old 19 changes, 4 while he moved under 5 m, 15
  chests within 8 m ignored; tour 8 changes, 0 while still, 1 ignored (19 s detour), 5 reroutes, each after 68-132 m
  of movement in 10 s; 0 on the live-test trace. `out/steering/planner-compare-replay.json`.
- Sim, 10 min from 5 starts: old 99 chests (103 with 20% wandering), tour 90 (87). The tour must visit every
  outlier, so it opens ~10% fewer. Hence the next step: keep orienteering, freeze it maps-app style.
- MST lower bound: the tour is at most 19% longer than optimal (literature: 2-opt ~5% typical at 1,000 points).

## Arrow accuracy (measured 2026-11-27, test feed)

Measured on the clean PS5 recording (`ps5-part1.mp4`, first 60 s, 3,562 frames) with
`live.py --metrics` and then `python scripts/steering/accuracy.py out/steering/accuracy-ps5-part1.json`.
This is recorded footage, not a live Remote Play session; console, network and display lag are not in it.

- **Tracking coverage:** 3,348 of 3,562 frames (94%) had both heading and position.
- **Compass reading vs the number on screen:** 24 random frames checked by eye
  (`out/steering/accuracy/compass-check.png`): all 24 within 5°, most exact. Misses were 2–5° when a map
  marker sat on the digits.
- **Compass heading vs the direction he actually moved:** 13 independent ~2 s stretches of straight running
  (only 13 because he spent most of the clip looting or turning). Median 22°, p90 56°, 15% over 45°, signed
  median −2° (no bias). The compass shows where the camera looks, so camera swings while running count as
  error here; the screen check above shows the reading itself is right.
- **Arrow vs the path 12 m ahead:** 3,164 frames. Median 5°, p90 17°. Wrong way (over 90° off): 0%.
- **Lag inside the program:** frame to HUD p50 0.1 ms, p95 27 ms. Heading reading age p50 50 ms, p95 181 ms.
  Position age p50 198 ms, p95 384 ms (about 1 m of running at his median 3 m/s).
- **What this doesn't prove:** the arrow check compares the arrow with the tool's own path from its own
  position. Positions passed 0.2–1.3 m from chest spots he opened in this clip, but chest coordinates are
  only as good as the map data.
- **Not measurable:** up/down. The map has no height data, so the arrow can't say climb or drop.

## Runtime pipeline

`live.py` works from capture frames as they arrive. It keeps the latest frame,
reads the compass with a persistent Vision worker, tracks minimap position,
and runs the project's Dijkstra terrain graph when the player enters a new
cell or the active chest changes. The arrow points to a waypoint along that
path. The HUD's distance is to the chest. Use **F** for Found, **M** for
Missing, and **Q** to quit the preview.

Run a paced repeatable test against the original recording:

```bash
python scripts/steering/live.py --input "$recording" --start 8 --duration 16 \
  --chest 19 --mark 5 found --mark 10 missing --headless \
  --record out/steering/live-feed-test.mp4 --metrics out/steering/live-feed-metrics.json
```

Run a connected macOS capture device or a known video stream:

```bash
python scripts/steering/live.py --device <capture-device-index>
python scripts/steering/live.py --input "<video-stream-url>"
```

Connect the PlayStation to a Mac-visible HDMI capture source, or provide a
video stream URL carrying the gameplay. Allow macOS camera access for the
terminal if prompted for a device input. The crop is calibrated to the
existing recording's 16:9 HUD layout and minimap scale. A different HUD can
require recalibration. This is a Mac preview of the feed with the arrow
composited on it. Console input is independent.

The test uses a source file played at capture rate while all computer vision
and route calculations run on current frames. The measured overlay latency
is from frame delivery inside the process. It excludes capture hardware,
network, display, and console latency. This benchmark uses the recording.

The 16-second paced integration run processed 921 frames, accepted 123 compass
updates and 40 position updates, and solved ten paths. Median frame-to-overlay
time was 3.3 ms and the 95th percentile was 25.1 ms. On frames that updated
heading, the 95th percentile was 33.6 ms. The first cold frame took 527 ms
and was withheld by the freshness guard. Dijkstra calls took at most 4.7 ms
in this run. The arrow had usable tracking on 824 frames.

At 8.326 seconds into the excerpt, heading was 99°, the next path waypoint
was at 255°, and the chest itself was at 228°. The cue commanded a 156°
right turn toward the waypoint. The injected Found and Missing actions each
changed the active chest and recomputed the path on the same processed frame.

## PlayStation Remote Play window

1. Connect to the PS5 in the native PS Remote Play app. Open Fortnite and keep
   the gameplay window unminimized at a fixed size during the test.
2. In Terminal, run the preview. The helper selects only the Remote Play
   window and captures video frames without audio.

   ```bash
   cd /Users/silas/Developer/fortnite-chest-route
   .venv/bin/python scripts/steering/live.py --remote-play --chest 1
   ```

3. If macOS prompts, allow Terminal under **System Settings → Privacy &
   Security → Screen & System Audio Recording** and reopen Terminal. The
   overlay appears in a separate Mac preview window. Focus that preview to
   use **F**, **M**, and **Q**. Keep controller input directed to Remote Play.

For explicit window selection, run
`.venv/bin/python scripts/steering/live.py --list-windows`, choose the ID of the
gameplay window, and use `--window-id ID` in place of `--remote-play`.
Start with a clean 16:9 gameplay image and dismiss connection or toolbar
overlays. If the HUD has bars or offset framing, `--window-crop W:H:X:Y`
selects the gameplay rectangle in the captured image normalized to 1920
pixels wide. The default tries to remove an extra title bar above 16:9
gameplay. Restart capture after resizing the window.

Verified selective capture by replaying the existing Fortnite clip in
a standalone local window, then passing only that window through the runtime
OCR, minimap tracker, Dijkstra, and compositing pipeline. The 14-second
run processed 294 frames, had 260 tracked frames, and computed nine paths.
The waypoint bearing differed from the chest bearing by up to 27°.
Frame delivery to overlay p95 was 28 ms inside Python. The measurements
exclude the console, Remote Play network path, and ScreenCaptureKit itself.
See `out/steering/window-feed-test.mp4` and
`out/steering/window-feed-metrics.json`. The later console test is described below.

### Draw directly over Remote Play

Use the click-through HUD to keep Remote Play focused while the arrow is drawn
over the gameplay window:

```bash
cd /Users/silas/Developer/fortnite-chest-route
.venv/bin/python scripts/steering/live.py --remote-play --hud --chest 1
```

The HUD appears once the compass and minimap are tracked. While tracking is
stale it drops the arrow and shows "FINDING SIGNAL" for up to 8 seconds, then
fades out until the next lock. Stop the runner with Control-C in Terminal. The active chest
moves on by itself after the player stays within `--arrive-meters` (default 8)
of it for `--arrive-seconds` (default 1.5; 0 turns this off). While Remote Play
keeps focus, **Control-Option-N** skips to the next chest and
**Control-Option-B** goes back one (Carbon hot keys, no Accessibility
permission). On the 36-second recording, chest 19 never came within 8 m (closest
11 m) and the run stayed on it; with a 16 m radius it advanced once, at 29.8 s.
The hot keys are untested on the console. The capture helper favors an on-screen Remote
Play window, normalizes the stream's black bars, and retries a temporary
capture disconnect.

On PS5, turn on **Settings → System → Remote Play → Hide Remote Play
Connection Status**. During the console test, that banner overlapped the
Fortnite compass and caused frequent heading loss. [PlayStation Remote
Play support](https://www.playstation.com/en-au/support/games/playstation-remote-play-on-pc-and-mac/)

The two-minute PS5 match test processed 2,996 frames at about 25 fps and
showed the click-through HUD above the Remote Play window while tracking
was available. The compass banner limited full tracking to 291 frames.
The first lock had a 7° heading, 139° path waypoint and 74° direct chest
bearing. Frame delivery to overlay p95 was 55 ms inside the process.
Capture recovered after Remote Play stream interruptions. Coverage after
disabling the banner remains unverified.

## Film with HDMI passthrough

Connect **PS5 HDMI OUT → capture card HDMI IN → capture card HDMI OUT → TV**.
Connect the card's USB cable to the Mac. Play on the TV with the DualSense
paired to the PS5. The Mac preview and recording receive the captured copy.
For gameplay capture, disable **Settings → System → HDMI → Enable HDCP** on
the PS5. Start with a 16:9 1080p SDR feed for the calibrated HUD crops.

List the video devices in Terminal and identify the capture card index.
Allow Terminal camera access if prompted. FFmpeg exits after printing the list.

```bash
cd /Users/silas/Developer/fortnite-chest-route
ffmpeg -f avfoundation -list_devices true -i ""
```

Replace `DEVICE_INDEX` with the capture card index and verify that the
preview shows Fortnite.

```bash
.venv/bin/python scripts/steering/live.py --device DEVICE_INDEX --chest 1 \
  --record-fps 60 --record out/steering/wired-take.mp4 \
  --metrics out/steering/wired-take-metrics.json
```

Use **F** and **M** in the Mac preview to advance the active chest. Press
**Q** to stop and finalize the MP4. The output has a 60 fps timeline and
repeats the latest available frame when capture or processing runs below
60 fps. It is a 720p overlay video without audio. Capture game audio
separately if it is needed for the edit.

## Themed HUD (Pirate Token Hunt)

`window_hud.swift` draws the whole look in code with macOS system fonts
(Futura Condensed ExtraBold, Avenir Next Condensed Heavy Italic). No game
assets, icons or fonts are used. The same binary draws the live click-through
panel and, with `--render W H`, raw frames for `live.py --record` and the
preview window, so recordings match the live HUD.

What makes a HUD read as native to this game, from the test footage and a
short look at HUD and stream-overlay write-ups:

- Heavy condensed capitals with a slight forward lean, white or yellow, with a
  dark edge and soft drop shadow so they hold on sand, sky and water.
- Text mostly floats on the picture. Panels are dark navy and see-through, and
  boxes lean (parallelograms), they are rarely upright rectangles.
- Saturated colour carries meaning: gold and orange for the best loot, blue and
  green for shield and health, white for neutral numbers.
- Icons are chunky with a dark outline and one highlight, no thin strokes.
- Distances are short numbers with a small "m" next to a pin, and pins also
  ride on the compass strip.
- Motion is quick and bouncy: a scale pop, a flash sweep, then still.
- Overlay guides agree on keeping clear of the game's own HUD, staying under
  about 70% panel opacity, and checking the result at phone size.

Pieces, all in a 1280x720 design space scaled to the gameplay rectangle:

- Card under the compass (his pick, 2026-11-27): gold compass dial with ONE solid 3D arrow, `PIRATE TOKEN HUNT`,
  `NEXT CHEST`, distance, turn wording (`STRAIGHT AHEAD` under 15°, `SLIGHT` under 45°, `TURN`, `BEHIND YOU` over
  135°) and a heat bar that fills over the leg. No chest counting (no N/total, no chest number, no tick row).
  The plate stops at x=796 so it clears the storm banner.
- Arrow: an extruded block arrow lying on a tilted ground plane (lit top, darker side walls, ground shadow),
  rotated by `turn`, which aims at the path point 12 m ahead. `style` is accepted and ignored. Height is not
  shown: no public source has chest heights for this map (see the shared research note).
- Closeness: far off (60 m+) the arrow is long and skinny; nearer it gets shorter and stubbier and glows more.
  The metres grow and pulse faster, and the card floods navy → gold → orange → hot orange (not red: red means
  danger in Fortnite). Metres ease over ~0.3 s, snap on a new target, and hold dimmed when tracking drops.
  Under 5 m it switches to the token and `DIG HERE!` / `OPEN IT!`.
- Compass pin: a token under the strip at the chest's straight-line bearing.
  Measured on `gameplay.mp4`: N, NE, E, SE labels sit 106.9 px apart at 1280
  wide, so 2.375 px per degree (3.5625 at 1920), centre x 639. Beyond 80° it
  parks at the strip's edge with a chevron.
- Minimap: the Dijkstra path and a chest token, clamped to the minimap edge
  when the chest is off it.
- A chest reached or marked found plays a pop: ring, sparks, gold sweep and
  `CHEST OPENED!`. `--hud-scale` resizes the card (0.6 to 1.6); use 1.4+ for the reel, since at
  phone size viewers read the number but not the arrow's shape.

The arrow, pin and minimap position are smoothed (0.10 s, 0.10 s and 0.22 s
time constants) and redrawn at 60 Hz between the 20 Hz snapshots.

Snapshot fields added to the HUD protocol, all optional (the first protocol's
`window`, `chest`, `turn`, `meters` still works): `tracked`, `done`, `total`,
`opened`, `kind`, `heading`, `bearing`, `player`, `target`, `path`, `mini`,
`compass`, `game`, `mpu`, `scale`, `style`, `t`, and `ahead` (`[turn, metres]`
points down the path; worked out from `path` when absent) and `replanned`
(the old ROUTE UPDATED label is gone; `rerouting` shows the REROUTING card). `ahead` and `replanned` are read leniently: an
unexpected shape is treated as absent.

Check the look without a console:

```bash
cd scripts/steering
../../.venv/bin/python hud_states.py ../../out/steering/gameplay.mp4 ../../out/steering/hud-states
cd ../..
.venv/bin/python scripts/steering/live.py --input out/steering/gameplay.mp4 --chest 19 \
  --arrive-meters 16 --headless --record-fps 30 --record out/steering/hud-themed.mp4
```

`hud_states.py` writes eight states, `closeness.png` (40, 25, 15 and 6 m), `closeness-phone.png` and
`approach-arrow.mp4` (60 m down to 4 m).

### Verified on recordings (2026-11-27)

- `gameplay.mp4`, 36 s, chest 19, 16 m arrival radius: 969 of 1,070 frames
  tracked, chest 19 reached once and the pop played. Spot checks of rendered
  frames against the compass in the same frame: at 12.0 s heading 70°, waypoint
  93°, arrow 23° right; at 24.0 s heading 126°, waypoint 113°, arrow 13° left;
  at 28.5 s heading 98°, chest pin drawn 15° right of the heading mark.
- `accuracy.py` on the first 60 s of a clean PS5 capture: see **Arrow accuracy** near the top
  (the movement check now uses ~2 s straight stretches instead of 1 s windows).
- The arrow check compares the arrow with the tool's own path from its own
  position estimate. It does not prove the position or the chest coordinates
  are right in the world. In both recordings the player dug up chests while
  the HUD still showed 29 to 70 m to its active chest.
- Two fresh viewers judged frames and the clip. The first misread the old
  dart-shaped arrow as disagreeing with the turn wording; the arrow now has a
  head and shaft. The second and third found nothing serious. The third said
  closeness only showed in the number; the halo and closing ring were added
  after that and have not been in front of a viewer.
- Not verified: the live panel on screen over PS Remote Play (placement on the
  gameplay rectangle, 60 Hz redraw cost, the hot keys). The live binary was
  only fed snapshots with no matching window and exited cleanly.
