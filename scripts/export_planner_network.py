"""Export the terrain and travel times needed for in-browser replanning."""

from base64 import b64encode
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from route import params, planner_source as source
from route.travel import LegPather, compute_travel_matrix


def main():
    _, labels, coordinates = source.load_spawns()
    with (source.PLANNER_DIR / "chest_spawns.csv").open(newline="", encoding="utf-8") as file:
        guaranteed = {
            (float(row["x_percent"]) * source.MAP_SIZE[0] / 100,
             float(row["y_percent"]) * source.MAP_SIZE[1] / 100)
            for row in csv.DictReader(file) if row["type"] == "guaranteed"
        }
    terrain = LegPather(source.MAP_IMAGE, source.MAP_SIZE)
    matrix = compute_travel_matrix(coordinates, terrain.graph)
    # 0.01 seconds per unit, round up so quantization cannot overrun the budget.
    times = np.ceil(np.minimum(matrix * 100, 65535)).astype("<u2")
    payload = {
        "stops": [[round(float(x), 2), round(float(y), 2), label, (x, y) in guaranteed]
                  for (x, y), label in zip(coordinates, labels)],
        "times": b64encode(times.tobytes()).decode(),
        "water": b64encode(terrain.cell_water.astype("u1").tobytes()).decode(),
        "cols": terrain.cell_water.shape[1],
        "cell": params.CELL_PX,
        "meter": params.METERS_PER_PX,
        "run": params.RUN_SPEED,
        "swim": params.SWIM_SPEED,
        "stop": params.CHEST_STOP_S,
        "busSpeed": params.BUS_SPEED,
        "fall": params.FALL_BASE_S,
        "glide": params.GLIDE_SPEED,
        "reach": params.MAX_DROP_REACH_M,
        "storm": params.STORM1_CLOSES_S,
    }
    (source.PLANNER_DIR / "network.js").write_text(
        "window.DROP_NETWORK=" + json.dumps(payload, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
