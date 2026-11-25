"""Runtime Fortnite steering from a macOS window, camera, stream or paced file."""

import argparse
from base64 import b64encode
import json
from math import dist
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from threading import Condition, Event, Thread
from time import monotonic

import cv2
import numpy as np

from render import steering
from track import land

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from route import params, planner_source
from route.travel import LegPather, cell_of


class WindowInput:
    """Decode the ScreenCaptureKit helper protocol into gameplay frames."""

    def __init__(self, helper, selection, crop):
        self.command = [helper, selection]
        self.configured_crop = crop
        self.stopped = Event()
        self.process = None
        if not self.connect():
            raise SystemExit("Unable to start window capture. See the capture diagnostic above.")

    def connect(self):
        self.process = subprocess.Popen(self.command, stdout=subprocess.PIPE)
        header = self.process.stdout.readline().split()
        if len(header) != 3:
            self.close_process()
            return False
        self.width, self.height, self.window_id = map(int, header)
        self.crop = self.configured_crop
        if self.crop:
            w, h, x, y = self.crop
            if min(w, h) <= 0 or min(x, y) < 0 or x + w > self.width or y + h > self.height:
                self.close_process()
                raise SystemExit(f"Window crop must fit inside the {self.width}x{self.height} captured image.")
        return True

    def read(self):
        for attempt in range(7):
            if self.stopped.is_set():
                return False, None
            if self.process is None and not self.connect():
                self.stopped.wait(.4)
                continue
            count = self.width * self.height * 4
            raw = self.process.stdout.read(count)
            if len(raw) == count:
                break
            self.close_process()
            if attempt == 0 and not self.stopped.is_set():
                print("Window stream interrupted. Reopening the selected window.", file=sys.stderr, flush=True)
            self.stopped.wait(.25)
        else:
            return False, None
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 4)
        if self.crop:
            w, h, x, y = self.crop
            frame = frame[y:y + h, x:x + w]
        elif self.height * 16 != self.width * 9:
            self.crop = gameplay_rectangle(frame)
            w, h, x, y = self.crop
            print(f"Using gameplay crop {w}:{h}:{x}:{y}.", file=sys.stderr)
            frame = frame[y:y + h, x:x + w]
        return True, cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def interrupt(self):
        self.stopped.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()

    def close_process(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            process.stdout.close()

    def release(self):
        self.stopped.set()
        self.close_process()


def gameplay_rectangle(frame):
    """Fit centrally letterboxed gameplay or trim a lone macOS title bar."""
    height, width = frame.shape[:2]
    if height * 16 > width * 9:
        game_height = width * 9 // 16
        extra = height - game_height
        dark_top = np.mean(frame[:8, :, :3].max(axis=2) < 16) > .95
        dark_bottom = np.mean(frame[-8:, :, :3].max(axis=2) < 16) > .95
        y = extra // 2 if dark_top and dark_bottom else 0 if dark_bottom else extra
        return width, game_height, 0, y
    game_width = height * 16 // 9
    return game_width, height, (width - game_width) // 2, 0


class Feed:
    """Keep only the newest capture frame so failed OCR can't queue old video."""

    def __init__(self, capture, paced):
        self.capture = capture
        self.paced = paced
        self.fps = (capture.get(cv2.CAP_PROP_FPS) or 30) if paced else 30
        self.condition = Condition()
        self.stop = Event()
        self.packet = None
        self.done = False
        self.worker = Thread(target=self.read_frames, daemon=True)
        self.worker.start()

    def read_frames(self):
        sequence = 0
        start = monotonic()
        try:
            while not self.stop.is_set():
                ok, frame = self.capture.read()
                if not ok:
                    break
                media_time = sequence / self.fps
                if self.paced and self.stop.wait(max(0, start + media_time - monotonic())):
                    break
                with self.condition:
                    self.packet = sequence, media_time, monotonic(), frame
                    self.condition.notify()
                sequence += 1
        finally:
            self.capture.release()
            with self.condition:
                self.done = True
                self.condition.notify_all()

    def after(self, sequence):
        with self.condition:
            self.condition.wait_for(
                lambda: self.done or (self.packet is not None and self.packet[0] > sequence), timeout=.5
            )
            return self.packet if self.packet is not None and self.packet[0] > sequence else None


def heading(frame, process):
    crop = cv2.resize(frame[14:46, 921:999], (390, 160), interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        return None
    process.stdin.write(b64encode(png).decode() + "\n")
    process.stdin.flush()
    reply = process.stdout.readline()
    if not reply:
        raise RuntimeError("Compass worker exited")
    match = re.fullmatch(r"[^0-9A-Za-z]*(\d{1,3})[^0-9A-Za-z]*", reply.strip())
    return int(match[1]) % 360 if match and int(match[1]) <= 360 else None


def locate(frame, atlas, prior):
    mini = frame[36:276, 1638:1886]
    template = cv2.resize(land(mini), None, fx=.99, fy=.99, interpolation=cv2.INTER_AREA)
    height, width = atlas.shape

    def match(region, x0, y0):
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))
        return ((x + x0 + 122 * .99) * 1500 / width, (y + y0 + 121 * .99) * 1500 / height), score

    if prior is not None:
        x, y = round(prior[0] * width / 1500), round(prior[1] * height / 1500)
        x0, y0 = max(0, x - 185), max(0, y - 185)
        position, score = match(atlas[y0:min(height, y + 185), x0:min(width, x + 185)], x0, y0)
        if score >= .75:
            return position, score
    return match(atlas, 0, 0)


def next_waypoint(terrain, player, chest):
    """Use the first grid waypoint far enough to clear position noise."""
    path = terrain.path(player, chest)
    for point in path[1:-1]:
        if dist(player, point) >= params.CELL_PX * 1.6:
            return point, len(path)
    return chest, len(path)


def overlay(frame, chest_number, player, yaw, waypoint, target, note):
    image = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    gold, white = (69, 211, 255), (231, 244, 255)
    panel = image[100:203, 477:803]
    cv2.addWeighted(panel, .14, np.full_like(panel, (16, 23, 31)), .86, 0, dst=panel)
    cv2.line(image, (477, 100), (803, 100), gold, 2, cv2.LINE_AA)
    center = (524, 151)
    cv2.circle(image, center, 31, gold, 1, cv2.LINE_AA)
    text = "Tracking lost"
    if target is None:
        text = "Route complete"
    elif player is not None and yaw is not None and waypoint is not None:
        _, turn, _ = steering(player, yaw, waypoint)
        meters = dist(player, target) * params.METERS_PER_PX
        if meters <= 5:
            cv2.circle(image, center, 5, gold, -1, cv2.LINE_AA)
            text = "Search area"
        else:
            angle = np.radians(turn)
            points = np.array([[0, -23], [16, 15], [0, 8], [-16, 15]])
            transform = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            polygon = np.rint(points @ transform.T + center).astype("int32")
            cv2.fillPoly(image, [polygon], gold, cv2.LINE_AA)
            direction = "Ahead" if abs(turn) < 12 else "Right" if turn > 0 else "Left"
            text = f"{direction}  |  chest ~{round(meters)} m"
    cv2.putText(image, "PIRATE TOKEN HUNT", (572, 126), 0, .48, gold, 1, cv2.LINE_AA)
    title = "ROUTE COMPLETE" if target is None else f"CHEST {chest_number:02d} / DIJKSTRA"
    cv2.putText(image, title, (572, 152), 0, .56, white, 2, cv2.LINE_AA)
    cv2.putText(image, text, (572, 174), 0, .50, white, 1, cv2.LINE_AA)
    cv2.putText(image, note or "F Found   M Missing   Q Quit", (572, 190), 0, .38, gold, 1, cv2.LINE_AA)
    return image


def run(args, ocr_binary, window_helper=None, hud_binary=None):
    atlas = land(cv2.imread(str(planner_source.MAP_IMAGE)))
    terrain = LegPather(planner_source.MAP_IMAGE, planner_source.MAP_SIZE)
    script = (ROOT / "planner" / "film-route.js").read_text()
    chests = json.loads(script.partition("=")[2].strip().removesuffix(";"))["chests"]
    if not 1 <= args.chest <= len(chests):
        raise SystemExit(f"Chest must be between 1 and {len(chests)}")

    marks = sorted((float(t), result) for t, result in args.mark)
    if window_helper is not None:
        selection = "--remote-play" if args.remote_play else str(args.window_id)
        capture = WindowInput(window_helper, selection, args.window_crop)
    else:
        capture = cv2.VideoCapture(args.device, cv2.CAP_AVFOUNDATION) if args.device is not None else cv2.VideoCapture(args.input)
        if not capture.isOpened():
            raise SystemExit("Couldn't open input. Check the capture device or stream and macOS camera permissions.")
    paced = args.input is not None and Path(args.input).is_file()
    if args.start:
        if not paced:
            raise SystemExit("--start is only supported for files")
        capture.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)

    encoder = None
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        encoder = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1280x720",
            "-r", str(args.record_fps), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.record),
        ], stdin=subprocess.PIPE)
    process = subprocess.Popen([ocr_binary, "--stream"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, bufsize=1)
    hud = subprocess.Popen([hud_binary], stdin=subprocess.PIPE, text=True) if hud_binary else None
    feed = Feed(capture, paced)
    index = args.chest - 1
    sequence = -1
    player = yaw = waypoint = route_key = None
    last_yaw = last_pos = next_head = next_pos = float("-inf")
    note, note_until = "", 0
    rows = []
    processed = frames_written = 0
    last_frame = None
    reported_lock = False
    next_hud_update = float("-inf")
    started = monotonic()
    try:
        while not feed.stop.is_set():
            packet = feed.after(sequence)
            if packet is None:
                if hud:
                    hud.stdin.write("null\n")
                    hud.stdin.flush()
                if feed.done or (args.duration and monotonic() - started >= args.duration):
                    break
                if not args.headless and last_frame is not None:
                    target = chests[index] if index < len(chests) else None
                    cv2.imshow("Pirate Token Hunt | runtime steering",
                               overlay(last_frame, index + 1, None, None, None, target, "Waiting for frames"))
                    if cv2.waitKey(1) & 0xff == ord("q"):
                        break
                continue
            sequence, media_time, arrived, frame = packet
            if not paced:
                media_time = arrived - started
            if args.duration and media_time >= args.duration:
                break
            if frame.shape[:2] != (1080, 1920):
                frame = cv2.resize(frame, (1920, 1080))
            last_frame = frame
            result = None
            if marks and media_time >= marks[0][0]:
                _, result = marks.pop(0)
            head_updated = position_updated = routed = False
            if media_time >= next_head:
                next_head = media_time + .10
                value = heading(frame, process)
                if value is not None:
                    yaw, last_yaw, head_updated = value, arrived, True
            if media_time >= next_pos:
                next_pos = media_time + .40
                value, score = locate(frame, atlas, player)
                if score >= .70:
                    player, last_pos, position_updated = value, arrived, True
            if result is not None and index < len(chests):
                note = f"Chest {index + 1} {result}"
                note_until = media_time + 2
                index += 1
                route_key = None
            target = chests[index] if index < len(chests) else None
            route_ms = 0.0
            if player is not None and target is not None and arrived - last_pos < .85:
                key = cell_of(*player), index
                if key != route_key:
                    tick = monotonic()
                    waypoint, path_points = next_waypoint(terrain, player, target)
                    route_ms = (monotonic() - tick) * 1000
                    route_key, routed = key, True
            tracked = player is not None and waypoint is not None and target is not None and yaw is not None
            now = monotonic()
            tracked = tracked and now - last_yaw <= .35 and now - last_pos <= .85
            image = overlay(frame, index + 1, player if tracked else None, yaw, waypoint, target,
                            note if media_time < note_until else "")
            latency_ms = (monotonic() - arrived) * 1000
            if tracked and not reported_lock:
                bearing, turn, _ = steering(player, yaw, waypoint)
                print(f"Tracking locked: chest {index + 1}, heading {yaw}°, waypoint {bearing:.0f}°, turn {turn:+.0f}°.",
                      flush=True)
                reported_lock = True
            if hud and media_time >= next_hud_update:
                next_hud_update = media_time + .05
                snapshot = None
                if tracked:
                    _, turn, _ = steering(player, yaw, waypoint)
                    snapshot = {"window": capture.window_id, "chest": index + 1, "turn": turn,
                                "meters": round(dist(player, target) * params.METERS_PER_PX)}
                hud.stdin.write(json.dumps(snapshot) + "\n")
                hud.stdin.flush()
            processed += 1
            if args.metrics:
                sample = {"t": round(media_time, 3), "frame": sequence, "chest": index + 1, "tracked": tracked,
                          "heading_update": head_updated, "position_update": position_updated, "routed": routed,
                          "route_ms": round(route_ms, 2), "frame_age_ms": round(latency_ms, 2)}
                if result:
                    sample["mark"] = result
                if tracked:
                    bearing, turn, _ = steering(player, yaw, waypoint)
                    direct, _, _ = steering(player, yaw, target)
                    sample.update({"heading": yaw, "position": player, "waypoint": waypoint, "target": target,
                                   "waypoint_bearing": bearing, "direct_bearing": direct, "turn": turn,
                                   "path_points": path_points, "heading_age_ms": round((now - last_yaw) * 1000, 2),
                                   "position_age_ms": round((now - last_pos) * 1000, 2)})
                rows.append(sample)
            if encoder:
                desired = int(media_time * args.record_fps) + 1
                while frames_written < desired:
                    encoder.stdin.write(image.tobytes())
                    frames_written += 1
            if not args.headless:
                cv2.imshow("Pirate Token Hunt | runtime steering", image)
                key = cv2.waitKey(1) & 0xff
                if key == ord("q"):
                    break
                if key in (ord("f"), ord("m")):
                    marks.insert(0, (media_time, "found" if key == ord("f") else "missing"))
    finally:
        feed.stop.set()
        if isinstance(capture, WindowInput):
            capture.interrupt()
        feed.worker.join(timeout=2)
        process.stdin.close()
        process.wait(timeout=5)
        if hud:
            hud.stdin.close()
            hud.wait(timeout=5)
        if encoder:
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError("Recording encoder failed")
        if not args.headless:
            cv2.destroyAllWindows()
        if args.metrics:
            args.metrics.parent.mkdir(parents=True, exist_ok=True)
            args.metrics.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Processed {processed} frames from {'paced file' if paced else 'live input'}.")
    if not processed:
        raise SystemExit("No frames arrived from the input.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", help="Local gameplay file or stream URL")
    inputs.add_argument("--device", type=int, help="macOS AVFoundation video input index")
    inputs.add_argument("--remote-play", action="store_true", help="Capture only the largest visible PS Remote Play window")
    inputs.add_argument("--window-id", type=int, help="Capture only this macOS window ID")
    inputs.add_argument("--list-windows", action="store_true", help="List capturable windows and their IDs")
    parser.add_argument("--window-crop", type=lambda value: tuple(map(int, value.split(":"))),
                        metavar="W:H:X:Y", help="Gameplay rectangle in the 1920px-wide captured window")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--chest", type=int, default=19, help="First active chest number")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--hud", action="store_true", help="Draw a nonactivating, click-through HUD on the selected window")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--record-fps", type=int, choices=(15, 30, 60), default=15,
                        help="Output recording frame rate. The capture device determines the unique input frame rate.")
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--mark", nargs=2, action="append", default=[], metavar=("SECONDS", "found|missing"))
    args = parser.parse_args()
    if any(mark not in {"found", "missing"} for _, mark in args.mark):
        parser.error("--mark result must be found or missing")
    if args.input and args.record and Path(args.input).resolve() == args.record.resolve():
        parser.error("The input and recording output must be different files")
    window_mode = args.remote_play or args.window_id is not None or args.list_windows
    if args.window_crop is not None and (not window_mode or len(args.window_crop) != 4):
        parser.error("--window-crop requires a window and W:H:X:Y")
    if args.start and (not args.input or not Path(args.input).is_file()):
        parser.error("--start is only supported for files")
    if args.hud:
        if not window_mode or args.list_windows:
            parser.error("--hud requires a gameplay window")
        args.headless = True
    helper = None
    if window_mode:
        source = Path(__file__).with_name("window_capture.swift")
        helper = ROOT / "out" / "steering" / "window-capture"
        helper.parent.mkdir(parents=True, exist_ok=True)
        if not helper.exists() or helper.stat().st_mtime < source.stat().st_mtime:
            with tempfile.TemporaryDirectory(dir=helper.parent) as build:
                compiled = Path(build) / helper.name
                subprocess.run(["swiftc", "-parse-as-library", str(source), "-o", compiled], check=True)
                compiled.replace(helper)
        if args.list_windows:
            raise SystemExit(subprocess.run([helper, "--list"]).returncode)
    with tempfile.TemporaryDirectory(prefix="fortnite-live-") as tmp:
        binary = Path(tmp) / "ocr"
        subprocess.run(["swiftc", str(Path(__file__).with_name("read_compass.swift")), "-o", binary], check=True)
        hud_binary = None
        if args.hud:
            hud_binary = Path(tmp) / "hud"
            subprocess.run(["swiftc", str(Path(__file__).with_name("window_hud.swift")), "-o", hud_binary], check=True)
        run(args, binary, helper, hud_binary)


if __name__ == "__main__":
    main()
