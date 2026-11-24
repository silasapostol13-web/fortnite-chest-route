"""Crossbones Isle chest snapshot for the standalone drop planner.

SequeLariFN's map feed publishes api-fortnite game-file chest positions as
percentages in the game's minimap coordinate frame. The CSV keeps every chest record
in the feed. The solver uses standard chests and groups overlapping positions
because its top-down graph cannot distinguish floors.

Snapshot generated 2026-11-24 at 20:30 UTC. POI names come from api-fortnite;
each position is assigned to the nearest named POI.
"""

import csv
from pathlib import Path

import numpy as np

PLANNER_DIR = Path(__file__).resolve().parent.parent / "planner"
MAP_IMAGE = PLANNER_DIR / "map.webp"
MAP_IMAGE_URL = (
    "https://raw.githubusercontent.com/yaelbrinkert/fortnite-archives/main/"
    "chapter_7/season_5/43_11/Apollo_Terrain_Minimap.png"
)
POI_SOURCE_URL = "https://www.sequelarifn.com.br/dados/api/v1/map"
SOURCE_URL = "https://www.sequelarifn.com.br/dados/mapa-objetos"
MAP_VERSION = "43.11"
SNAPSHOT_DATE = "2026-11-24"
MAP_SIZE = (1500, 1500)
METERS_PER_PX = 1.7  # Approximate scale used in the existing travel model.
STANDARD_RECORD_COUNT = 901
STANDARD_STOP_COUNT = 900
TOTAL_RECORD_COUNT = 1007


def load_spawns():
    """Return ids, nearest POI labels, and logical map coordinates."""
    standard_types = {"regular", "guaranteed"}
    by_position = {}
    width, height = MAP_SIZE
    with (PLANNER_DIR / "chest_spawns.csv").open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["type"] not in standard_types:
                continue
            x = float(row["x_percent"]) * width / 100
            y = float(row["y_percent"]) * height / 100
            by_position.setdefault((x, y), (row["id"], row["area"]))

    ids, areas = zip(*by_position.values())
    return list(ids), list(areas), np.array(list(by_position), dtype=float)
