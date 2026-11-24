"""Optional demo: compare 20-stop routes from each mapped chest spawn."""

from math import dist

from chest_data import CHEST_SPAWNS, CHEST_TARGET
from route_map import render_route


def recommend_landing(positions, target):
    """Return chest IDs and total map distance for the best greedy route found."""
    if not 1 <= target <= len(positions):
        raise ValueError("The target must be between one and the number of spawns.")

    chest_ids = sorted(positions)
    points = [positions[chest_id] for chest_id in chest_ids]
    distances = [[dist(start, end) for end in points] for start in points]
    nearest = [sorted(range(len(points)), key=row.__getitem__) for row in distances]

    best_route = []
    best_distance = float("inf")
    for start in range(len(points)):
        route = [start]
        visited = {start}
        total_distance = 0
        while len(route) < target:
            current = route[-1]
            next_stop = next(chest for chest in nearest[current] if chest not in visited)
            total_distance += distances[current][next_stop]
            route.append(next_stop)
            visited.add(next_stop)
        if total_distance < best_distance:
            best_route = route
            best_distance = total_distance

    return [chest_ids[chest] for chest in best_route], best_distance


if __name__ == "__main__":
    positions = {chest_id: (x, y) for chest_id, _, x, y, _ in CHEST_SPAWNS}
    areas = {chest_id: area for chest_id, area, *_ in CHEST_SPAWNS}
    route, total_distance = recommend_landing(positions, CHEST_TARGET)
    landing = route[0]
    title = f"Land at {landing} · {areas[landing]}"
    map_path = render_route(route, title=title)
    print(title)
    print(f"Compared {len(positions)} landing spots.")
    print(f"Route: {' → '.join(route)}")
    print(f"Modeled distance: {total_distance:.1f} map pixels")
    print(f"Map: {map_path}")
