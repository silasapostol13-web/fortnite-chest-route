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
network, display, and console latency. Physical PlayStation capture remains
untested.

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
