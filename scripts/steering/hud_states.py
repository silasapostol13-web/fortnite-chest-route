"""Render the HUD's main states over one gameplay frame, without a console or tracking.

    python scripts/steering/hud_states.py out/steering/gameplay.mp4 out/steering/hud-states

Writes one PNG per state, a contact sheet, the arrow at four distances (closeness.png, and closeness-phone.png at
about phone size) and approach-arrow.mp4 (60 m down to the chest). Uses the same Swift drawing code as the live HUD.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Gameplay video or image")
    parser.add_argument("output", type=Path, help="Folder for the PNGs")
    parser.add_argument("--at", type=float, default=14, help="Seconds into the video")
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.source))
    capture.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = capture.read()
    if not ok:
        raise SystemExit("Couldn't read a frame from the source.")
    frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    args.output.mkdir(parents=True, exist_ok=True)
    binary = hud_binary()
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
    approach(binary, frame, args.output / "approach-arrow.mp4")
    print(f"Wrote {len(tiles)} states to {args.output}.")

if __name__ == "__main__":
    main()
