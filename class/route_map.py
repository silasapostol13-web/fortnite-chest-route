"""Draw an ordered list of chest IDs over the published map."""

from html import escape
from pathlib import Path

from chest_data import CHEST_SPAWNS, MAP_IMAGE_URL, MAP_SIZE, SOURCE_URL


def render_route(chest_ids, output_path="chest_route.html", *, title="Chest route"):
    """Write an auto-zoomed HTML map and return its path."""
    positions = {chest_id: (x, y) for chest_id, _, x, y, _ in CHEST_SPAWNS}
    chest_ids = list(chest_ids)
    points = [positions[chest_id] for chest_id in chest_ids]
    if not points:
        raise ValueError("Provide at least one chest ID to draw.")

    xs, ys = zip(*points)
    width, height = MAP_SIZE
    left, top = max(0, min(xs) - 38), max(0, min(ys) - 38)
    right, bottom = min(width, max(xs) + 38), min(height, max(ys) + 38)
    view_box = f"{left} {top} {right - left} {bottom - top}"
    line = " ".join(f"{x},{y}" for x, y in points)
    markers = "\n".join(
        f'<g><title>{step}. {chest_id}</title><circle cx="{x}" cy="{y}" r="6" />'
        f'<text x="{x}" y="{y}">{step}</text></g>'
        for step, (chest_id, (x, y)) in enumerate(zip(chest_ids, points), 1)
    )
    safe_title = escape(title)
    stops = "".join(f"<li>{chest_id}</li>" for chest_id in chest_ids)
    page = f"""<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
body {{background:#111a24;color:#f6f7f9;font:16px system-ui;margin:0}}
main {{max-width:850px;margin:auto;padding:24px 16px}}
h1 {{margin:0 0 6px}}
svg {{display:block;width:100%;max-height:75vh;background:#243c4d;border-radius:12px}}
a {{color:#b6e4ff}}
circle {{fill:#ffcf55;stroke:#15191f;stroke-width:1}}
text {{fill:#15191f;font:700 5px system-ui;text-anchor:middle;dominant-baseline:central}}
ol {{display:flex;flex-wrap:wrap;gap:4px 32px;padding-left:30px}}
</style>
<main>
<h1>{safe_title}</h1>
<p>Crossbones Isle · {len(set(chest_ids))} distinct chest spawn markers</p>
<svg viewBox="{view_box}" role="img" aria-label="Numbered chest route over Crossbones Isle">
<image href="{MAP_IMAGE_URL}" width="{width}" height="{height}" />
<polyline points="{line}" fill="none" stroke="#16191f" stroke-width="3.2" stroke-linejoin="round" />
<polyline points="{line}" fill="none" stroke="#ffcf55" stroke-width="1.7" stroke-linejoin="round" />
{markers}
</svg>
<ol aria-label="Chest visit order">{stops}</ol>
<p>Markers are possible spawns. <a href="{SOURCE_URL}">Map and spawn data source</a></p>
</main>
</html>
"""
    path = Path(output_path)
    path.write_text(page, encoding="utf-8")
    return path
