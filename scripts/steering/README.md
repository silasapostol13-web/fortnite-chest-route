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

The HUD appears once the compass and minimap are tracked, and disappears while
tracking is stale. Stop the runner with Control-C in Terminal. The active chest
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
