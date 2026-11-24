"""Show-off clip: scan every landing spot (heat map), rank the top 5, draw the winner's route,
compare with the average drop.

    .venv/bin/python -m route.scan_render --draft     # 540x960
    .venv/bin/python -m route.scan_render             # 1080x1920

Needs out/scan.json and out/best_landing.json from ``python -m route.scan``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import render as R
from .render import BG, GOLD, WHITE, Scene, ease
from .travel import load_spawns

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FPS = 30
SCAN_END, RANK_END = 2.4, 4.4   # phases, video seconds
ROUTE_LEN = 6.5                 # route phase length (pin + zoom + drawing)
TAIL = 2.0
DURATION = RANK_END + ROUTE_LEN + TAIL


def heat(v):
    """0..1 -> blue, white, gold."""
    lo, mid, hi = np.array([40, 90, 200]), np.array([235, 240, 250]), np.array([255, 190, 40])
    c = lo + (mid - lo) * (v / 0.6) if v < 0.6 else mid + (hi - mid) * ((v - 0.6) / 0.4)
    return tuple(int(x) for x in c)


class ScanScene(Scene):
    def __init__(self, W, H):
        super().__init__(W, H)
        scan = json.loads((OUT / "scan.json").read_text())
        self.counts = np.array(scan["counts"])
        self.top5 = scan["top5"]
        self.avg = scan["random_mean"]
        self.n_spots = len(self.counts)
        lo, hi = self.counts.min(), self.counts.max()
        self.v = (self.counts - lo) / max(hi - lo, 1)
        self.order_x = self.xy[:, 0]
        self.x_min, self.x_max = self.order_x.min(), self.order_x.max()

    def full_frame(self, t):
        cam = self.cam_full
        img = self.base(cam).convert("RGBA")
        top = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(top)
        s = self.s
        sweep = self.x_min + (self.x_max - self.x_min + 20) * ease(t / SCAN_END)
        scanned = 0
        dim = t > SCAN_END  # during ranking, fade the heat dots back
        for i, (x, y) in enumerate(self.xy):
            if x > sweep:
                continue
            scanned += 1
            px, py = self.to_screen(cam, x, y)
            r = (3 + 5 * self.v[i] ** 2) * s
            a = 110 if dim else 235
            d.ellipse((px - r, py - r, px + r, py + r), fill=heat(self.v[i]) + (a,))
        if t < SCAN_END:
            lx, _ = self.to_screen(cam, sweep, 0)
            d.line([(lx, self.H * 0.12), (lx, self.H * 0.9)], fill=(120, 220, 255, 200), width=int(4 * s))
        # header
        if t < SCAN_END + 0.2:
            n = min(self.n_spots, int(self.n_spots * ease(t / SCAN_END)))
            d.text((60 * s, 110 * s), f"{n}", font=self.f_big, fill=GOLD + (255,))
            nw = d.textlength(f"{n}", font=self.f_big)
            d.text((60 * s + nw + 24 * s, 150 * s), "LANDING SPOTS", font=self.f_mid, fill=WHITE + (255,))
            d.text((60 * s + nw + 24 * s, 205 * s), "SCORED", font=self.f_mid, fill=WHITE + (255,))
        else:
            d.text((60 * s, 120 * s), "MOST CHEST SPOTS IN", font=self.f_mid, fill=WHITE + (255,))
            d.text((60 * s, 175 * s), "2:00 ON THE GROUND", font=self.f_mid, fill=GOLD + (255,))
        # top 5
        if t >= SCAN_END:
            pa = int(225 * ease((t - SCAN_END) / 0.3))
            d.rounded_rectangle((36 * s, self.H * 0.72, self.W - 36 * s, self.H * 0.72 + 270 * s),
                                radius=int(24 * s), fill=BG + (pa,))
            fr = self.f_mid
            for rank, (area, idx, cnt) in enumerate(self.top5, start=1):
                appear = ease((t - SCAN_END - (5 - rank) * 0.25) / 0.3)  # 5th first, 1st last
                if appear <= 0:
                    continue
                px, py = self.to_screen(cam, *self.xy[idx])
                r = 22 * s
                col = (255, 70, 90) if rank == 1 else GOLD
                d.ellipse((px - r, py - r, px + r, py + r), fill=col + (int(255 * appear),),
                          outline=(20, 16, 8, 255), width=int(3 * s))
                lab = str(rank)
                d.text((px - d.textlength(lab, font=self.f_small) / 2, py - 19 * s), lab, font=self.f_small,
                       fill=(20, 16, 8, int(255 * appear)))
                y = self.H * 0.735 + (rank - 1) * 50 * s
                rf = fr if rank == 1 else self.f_small
                fill = (col if rank == 1 else WHITE) + (int(255 * appear),)
                d.text((60 * s, y), f"{rank}   {area.upper()}", font=rf, fill=fill)
                tie = rank > 1 and cnt == self.top5[0][2]
                cs = f"{cnt} (TIE)" if tie else f"{cnt}"
                d.text((self.W - 60 * s - d.textlength(cs, font=rf), y), cs, font=rf, fill=fill)
        return Image.alpha_composite(img, top).convert("RGB")

    def frame(self, t):
        if t < RANK_END:
            return self.full_frame(t)
        rt = t - RANK_END
        img = self.draw(min(rt, R.T_END + 0.5))
        if t > RANK_END + ROUTE_LEN:
            a = ease((t - RANK_END - ROUTE_LEN) / 0.4)
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(ov)
            s = self.s
            y0 = self.H * 0.76
            d.rounded_rectangle((40 * s, y0, self.W - 40 * s, y0 + 250 * s), radius=int(28 * s),
                                fill=BG + (int(235 * a),))
            d.text((80 * s, y0 + 30 * s), "AVERAGE LANDING SPOT", font=self.f_mid, fill=(180, 190, 205, int(255 * a)))
            d.text((self.W - 80 * s - d.textlength(f"{self.avg:.0f}", font=self.f_mid), y0 + 30 * s),
                   f"{self.avg:.0f}", font=self.f_mid, fill=(180, 190, 205, int(255 * a)))
            n = len(self.route)
            d.text((80 * s, y0 + 120 * s), "THIS ROUTE", font=self.f_mid, fill=GOLD + (int(255 * a),))
            d.text((self.W - 80 * s - d.textlength(str(n), font=self.f_big), y0 + 70 * s), str(n),
                   font=self.f_big, fill=GOLD + (int(255 * a),))
            img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    W, H = (540, 960) if args.draft else (1080, 1920)
    R.T_END = ROUTE_LEN - 0.3  # route finishes drawing just before the comparison card
    sc = ScanScene(W, H)
    tag = "draft" if args.draft else "final"
    out = Path(args.out) if args.out else OUT / f"scan_{tag}.mp4"
    frames = out.parent / f"scan_frames_{tag}"
    frames.mkdir(parents=True, exist_ok=True)
    n = int(DURATION * FPS)
    for i in range(n):
        sc.frame(i / FPS).save(frames / f"f{i:04d}.png", compress_level=1)
    sc.frame(SCAN_END + 1.9).save(out.with_name(out.stem + "_top5.png"))
    sc.frame(DURATION).save(out.with_suffix(".png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart", str(out)],
                   check=True)
    print(out, f"{DURATION:.1f} s")


if __name__ == "__main__":
    main()
