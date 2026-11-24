"""Island-wide Crossbones Isle v43.00 regular chest spawn data.

Crisis game-file records via Pirate Shop Planner, November 11, 2026.
Coordinates are logical image pixels. Records sharing a map position are
grouped as one stop because the source does not identify separate floors.
"""

import csv
from pathlib import Path

SOURCE_URL = "https://fortnitepirateshoptoken.org/fortnite-chest-map/"
MAP_IMAGE_URL = "https://fortnitepirateshoptoken.org/site/maps/crossbones-isle-43.00.webp"
MAP_SIZE = (1212, 1298)
CHEST_TARGET = 20


def load_chest_spawns():
    """Read tuples containing chest ID, area, x, y, and source reference."""
    path = Path(__file__).with_name("chest_spawns.csv")
    with path.open(newline="", encoding="utf-8") as file:
        return tuple(
            (row["id"], row["area"], float(row["x"]), float(row["y"]), row["source_ref"])
            for row in csv.DictReader(file)
        )


CHEST_SPAWNS = load_chest_spawns()
