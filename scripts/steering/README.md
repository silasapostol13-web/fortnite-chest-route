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
