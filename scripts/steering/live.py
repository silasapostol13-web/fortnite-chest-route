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
            return point, path
    return chest, path


# Where the game's own HUD sits in a 1920x1080 frame. The same numbers place the HUD's extras.
MINIMAP = (1638, 36, 248, 240)          # x, y, width, height of the minimap crop
MINIMAP_PLAYER = (122, 121)             # the player's spot inside that crop
COMPASS = (958.5, 58, 3.5625)           # strip centre x, strip bottom y, pixels per degree (measured, see README)


def hud_binary():
    """Compile the Swift HUD once and reuse it until its source changes."""
    source = Path(__file__).with_name("window_hud.swift")
    binary = ROOT / "out" / "steering" / "window-hud"
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        with tempfile.TemporaryDirectory(dir=binary.parent) as build:
            compiled = Path(build) / binary.name
            subprocess.run(["swiftc", "-O", str(source), "-o", compiled], check=True)
            compiled.replace(binary)
    return binary


class HudRenderer:
    """Draw the live HUD onto recorded frames with the same Swift code that draws it on the game."""

    def __init__(self, binary, size=(1280, 720)):
        self.width, self.height = size
        self.process = subprocess.Popen([binary, "--render", str(self.width), str(self.height)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def composite(self, image, snapshot):
        self.process.stdin.write((json.dumps(snapshot) + "\n").encode())
        self.process.stdin.flush()
        count = self.width * self.height * 4
        raw = self.process.stdout.read(count)
        if len(raw) != count:
            raise RuntimeError("HUD renderer exited")
        layer = np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 4)
        rows = np.flatnonzero(layer[..., 3].any(axis=1))
        if rows.size:                           # premultiplied "over", only on the rows the HUD touched
            top, bottom = rows[0], rows[-1] + 1
            part = layer[top:bottom].astype(np.uint16)
            under = image[top:bottom].astype(np.uint16) * (255 - part[..., 3:]) // 255
            image[top:bottom] = np.minimum(part[..., :3] + under, 255).astype(np.uint8)
        return image

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)


HUD_OPTIONS = {}                        # look-only settings from the command line: scale, style


class FixedRoute:
    """The hand-made film route: a fixed list of chests, one after another (``--route film``)."""

    def __init__(self, chests, kinds, start, opened):
        self.chests, self.kinds, self.index = chests, kinds, start - 1
        # Chests counted as opened: the ones before the starting chest, then every one reached or marked found.
        self.opened = set(range(start - 1 if opened is None else min(opened, len(chests))))

    @property
    def done(self):
        return self.index >= len(self.chests)

    @property
    def key(self):
        return self.index

    def target(self):
        return None if self.done else self.chests[self.index]

    def kind(self):
        return "" if self.done else self.kinds[self.index]

    def fields(self):
        return {"chest": min(self.index + 1, len(self.chests)), "total": len(self.chests), "opened": len(self.opened)}

    def resolve(self, result):
        if self.done:
            return None
        if result in {"found", "reached"}:
            self.opened.add(self.index)
        self.index += 1
        return f"Chest {self.index} {result}."

    def back(self):
        if self.index > 0:
            self.index -= 1
            return f"Back to chest {self.index + 1}."

    def update(self, player, moved, now):
        return {}

    def close(self):
        pass


class LiveRoute:
    """Every chest spot on the map, re-planned about once a second from where the player is (``--route live``).

    The active chest is the first stop of the newest plan. Reaching it (the arrive rule in ``run``) or pressing
    found counts it as opened; skip or missing drops it. Standing within ``pass_meters`` of any other chest
    spot for ``pass_seconds`` counts it as checked, so the plan never sends him back (not buried spots: those
    need digging, so walking over one proves nothing). Back restores the
    last spot dealt with and keeps it first until it is dealt with again."""

    def __init__(self, terrain, budget, pass_meters=6.0, pass_seconds=1.5):
        from replan import LivePlanner, Planner
        self.planner = Planner(terrain, budget=budget)
        self.worker = LivePlanner(self.planner)
        self.xy = self.planner.xy
        self.plan, self.history, self.visited = [], [], set()
        self.opened = 0
        self.sequence = 0
        self.passing = {}
        self.pass_px, self.pass_seconds = pass_meters / params.METERS_PER_PX, pass_seconds
        self.force, self.pin = True, None
        self.done = False

    @property
    def key(self):
        return self.plan[0] if self.plan else None

    def target(self):
        return tuple(float(v) for v in self.xy[self.plan[0]]) if self.plan else None

    def kind(self):
        return self.planner.kinds[self.plan[0]] if self.plan else ""

    def fields(self):
        return {"chest": self.opened + 1, "total": self.opened + len(self.plan), "opened": self.opened,
                "planned": len(self.plan)}

    def _deal(self, spot, opened):
        self.visited.add(spot)
        self.history.append((spot, opened))
        self.opened += opened
        self.plan = [s for s in self.plan if s != spot]
        self.passing.pop(spot, None)
        if spot == self.pin:
            self.pin = None
        self.force = True

    def resolve(self, result):
        if not self.plan:
            return None
        spot = self.plan[0]
        self._deal(spot, result in {"found", "reached"})
        return f"Chest spot {spot} ({self.planner.kinds[spot]}) {result}; {self.opened} opened."

    def back(self):
        if not self.history:
            return None
        spot, opened = self.history.pop()
        self.visited.discard(spot)
        self.opened -= opened
        self.plan = [spot] + [s for s in self.plan if s != spot]
        self.pin, self.force = spot, True
        return f"Back to chest spot {spot}."

    def update(self, player, moved, now):
        """Call on every frame. ``moved`` is True on frames with a new position fix."""
        events = {}
        if player is not None and moved:
            near = np.flatnonzero(np.hypot(*(self.xy - np.asarray(player)).T) <= self.pass_px)
            near = {int(i) for i in near if self.planner.kinds[i] != "buried"} - self.visited - {self.key}
            self.passing = {spot: since for spot, since in self.passing.items() if spot in near}
            for spot in near:
                if now - self.passing.setdefault(spot, now) >= self.pass_seconds:
                    self._deal(spot, False)
                    events.setdefault("passed", []).append(spot)
            self.worker.submit(player, self.visited, self.key, force=self.force, hold=self.pin is not None)
            self.force = False
        sequence, result = self.worker.latest()
        if sequence != self.sequence and result is not None:
            self.sequence = sequence
            order, _, _, solve_ms, _ = result
            order = [s for s in order if s not in self.visited]
            if self.pin is not None:
                order = [self.pin] + [s for s in order if s != self.pin]
            if order and self.plan and order[0] != self.plan[0]:
                events["replanned"] = True
            self.plan = order
            events["plan_ms"] = round(solve_ms, 1)
        return events

    def close(self):
        self.worker.close()


def path_ahead(player, yaw, path, marks=(12, 30, 50)):
    """[turn, metres] at points this far down the path; stops at the chest."""
    points, walked = [], 0.0
    for a, b in zip(path, path[1:]):
        step = dist(a, b) * params.METERS_PER_PX
        while marks[len(points):] and walked + step >= marks[len(points)] and step > 0:
            f = (marks[len(points)] - walked) / step
            point = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            points.append([round(steering(player, yaw, point)[1], 1), marks[len(points)]])
        walked += step
    if path and len(points) < len(marks) and walked > (points[-1][1] if points else 0) + 3:
        points.append([round(steering(player, yaw, path[-1])[1], 1), round(walked)])
    return points


def hud_snapshot(route, player, yaw, waypoint, path, tracked, atlas_width, replanned=False):
    """Everything the HUD draws for one moment. Old HUD builds only read chest, turn and meters."""
    target = route.target()
    snapshot = {**route.fields(), "tracked": bool(tracked), "done": route.done, "kind": route.kind(),
                "mpu": params.METERS_PER_PX, **HUD_OPTIONS}
    if replanned:
        snapshot["replanned"] = True
    if tracked and target is not None:
        _, turn, _ = steering(player, yaw, waypoint)
        direct, _, _ = steering(player, yaw, target)
        x, y, _, _ = MINIMAP
        snapshot.update({
            "turn": turn, "meters": round(dist(player, target) * params.METERS_PER_PX), "heading": yaw,
            "bearing": direct, "player": [round(v, 1) for v in player], "target": list(target),
            "path": [[round(px, 1), round(py, 1)] for px, py in path[:80]],
            "ahead": path_ahead(player, yaw, path),
            "mini": [x + MINIMAP_PLAYER[0], y + MINIMAP_PLAYER[1], atlas_width / 1500 / .99, x, y, x + MINIMAP[2], y + MINIMAP[3]],
            "compass": list(COMPASS),
        })
    return snapshot


def overlay(frame, renderer, snapshot):
    image = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    return renderer.composite(image, snapshot)


def run(args, ocr_binary, window_helper=None, hud_path=None, render_binary=None):
    atlas = land(cv2.imread(str(planner_source.MAP_IMAGE)))
    terrain = LegPather(planner_source.MAP_IMAGE, planner_source.MAP_SIZE)
    if args.route == "film":
        script = (ROOT / "planner" / "film-route.js").read_text()
        film = json.loads(script.partition("=")[2].strip().removesuffix(";"))
        chests = film["chests"]
        if not 1 <= args.chest <= len(chests):
            raise SystemExit(f"Chest must be between 1 and {len(chests)}")
        route = FixedRoute(chests, film.get("types") or ["chest"] * len(chests), args.chest, args.opened)
    else:
        route = LiveRoute(terrain, args.budget)

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
    hud = subprocess.Popen([hud_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                           bufsize=1) if hud_path else None
    renderer = HudRenderer(render_binary) if render_binary and (args.record or not args.headless) else None
    path = []
    commands = []
    if hud:
        def listen():
            for line in hud.stdout:
                if line.strip() in {"next", "back"}:
                    commands.append(line.strip())
        Thread(target=listen, daemon=True).start()
    near_since = None
    feed = Feed(capture, paced)
    replanned_until = float("-inf")
    sequence = -1
    player = yaw = waypoint = route_key = None
    last_yaw = last_pos = next_head = next_pos = float("-inf")
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
                    waiting = hud_snapshot(route, None, None, None, [], False, atlas.shape[1])
                    cv2.imshow("Pirate Token Hunt | runtime steering", overlay(last_frame, renderer, waiting))
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
            while commands:
                command = commands.pop(0)
                if command == "back":
                    message = route.back()
                    if message:
                        route_key = near_since = None
                        print(message, flush=True)
                elif command == "next" and result is None:
                    result = "skipped"
                elif command == "arrived" and result is None:
                    result = "reached"
            if result is not None:
                message = route.resolve(result)
                if message:
                    route_key = near_since = None
                    print(message, flush=True)
            events = route.update(player if arrived - last_pos < .85 else None, position_updated, media_time)
            if events.get("replanned"):
                replanned_until = media_time + .3
                near_since = None
            target = route.target()
            route_ms = 0.0
            if player is not None and target is not None and arrived - last_pos < .85:
                key = cell_of(*player), route.key
                if key != route_key:
                    tick = monotonic()
                    waypoint, path = next_waypoint(terrain, player, target)
                    path_points = len(path)
                    route_ms = (monotonic() - tick) * 1000
                    route_key, routed = key, True
            tracked = player is not None and waypoint is not None and target is not None and yaw is not None
            now = monotonic()
            tracked = tracked and now - last_yaw <= .35 and now - last_pos <= .85
            if args.arrive_seconds > 0 and target is not None and player is not None and now - last_pos <= .85:
                if dist(player, target) * params.METERS_PER_PX <= args.arrive_meters:
                    near_since = media_time if near_since is None else near_since
                    if media_time - near_since >= args.arrive_seconds:
                        commands.insert(0, "arrived")
                else:
                    near_since = None
            state = hud_snapshot(route, player, yaw, waypoint, path, tracked, atlas.shape[1],
                                 replanned=media_time < replanned_until)
            image = overlay(frame, renderer, {**state, "t": media_time}) if renderer else None
            latency_ms = (monotonic() - arrived) * 1000
            if tracked and not reported_lock:
                bearing, turn, _ = steering(player, yaw, waypoint)
                print(f"Tracking locked: chest {state['chest']}, heading {yaw}°, waypoint {bearing:.0f}°, turn {turn:+.0f}°.",
                      flush=True)
                reported_lock = True
            if hud and media_time >= next_hud_update:
                next_hud_update = media_time + .05
                snapshot = {**state, "window": capture.window_id}
                if capture.crop:                # where the gameplay picture sits inside the captured window
                    w, h, x, y = capture.crop
                    snapshot["game"] = [x / capture.width, y / capture.height, w / capture.width, h / capture.height]
                hud.stdin.write(json.dumps(snapshot) + "\n")
                hud.stdin.flush()
            processed += 1
            if args.metrics:
                sample = {"t": round(media_time, 3), "frame": sequence, "chest": state["chest"], "tracked": tracked,
                          "heading_update": head_updated, "position_update": position_updated, "routed": routed,
                          "route_ms": round(route_ms, 2), "frame_age_ms": round(latency_ms, 2)}
                if result:
                    sample["mark"] = result
                if isinstance(route, LiveRoute):
                    sample.update({"spot": route.key, "planned": len(route.plan), "opened": route.opened})
                    for name in ("plan_ms", "replanned", "passed"):
                        if name in events:
                            sample[name] = events[name]
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
        route.close()
        if isinstance(capture, WindowInput):
            capture.interrupt()
        feed.worker.join(timeout=2)
        process.stdin.close()
        process.wait(timeout=5)
        if hud:
            hud.stdin.close()
            hud.wait(timeout=5)
        if renderer:
            renderer.close()
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
    parser.add_argument("--route", choices=("live", "film"), default="live",
                        help="live: re-plan over every chest spot from where you are (default); film: the fixed 33-chest list")
    parser.add_argument("--budget", type=float, default=120,
                        help="Live route: plan the most chests reachable in this many seconds")
    parser.add_argument("--chest", type=int, default=19, help="Film route: first active chest number")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--hud", action="store_true", help="Draw a nonactivating, click-through HUD on the selected window")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--record-fps", type=int, choices=(15, 30, 60), default=15,
                        help="Output recording frame rate. The capture device determines the unique input frame rate.")
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--arrive-meters", type=float, default=8,
                        help="Move to the next chest after staying this close to the active one")
    parser.add_argument("--arrive-seconds", type=float, default=1.5,
                        help="How long to stay near a chest before moving on; 0 turns auto-advance off")
    parser.add_argument("--hud-scale", type=float, default=1.0,
                        help="Card size, 0.6 to 1.6. Above about 1.1 it can touch the game's storm banner")
    parser.add_argument("--hud-style", choices=("ribbon", "arrow", "cutlass"), default="ribbon",
                        help="Arrow look: ribbon bends with the path's next turns, arrow is one straight gold arrow, "
                             "cutlass is a pirate sword needle")
    parser.add_argument("--opened", type=int,
                        help="Chests already opened when the run starts (default: every chest before --chest)")
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
        HUD_OPTIONS.update(scale=args.hud_scale, style=args.hud_style)
        drawn = args.hud or args.record or not args.headless
        built = hud_binary() if drawn else None
        run(args, binary, helper, built if args.hud else None, built)


if __name__ == "__main__":
    main()
