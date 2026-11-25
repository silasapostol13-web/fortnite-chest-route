"""Extract position and compass telemetry from the calibrated PS footage."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HEAD_RATE = 12
MAP_RATE = 2


def land(image):
    b, g, r = cv2.split(image.astype("float32"))
    return ((r > b * .82) & (g > b * .95) & (b < 223)).astype("float32")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, default=8)
    parser.add_argument("--duration", type=float, default=36)
    args = parser.parse_args()
    atlas = cv2.imread(str(ROOT / "planner" / "map.webp"))
    if atlas is None:
        raise SystemExit("Missing planner/map.webp")
    mask = land(atlas)
    route_js = (ROOT / "planner" / "film-route.js").read_text()
    route = json.loads(route_js.partition("=")[2].strip().removesuffix(";"))
    with tempfile.TemporaryDirectory(prefix="fortnite-steering-") as tmp:
        tmp = Path(tmp)
        binary = tmp / "ocr"
        subprocess.run(["swiftc", str(Path(__file__).with_name("read_compass.swift")), "-o", str(binary)], check=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-ss", str(args.start), "-t", str(args.duration), "-i", str(args.video),
            "-filter_complex",
            f"[0:v]split=2[h][m];[h]fps={HEAD_RATE},crop=78:32:921:14,scale=390:160:flags=lanczos[head];"
            f"[m]fps={MAP_RATE},crop=248:240:1638:36[mini]",
            "-map", "[head]", str(tmp / "heading-%04d.png"),
            "-map", "[mini]", str(tmp / "position-%04d.png"),
        ], check=True)
        headings = []
        frames = sorted(tmp.glob("heading-*.png"))
        for offset in range(0, len(frames), 240):
            lines = subprocess.check_output([binary, *frames[offset:offset + 240]], text=True).splitlines()
            for line in lines:
                filename, _, label = line.partition("\t")
                index = int(filename.removesuffix(".png").split("-")[-1]) - 1
                reading = re.fullmatch(r"[^0-9A-Za-z]*(\d{1,3})[^0-9A-Za-z]*", label.strip())
                if reading and int(reading[1]) <= 360:
                    headings.append([index / HEAD_RATE, int(reading[1]) % 360])

        positions = []
        for index, path in enumerate(sorted(tmp.glob("position-*.png"))):
            template = cv2.resize(land(cv2.imread(str(path))), None, fx=.99, fy=.99, interpolation=cv2.INTER_AREA)
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED))
            if score >= .62:
                positions.append([index / MAP_RATE, round((x + 122 * .99) * 1500 / mask.shape[1], 2),
                                  round((y + 121 * .99) * 1500 / mask.shape[0], 2), round(score, 3)])

    # Reject isolated OCR readings inconsistent with adjacent frames.
    def turn(a, b):
        return abs((a - b + 180) % 360 - 180)

    def plausible(a, b):
        return turn(a[1], b[1]) <= 9 + 540 * abs(a[0] - b[0])

    cleaned = []
    for i, reading in enumerate(headings):
        neighbors = headings[max(i - 1, 0):i] + headings[i + 1:i + 2]
        if any(abs(sample[0] - reading[0]) <= .25 and plausible(sample, reading) for sample in neighbors):
            cleaned.append(reading)

    if not positions or not cleaned:
        raise SystemExit("No usable telemetry. Check the source clip and crop calibration.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sourceStart": args.start, "duration": args.duration, "headings": cleaned,
               "positions": positions, "waypoints": route["chests"]}
    args.output.write_text("window.STEERING_DATA=" + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"Position samples: {len(positions)}. Compass readings: {len(cleaned)}/{len(headings)} accepted.")


if __name__ == "__main__":
    main()
