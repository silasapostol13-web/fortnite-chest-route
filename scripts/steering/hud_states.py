"""Render the HUD's main states over one gameplay frame, without a console or tracking.

    python scripts/steering/hud_states.py out/steering/gameplay.mp4 out/steering/hud-states

Writes one PNG per state and a contact sheet. Uses the same Swift drawing code as the live HUD.
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


STYLES = ("ribbon", "arrow", "cutlass")
# The same three moments for every style: nearly straight, a right turn that bends back left, and chest behind.
MOMENTS = (
    {"turn": 8, "ahead": [[8, 12], [6, 30], [5, 50]], "bearing": 76, "meters": 61},
    {"turn": 55, "ahead": [[55, 12], [38, 27], [12, 42]], "bearing": 84, "meters": 88},
    {"turn": -150, "ahead": [[-150, 12], [-128, 29], [-105, 47]], "bearing": 300, "meters": 140, "target": [1060, 400], "path": None},
)


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

    # The three arrow styles side by side on the same moments: one row per style, one column per moment.
    rows = []
    for style in STYLES:
        row = []
        for changes in MOMENTS:
            renderer = HudRenderer(binary)
            for step in range(45):
                image = renderer.composite(frame.copy(), {**BASE, **changes, "style": style, "t": step / 30})
            renderer.close()
            row.append(cv2.resize(image[30:170, 425:815], None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC))
        rows.append(np.hstack(row))
        cv2.imwrite(str(args.output / f"style-{style}.png"), rows[-1])
    cv2.imwrite(str(args.output / "styles.png"), np.vstack(rows))

    # How each style shows the chest getting closer: 40 m, 15 m, 6 m. (At 5 m every style flips to DIG HERE.)
    rows = []
    for style in STYLES:
        row = []
        for meters in (40, 15, 6):
            renderer = HudRenderer(binary)
            for step in range(52):
                image = renderer.composite(frame.copy(), {**BASE, **MOMENTS[0], "meters": meters, "style": style, "t": step / 30})
            renderer.close()
            row.append(cv2.resize(image[30:170, 425:815], None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC))
        rows.append(np.hstack(row))
        cv2.imwrite(str(args.output / f"closeness-{style}.png"), rows[-1])
    cv2.imwrite(str(args.output / "closeness.png"), np.vstack(rows))
    print(f"Wrote {len(tiles)} states to {args.output}.")


if __name__ == "__main__":
    main()
