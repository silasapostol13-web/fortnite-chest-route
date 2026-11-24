"""Animated 9:16 clip + still of the best landing and route.

    .venv/bin/python -m route.render --draft      # 540x960 preview
    .venv/bin/python -m route.render              # 1080x1920 final

Reads out/best_landing.json (from ``run.py land``). Legs are drawn along the
real walking path from Silas's Graph.dijkstra on the map grid.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from math import hypot
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import params as P
from .travel import MAP_IMAGE, LegPather, load_spawns, travel_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FPS = 30
GOLD = (255, 205, 60)
BUS = (120, 200, 255)
WHITE = (245, 247, 250)
BG = (10, 18, 32)

# timeline, seconds of video
T_BUS, T_PIN, T_ZOOM, T_ROUTE, T_END = 0.0, 0.45, 0.8, 1.3, 8.8
DURATION = 10.5


def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial Black.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def chaikin(pts, rounds=2):
    pts = list(pts)
    for _ in range(rounds):
        if len(pts) < 3:
            return pts
        new = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            new += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        new.append(pts[-1])
        pts = new
    return pts


class Scene:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.s = W / 1080
        data = json.loads((OUT / "best_landing.json").read_text())
        self.data = data
        ids, areas, xy = load_spawns()
        self.xy = xy
        self.area = data["area"]
        self.route = data["route_idx"]
        T = travel_matrix()
        pather = LegPather()
        # legs: polyline + game-time span
        self.legs = []
        t = P.CHEST_STOP_S
        self.open_times = [t]  # landing chest opens after its stop
        for a, b in zip(self.route, self.route[1:]):
            pts = chaikin(pather.path(xy[a], xy[b]))
            dur = T[a, b]
            self.legs.append((pts, t, t + dur))
            t += dur + P.CHEST_STOP_S
            self.open_times.append(t)
        self.total = t
        self.bus = data["bus"]
        img = Image.open(MAP_IMAGE).convert("RGB")
        self.k = img.size[0] / P.MAP_LOGICAL_SIZE[0]  # logical -> image px
        # pad with sea colour so the camera never sees black edges
        self.pad = 900
        sea = img.getpixel((10, img.size[1] // 2))
        padded = Image.new("RGB", (img.size[0] + 2 * self.pad, img.size[1] + 2 * self.pad), sea)
        fade = np.ones((img.size[1], img.size[0]), dtype=float)
        e = 80
        ramp = np.linspace(0, 1, e)
        fade[:e] *= ramp[:, None]
        fade[-e:] *= ramp[::-1][:, None]
        fade[:, :e] *= ramp[None, :]
        fade[:, -e:] *= ramp[::-1][None, :]
        padded.paste(img, (self.pad, self.pad), Image.fromarray((fade * 255).astype(np.uint8), "L"))
        self.map_img = padded
        # cameras in logical px: (cx, cy, width)
        lw, lh = P.MAP_LOGICAL_SIZE
        self.cam_full = (lw / 2, lh / 2 - 20, lw * 0.92)
        rxy = xy[self.route]
        x0, y0 = rxy.min(0)
        x1, y1 = rxy.max(0)
        wid = max(x1 - x0 + 90, (y1 - y0 + 70) * W / (H * 0.5), 175)
        self.cam_zoom = ((x0 + x1) / 2, (y0 + y1) / 2 - 12, wid)  # nudge down: room for the pin label
        self.f_big, self.f_mid, self.f_small = font(int(150 * self.s)), font(int(46 * self.s)), font(int(36 * self.s))

    # map area: centred vertically, leaves room top (counter) and bottom (captions)
    def to_screen(self, cam, x, y):
        cx, cy, wid = cam
        scale = self.W / wid
        return ((x - cx) * scale + self.W / 2, (y - cy) * scale + self.H * 0.52)

    def camera(self, vt):
        a = ease((vt - T_ZOOM) / (T_ROUTE - T_ZOOM))
        return tuple(f + (z - f) * a for f, z in zip(self.cam_full, self.cam_zoom))

    def base(self, cam):
        cx, cy, wid = cam
        scale = self.W / wid  # screen px per logical px
        # logical rect covering the frame
        lx0, ly0 = cx - self.W / 2 / scale, cy - self.H * 0.52 / scale
        lx1, ly1 = lx0 + self.W / scale, ly0 + self.H / scale
        k = self.k
        o = self.pad
        crop = self.map_img.crop((int(lx0 * k) + o, int(ly0 * k) + o, int(lx1 * k) + o, int(ly1 * k) + o))
        frame = Image.new("RGB", (self.W, self.H), BG)
        crop = crop.resize((self.W, int(self.W * crop.size[1] / crop.size[0])), Image.LANCZOS)
        frame.paste(crop, (0, 0))
        # darken so the route pops; fade into the background at top and bottom
        dark = Image.new("RGB", frame.size, BG)
        frame = Image.blend(frame, dark, 0.38)
        grad = np.zeros((self.H, 1), dtype=np.uint8)
        for y in range(self.H):
            top = max(0.0, 1 - y / (self.H * 0.17))
            bot = max(0.0, (y - self.H * 0.83) / (self.H * 0.17))
            grad[y, 0] = int(255 * min(1.0, max(top, bot)))
        mask = Image.fromarray(np.repeat(grad, self.W, axis=1), "L")
        frame.paste(dark, (0, 0), mask)
        return frame

    def draw(self, vt):
        cam = self.camera(vt)
        img = self.base(cam)
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        top = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(top)
        s = self.s
        sc = lambda x, y: self.to_screen(cam, x, y)  # noqa: E731

        # all 860 spawn spots, faint
        dot_r = max(1.5, 2.2 * s * (self.W / cam[2]) / (self.W / self.cam_full[2]) ** 0.5 / 2)
        for x, y in self.xy:
            px, py = sc(x, y)
            if -5 < px < self.W + 5 and -5 < py < self.H + 5:
                d.ellipse((px - dot_r, py - dot_r, px + dot_r, py + dot_r), fill=(255, 255, 255, 90))

        # bus line
        if self.bus:
            (bx0, by0), (bx1, by1) = self.bus
            a = ease((vt - T_BUS) / (T_PIN - T_BUS))
            bus_alpha = int(255 * (1 - ease((vt - T_ROUTE) / 1.0)))
            if bus_alpha > 0:
                ex, ey = bx0 + (bx1 - bx0) * a, by0 + (by1 - by0) * a
                p0, p1 = sc(bx0, by0), sc(ex, ey)
                d.line([p0, p1], fill=BUS + (bus_alpha,), width=int(7 * s))
                d.ellipse((p1[0] - 14 * s, p1[1] - 14 * s, p1[0] + 14 * s, p1[1] + 14 * s), fill=BUS + (bus_alpha,))
                if a > 0.15:
                    d.text((p1[0] + 22 * s, p1[1] - 20 * s), "BUS", font=self.f_small, fill=BUS + (bus_alpha,))

        # route progress in game time
        gt = self.total * min(1.0, (vt - T_ROUTE) / (T_END - T_ROUTE)) if vt >= T_ROUTE else 0.0
        lw = int(9 * s)
        for pts, t0, t1 in self.legs:
            if gt <= t0:
                break
            frac = min(1.0, (gt - t0) / max(t1 - t0, 1e-6))
            spts = [sc(x, y) for x, y in pts]
            # cut polyline at frac of its length
            seg = [hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(spts, spts[1:])]
            goal, acc, cut = frac * sum(seg), 0.0, [spts[0]]
            for (p, q), L in zip(zip(spts, spts[1:]), seg):
                if acc + L >= goal:
                    u = (goal - acc) / L if L else 0
                    cut.append((p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u))
                    break
                cut.append(q)
                acc += L
            if len(cut) >= 2:
                gd.line(cut, fill=GOLD + (160,), width=lw * 3, joint="curve")
                d.line(cut, fill=(20, 16, 8, 255), width=lw + int(4 * s), joint="curve")
                d.line(cut, fill=GOLD + (255,), width=lw, joint="curve")

        # opened chests pop
        opened = 0
        for idx, ot in zip(self.route, self.open_times):
            if vt >= T_ROUTE and gt >= ot - P.CHEST_STOP_S:
                opened += gt >= ot - P.CHEST_STOP_S * 0.5
                px, py = sc(*self.xy[idx])
                age = (gt - (ot - P.CHEST_STOP_S)) / self.total * (T_END - T_ROUTE)  # video seconds since reached
                pop = 1 + 0.8 * max(0.0, 1 - age / 0.25)
                r = 9 * s * pop
                d.ellipse((px - r, py - r, px + r, py + r), fill=GOLD + (255,), outline=(20, 16, 8, 255), width=int(3 * s))

        # landing pin
        lx, ly = sc(*self.xy[self.route[0]])
        pa = ease((vt - T_PIN) / 0.35)
        if pa > 0:
            drop = (1 - pa) * 120 * s
            pr = 26 * s
            ring = (vt - T_PIN) % 1.0
            if vt < T_ROUTE + 1.5:
                rr = pr * (1 + 2.2 * ring)
                d.ellipse((lx - rr, ly - rr, lx + rr, ly + rr), outline=WHITE + (int(220 * (1 - ring)),), width=int(4 * s))
            d.polygon([(lx, ly - drop), (lx - pr * 0.8, ly - pr * 2.0 - drop), (lx + pr * 0.8, ly - pr * 2.0 - drop)],
                      fill=(255, 70, 90, 255))
            d.ellipse((lx - pr, ly - pr * 3.2 - drop, lx + pr, ly - pr * 1.2 - drop), fill=(255, 70, 90, 255),
                      outline=WHITE + (255,), width=int(4 * s))
            label = f"LAND: {self.area.upper()}"
            tw = d.textlength(label, font=self.f_mid)
            tx = min(max(lx - tw / 2, 24 * s), self.W - tw - 24 * s)
            ty = ly - pr * 3.2 - drop - 70 * s
            d.rounded_rectangle((tx - 16 * s, ty - 8 * s, tx + tw + 16 * s, ty + 58 * s), radius=int(14 * s),
                                fill=(10, 18, 32, int(220 * pa)))
            d.text((tx, ty), label, font=self.f_mid, fill=WHITE + (int(255 * pa),))

        glow = glow.filter(ImageFilter.GaussianBlur(10 * s))
        img = Image.alpha_composite(img.convert("RGBA"), glow)
        img = Image.alpha_composite(img, top)

        # HUD: chest counter (top) and loot clock
        hud = ImageDraw.Draw(img)
        num = str(opened)
        hud.text((60 * s, 110 * s), num, font=self.f_big, fill=GOLD)
        nw = hud.textlength(num, font=self.f_big)
        hud.text((60 * s + nw + 24 * s, 150 * s), "CHEST SPOTS", font=self.f_mid, fill=WHITE)
        hud.text((60 * s + nw + 24 * s, 205 * s), "CHECKED", font=self.f_mid, fill=WHITE)
        clock = int(gt)
        ct = f"{clock // 60}:{clock % 60:02d}"
        cw = hud.textlength(ct, font=self.f_mid)
        hud.text((self.W - 60 * s - cw, 150 * s), ct, font=self.f_mid, fill=GOLD)
        lab = "ON THE GROUND"
        hud.text((self.W - 60 * s - hud.textlength(lab, font=self.f_small), 205 * s), lab, font=self.f_small,
                 fill=WHITE)
        return img.convert("RGB")


def render(W, H, out_path, still_path, frames_dir):
    scene = Scene(W, H)
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = int(DURATION * FPS)
    for i in range(n):
        scene.draw(i / FPS).save(frames_dir / f"f{i:04d}.png", compress_level=1)
    scene.draw(DURATION).save(still_path)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames_dir / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium",
                    "-movflags", "+faststart", str(out_path)], check=True)
    return out_path, still_path, scene


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--frames", default=None)
    args = ap.parse_args()
    W, H = (540, 960) if args.draft else (1080, 1920)
    OUT.mkdir(exist_ok=True)
    tag = "draft" if args.draft else "final"
    out = Path(args.out) if args.out else OUT / f"route_{tag}.mp4"
    frames = Path(args.frames) if args.frames else OUT / f"frames_{tag}"
    v, s, scene = render(W, H, out, out.with_suffix(".png"), frames)
    print(v, s, f"{len(scene.route)} chests, {scene.total:.0f} s of game time")


if __name__ == "__main__":
    main()
