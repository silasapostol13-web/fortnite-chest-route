"""Render a fixed-waypoint steering demo over the recorded clip."""

import argparse
from bisect import bisect_left
import json
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np


def wrap(angle):
    return (angle + 180) % 360 - 180


def sampler(rows, gap, angular=False):
    times = [row[0] for row in rows]

    def sample(t):
        i = bisect_left(times, t)
        if i == 0 or i == len(rows):
            row = rows[min(i, len(rows) - 1)]
            return row[1:] if abs(t - row[0]) < .20 else None
        a, b = rows[i - 1], rows[i]
        if t == b[0]:
            return b[1:]
        if b[0] - a[0] > gap:
            return None
        weight = (t - a[0]) / (b[0] - a[0])
        if angular:
            return [(a[1] + weight * wrap(b[1] - a[1])) % 360]
        return [x + weight * (y - x) for x, y in zip(a[1:], b[1:])]

    return sample


def steering(position, heading, target):
    dx, dy = target[0] - position[0], target[1] - position[1]
    bearing = degrees(atan2(dx, -dy)) % 360
    return bearing, wrap(bearing - heading), hypot(dx, dy) * 1.7


def paint(frame, position, heading, target, number):
    h, w = frame.shape[:2]
    cx, cy = w // 2, int(h * .20)
    gold = (69, 211, 255)
    ink = (15, 26, 38)
    cream = (235, 248, 255)
    patch = frame[cy - 43:cy + 44, cx - 138:cx + 138]
    cv2.addWeighted(patch, .14, np.full_like(patch, ink), .86, 0, dst=patch)
    cv2.line(frame, (cx - 138, cy - 43), (cx + 137, cy - 43), gold, 2, cv2.LINE_AA)
    cv2.circle(frame, (cx - 96, cy), 32, gold, 1, cv2.LINE_AA)
    label = f"PIRATE TOKEN HUNT"
    status = "TRACKING LOST"
    if position is not None and heading is not None:
        _, turn, distance = steering(position, heading, target)
        if distance > 5:
            angle = radians(turn)
            shape = np.array([(0, -22), (15, 14), (0, 7), (-15, 14)])
            transform = np.array([[cos(angle), -sin(angle)], [sin(angle), cos(angle)]])
            arrow = np.rint(shape @ transform.T + (cx - 96, cy)).astype("int32")
            cv2.fillConvexPoly(frame, arrow, gold, cv2.LINE_AA)
            direction = "AHEAD" if abs(turn) < 12 else "RIGHT" if turn > 0 else "LEFT"
            status = f"{direction}  |  ~{round(distance)} m"
        else:
            cv2.circle(frame, (cx - 96, cy), 6, gold, -1, cv2.LINE_AA)
            status = "SEARCH AREA"
    cv2.putText(frame, label, (cx - 53, cy - 12), cv2.FONT_HERSHEY_SIMPLEX, .41, gold, 1, cv2.LINE_AA)
    cv2.putText(frame, f"CHEST {number:02d}", (cx - 53, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, .68, cream, 2, cv2.LINE_AA)
    cv2.putText(frame, status, (cx - 53, cy + 30), cv2.FONT_HERSHEY_SIMPLEX, .45, cream, 1, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--chest", type=int, default=19)
    args = parser.parse_args()
    data = json.loads(args.telemetry.read_text().partition("=")[2].strip().removesuffix(";"))
    target = data["waypoints"][args.chest - 1]
    position_at = sampler(data["positions"], .76)
    heading_at = sampler(data["headings"], .35, angular=True)
    capture = cv2.VideoCapture(str(args.clip))
    if not capture.isOpened():
        raise SystemExit("Could not open gameplay clip")
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / "overlay.mp4"
        with subprocess.Popen([
            "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
            "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-pix_fmt", "yuv420p", str(silent),
        ], stdin=subprocess.PIPE) as encoder:
            i = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                t = i / fps
                yaw = heading_at(t)
                paint(frame, position_at(t), yaw[0] if yaw else None, target, args.chest)
                encoder.stdin.write(frame.tobytes())
                i += 1
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise SystemExit("Overlay encoding failed")
        capture.release()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(args.clip),
                        "-map", "0:v", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart",
                        "-shortest", str(args.output)], check=True)


if __name__ == "__main__":
    main()
