"""Route card to follow in-game: numbered chests on the map, direction, distance, target split.

    .venv/bin/python -m route.card      # uses out/best_landing.json (from route.scan)

Writes out/route_card.json (used by ``route.scan --calibrate``), out/route_card.md and
out/route_card.png. The spawn data has no landmark names below area level, so the
numbered map is the landmark: chest N on the card is circle N on the picture.
"""

from __future__ import annotations

import json
from math import atan2, degrees, hypot
from pathlib import Path

from PIL import Image, ImageDraw

from . import params as P
from .render import BG, GOLD, WHITE, Scene, font
from .travel import load_spawns, travel_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
DIRS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]  # screen y points south


def compass(a, b):
    ang = degrees(atan2(b[1] - a[1], b[0] - a[0])) % 360
    return DIRS[int((ang + 22.5) // 45) % 8]


def mmss(t):
    t = int(round(t))
    return f"{t // 60}:{t % 60:02d}"


def build_steps(route, T, xy):
    steps, walk, t = [], 0.0, P.CHEST_STOP_S
    steps.append({"n": 1, "chest": route[0], "dir": "land", "meters": 0, "walk_s_cum": 0.0, "split_s": t})
    for n, (a, b) in enumerate(zip(route, route[1:]), start=2):
        walk += T[a, b]
        t += T[a, b] + P.CHEST_STOP_S
        m = hypot(*(xy[b] - xy[a])) * P.METERS_PER_PX
        steps.append({"n": n, "chest": b, "dir": compass(xy[a], xy[b]), "meters": round(m),
                      "walk_s_cum": round(float(walk), 2), "split_s": round(float(t), 1)})
    return steps


def main():
    data = json.loads((OUT / "best_landing.json").read_text())
    ids, areas, xy = load_spawns()
    T = travel_matrix()
    route = data["route_idx"]
    steps = build_steps(route, T, xy)
    for s in steps:
        s["id"] = ids[s["chest"]]
    (OUT / "route_card.json").write_text(json.dumps({"area": data["area"], "steps": steps}, indent=1))

    lines = [f"# Route card: {data['area']}, {len(steps)} chest spots in {mmss(steps[-1]['split_s'])}", "",
             "Land on circle 1. Open, then go to the next number. Targets are from the model; after a run, "
             "put your real times in a CSV (chest,real_time) and run `python -m route.scan --calibrate file.csv`.", "",
             "| # | go | about | open by |", "|---|---|---|---|"]
    for s in steps:
        go = "land here" if s["dir"] == "land" else s["dir"]
        lines.append(f"| {s['n']} | {go} | {s['meters']} m | {mmss(s['split_s'])} |")
    (OUT / "route_card.md").write_text("\n".join(lines) + "\n")

    # picture
    W, H = 1080, 1920
    sc = Scene(W, H)
    rxy = xy[route]
    (x0, y0), (x1, y1) = rxy.min(0), rxy.max(0)
    wid = max(x1 - x0 + 30, (y1 - y0 + 30) * W / (H * 0.45), 90)
    scale = W / wid
    # route centred in the top 60% of the card
    cam = ((x0 + x1) / 2, (y0 + y1) / 2 + (0.52 - 0.31) * H / scale, wid)
    img = sc.base(cam).convert("RGBA")
    top = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(top)
    s = 1.0
    to = lambda x, y: sc.to_screen(cam, x, y)  # noqa: E731
    for pts, _, _ in sc.legs:
        p = [to(x, y) for x, y in pts]
        d.line(p, fill=(20, 16, 8, 255), width=11, joint="curve")
        d.line(p, fill=GOLD + (255,), width=6, joint="curve")
    fnum = font(22)
    for st in steps:
        px, py = to(*xy[st["chest"]])
        r = 17
        fill = (255, 70, 90, 255) if st["n"] == 1 else GOLD + (255,)
        d.ellipse((px - r, py - r, px + r, py + r), fill=fill, outline=(20, 16, 8, 255), width=3)
        label = str(st["n"])
        tw = d.textlength(label, font=fnum)
        d.text((px - tw / 2, py - 14), label, font=fnum, fill=(20, 16, 8, 255))
    img = Image.alpha_composite(img, top)
    # list panel
    panel_y = int(H * 0.60)
    pd = ImageDraw.Draw(img)
    pd.rectangle((0, panel_y, W, H), fill=BG + (245,))
    ft, fr = font(44), font(27)
    pd.text((40, 40), f"LAND: {data['area'].upper()}", font=ft, fill=WHITE)
    pd.text((40, 98), f"{len(steps)} chest spots in {mmss(steps[-1]['split_s'])}", font=font(34), fill=GOLD)
    col_rows = (len(steps) + 1) // 2
    row_h = min(40, (H - panel_y - 40) // max(col_rows, 1))
    for i, st in enumerate(steps):
        col, row = divmod(i, col_rows)
        x, y = 40 + col * 520, panel_y + 24 + row * row_h
        go = "LAND" if st["dir"] == "land" else f"{st['dir']:>2} {st['meters']:>3} m"
        pd.text((x, y), f"{st['n']:>2}", font=fr, fill=GOLD)
        pd.text((x + 56, y), go, font=fr, fill=WHITE)
        pd.text((x + 330, y), mmss(st["split_s"]), font=fr, fill=(180, 190, 205))
    img.convert("RGB").save(OUT / "route_card.png")
    print(OUT / "route_card.png", OUT / "route_card.md", f"{len(steps)} steps")


if __name__ == "__main__":
    main()
