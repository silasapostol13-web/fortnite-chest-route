"""Render the HUD's main states over one gameplay frame, without a console or tracking.

    python scripts/steering/hud_states.py out/steering/gameplay.mp4 out/steering/hud-states

Writes one PNG per state, a contact sheet, the arrow at four distances (closeness.png, and closeness-phone.png at
about phone size), approach-arrow.mp4 (60 m down to the chest) and the REROUTING moment (rerouting.png,
rerouting-phone.png, rerouting-phone-small.png, rerouting-frames/ and rerouting.mp4), plus the pirate token up close (token-*.png;
`--only token` writes just those). Uses the same Swift drawing
code as the live HUD. `--only rerouting` writes just that last set.
"""

import argparse
from pathlib import Path
import subprocess

import cv2
import numpy as np

from live import HudRenderer, hud_binary

BASE = {"chest": 19, "total": 33, "opened": 18, "kind": "buried", "tracked": True, "turn": 60, "meters": 42,
        "heading": 70, "bearing": 118, "player": [1134, 442], "target": [1168.8, 440.5],
        "path": [[1134, 442], [1142.5, 447.5], [1152.5, 452.5], [1162.5, 447.5], [1168.8, 440.5]]}
# name -> list of (seconds, changes). The last entry is the frame that gets saved.
STATES = {
    "1-turn-right": [(0, {}), (2, {})],
    "2-turn-left": [(0, {"turn": -95, "bearing": 330, "meters": 118, "target": [1040, 380], "path": None}), (2, {})],
    "3-straight-ahead": [(0, {"turn": 3, "bearing": 74, "meters": 23}), (2, {})],
    "4-behind": [(0, {"turn": 170, "bearing": 240, "meters": 64, "target": [1100, 470], "path": None}), (2, {})],
    "5-dig-here": [(0, {"turn": 10, "meters": 3, "bearing": 80, "target": [1136, 441], "path": None}), (2.1, {})],
    "6-chest-opened": [(0, {}), (2, {}), (2.2, {"chest": 20, "opened": 19, "kind": "guaranteed", "meters": 96, "turn": -40})],
    "7-finding-signal": [(0, {}), (2, {}), (3.4, {"tracked": False, "turn": None, "meters": None})],
    "9-chest-nearby": [(0, {}), (2, {"nearby": True, "kind": "regular", "turn": -35, "bearing": 35, "meters": 7,
                                  "target": [1130, 438], "path": None})],
    "8-route-complete": [(0, {}), (2, {}), (4, {"tracked": False, "done": True, "chest": 33, "opened": 33, "turn": None})],
}


CLOSENESS = (40, 25, 15, 6)             # metres shown in closeness.png, one column each


def approach(binary, frame, output, seconds=6.0, fps=30):
    """Walking in from 60 m to 4 m with the arrow swinging a little, then a second of DIG HERE.
    Top: the card at 2x. Bottom: the whole frame at phone width, to judge it at the size it is watched."""
    encoder = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "960x568",
                                "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(output)],
                               stdin=subprocess.PIPE)
    renderer = HudRenderer(binary)
    for step in range(int((seconds + 1.5) * fps)):
        t = step / fps
        meters = round(60 - 56 * min(t / seconds, 1))
        turn = 28 * np.cos(t * 1.4) * max(0.15, 1 - t / seconds)
        image = renderer.composite(frame.copy(), {**BASE, "turn": turn, "bearing": 70 + turn, "meters": meters, "t": t})
        canvas = np.zeros((568, 960, 3), np.uint8)
        canvas[:340] = cv2.resize(image[20:190, 400:880], (960, 340), interpolation=cv2.INTER_CUBIC)
        canvas[340:, 277:683] = cv2.resize(image, (406, 228), interpolation=cv2.INTER_AREA)
        encoder.stdin.write(canvas.tobytes())
    renderer.close()
    encoder.stdin.close()
    encoder.wait(timeout=60)


def token_frames(binary, frame, output):
    """The pirate token up close: the card at 2x over the whole frame at phone width, at 40, 15 and 6 m,
    and the pin under the compass strip (4x close-up beside the strip at its real size)."""
    for meters in (40, 15, 6):
        renderer = HudRenderer(binary)
        for step in range(75):
            image = renderer.composite(frame.copy(), {**BASE, "turn": 8, "bearing": 78, "meters": 90 if step == 0 else meters,
                                                      "t": step / 30})
        renderer.close()
        canvas = np.zeros((568, 960, 3), np.uint8)
        canvas[:340] = cv2.resize(image[20:190, 400:880], (960, 340), interpolation=cv2.INTER_CUBIC)
        canvas[340:, 277:683] = cv2.resize(image, (406, 228), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(output / f"token-{meters}m.png"), canvas)
    x = int(round((958.5 + 8 * 3.5625) / 1.5))          # where the pin sits for a chest 8 degrees to the right
    close = cv2.resize(image[8:68, x - 40:x + 40], (640, 480), interpolation=cv2.INTER_CUBIC)
    strip = np.zeros((480, 640, 3), np.uint8)
    strip[180:300] = image[0:120, 320:960]
    cv2.imwrite(str(output / "token-compass.png"), np.hstack([close, strip]))


# He leaves the route at 2.0 s: live.py sends `rerouting` for 1.5 s and `replanned` for 0.3 s, and the target changes.
REROUTE_AT = 2.0
REROUTED = {"turn": -70, "bearing": 0, "meters": 58, "target": [1128, 398], "kind": "guaranteed",
            "path": [[1134, 442], [1126, 432], [1120, 418], [1124, 406], [1128, 398]]}
REROUTE_SHOTS = ((1.9, "BEFORE"), (2.1, "0.1 s"), (2.55, "0.55 s"), (3.0, "1.0 s"), (3.6, "1.6 s"), (5.4, "AFTER"))


def reroute_snapshot(t, scale):
    state = {**BASE, "scale": scale, "t": t}
    if t >= REROUTE_AT:
        state.update(REROUTED, rerouting=t < REROUTE_AT + 1.5, replanned=t < REROUTE_AT + .3)
    return state


def rerouting(binary, source, output, start=6.6, fps=30, seconds=6.0):
    """The REROUTING moment: before, three moments inside it, the new route landing, and settled.
    rerouting.png is the card at the default size (2x crops); the phone files and the clip use the reel's 1.4 card.
    The gameplay under it plays on from `start` (he is running there). The HUD values are made up, not tracked."""
    capture = cv2.VideoCapture(str(source))
    capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    plates = []
    for _ in range(int(seconds * fps) + 1):
        ok, plate = capture.read()
        if not ok:
            raise SystemExit("The source is too short for the rerouting clip.")
        plates.append(cv2.resize(plate, (1280, 720), interpolation=cv2.INTER_AREA))
    shots = {}
    for scale in (1.0, 1.4):
        renderer = HudRenderer(binary)
        encoder = None
        if scale == 1.4:
            encoder = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1280x720",
                                        "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                                        str(output / "rerouting.mp4")], stdin=subprocess.PIPE)
        for step in range(int(seconds * fps) + 1):
            t = step / fps
            image = renderer.composite(plates[step].copy(), reroute_snapshot(t, scale))
            if encoder:
                encoder.stdin.write(image.tobytes())
            for at, name in REROUTE_SHOTS:
                if abs(t - at) < .5 / fps:
                    shots[scale, name] = image
        renderer.close()
        if encoder:
            encoder.stdin.close()
            encoder.wait(timeout=60)

    def captioned(image, name):
        cv2.rectangle(image, (0, image.shape[0] - 34), (150, image.shape[0]), (20, 12, 6), -1)
        cv2.putText(image, name, (10, image.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2, cv2.LINE_AA)
        return image

    names = [name for _, name in REROUTE_SHOTS]
    cards = [captioned(cv2.resize(shots[1.0, name][20:190, 400:880], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), name)
             for name in names]
    cv2.imwrite(str(output / "rerouting.png"), np.vstack([np.hstack(cards[i:i + 3]) for i in (0, 3)]))
    # Whole frames as a reel shows them: the game filling a 1080-wide screen. The small one is about what a phone shows.
    frames = output / "rerouting-frames"
    frames.mkdir(exist_ok=True)
    phone = []
    for index, name in enumerate(names):
        image = cv2.resize(shots[1.4, name], (1080, 608), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(frames / f"{index + 1}.png"), image)
        phone.append(captioned(image.copy(), name))
    sheet = np.vstack(phone)
    cv2.imwrite(str(output / "rerouting-phone.png"), sheet)
    cv2.imwrite(str(output / "rerouting-phone-small.png"), cv2.resize(sheet, None, fx=.375, fy=.375, interpolation=cv2.INTER_AREA))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Gameplay video or image")
    parser.add_argument("output", type=Path, help="Folder for the PNGs")
    parser.add_argument("--at", type=float, default=14, help="Seconds into the video")
    parser.add_argument("--only", choices=["rerouting", "token"], help="Write just this set")
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.source))
    capture.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = capture.read()
    if not ok:
        raise SystemExit("Couldn't read a frame from the source.")
    frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    args.output.mkdir(parents=True, exist_ok=True)
    binary = hud_binary()
    if args.only == "rerouting":
        rerouting(binary, args.source, args.output)
        print(f"Wrote the rerouting frames and clip to {args.output}.")
        return
    if args.only == "token":
        token_frames(binary, frame, args.output)
        print(f"Wrote the token frames to {args.output}.")
        return
    tiles = []
    for name, steps in STATES.items():
        renderer = HudRenderer(binary)
        state, image, clock = dict(BASE), frame, 0.0
        for seconds, changes in steps:
            state.update(changes)
            while clock <= seconds:                      # advance at 30 fps so smoothing and pops play out
                image = renderer.composite(frame.copy(), {**{k: v for k, v in state.items() if v is not None}, "t": clock})
                clock += 1 / 30
        renderer.close()
        cv2.imwrite(str(args.output / f"{name}.png"), image)
        tiles.append(cv2.resize(image[0:230, 330:1280], None, fx=.8, fy=.8, interpolation=cv2.INTER_AREA))
    if len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))       # keep the two-wide grid even
    sheet = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
    cv2.imwrite(str(args.output / "sheet.png"), sheet)

    # How the arrow shows the chest getting closer. The leg starts at 90 m so the heat bar has something to fill.
    # (At 5 m it flips to DIG HERE.)
    row = []
    for meters in CLOSENESS:
        renderer = HudRenderer(binary)
        for step in range(75):
            image = renderer.composite(frame.copy(), {**BASE, "turn": 8, "bearing": 78, "meters": 90 if step == 0 else meters,
                                                      "t": step / 30})
        renderer.close()
        row.append(cv2.resize(image[30:178, 425:815], None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC))
    sheet = np.hstack(row)
    cv2.imwrite(str(args.output / "closeness.png"), sheet)
    # The same row with each card about as big as it is on a phone showing the full 16:9 frame.
    cv2.imwrite(str(args.output / "closeness-phone.png"), cv2.resize(sheet, None, fx=.2, fy=.2, interpolation=cv2.INTER_AREA))
    token_frames(binary, frame, args.output)
    approach(binary, frame, args.output / "approach-arrow.mp4")
    rerouting(binary, args.source, args.output)
    print(f"Wrote {len(tiles)} states to {args.output}.")

if __name__ == "__main__":
    main()
