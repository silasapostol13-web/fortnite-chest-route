"""Entry point for the Crossbones Isle chest route analyzer."""

from chest_data import CHEST_SPAWNS, CHEST_TARGET, SOURCE_URL
from route_map import render_route
from collections import deque
from heapq import heappop, heappush
from math import dist

# Start here: define Graph and give each instance its own adjacency dictionary.
# Then add operations to register a node, connect two nodes, and view neighbors.
# Build BFS, DFS, and Dijkstra before using the graph in a 20-chest route.
# Pass the finished route's ordered chest IDs to render_route to draw the map.

class Graph:
    def __init__(self):
        self.adjacency = {}
        
    def add_node(self, chest_id):
        if chest_id not in self.adjacency:
            self.adjacency[chest_id] = []
            
    def add_edge(self, first_chest_id, second_chest_id, distance):
        self.add_node(first_chest_id)
        self.add_node(second_chest_id)
        self.adjacency[first_chest_id].append((second_chest_id, distance))
        self.adjacency[second_chest_id].append((first_chest_id, distance))
        
    def neighbor_lookup(self, chest_id):
        return self.adjacency[chest_id]
        
    def bfs(self, start_chest_id):
        queue = deque([start_chest_id])
        visited = {start_chest_id}
        visit_order = []
        
        while queue:
            current = queue.popleft()
            visit_order.append(current)
            
            for neighbor_id, distance in self.neighbor_lookup(current):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append(neighbor_id)
                    
        return visit_order
        
        
    def dfs(self, start_chest_id):
        stack = [start_chest_id]
        visited = set()
        visit_order = []
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            visit_order.append(current)
            
            for neighbor_id, distance in reversed(self.neighbor_lookup(current)):
                if neighbor_id not in visited:
                    stack.append(neighbor_id)
                    
        return visit_order
            
            
    def dijkstra(self, start_chest_id, end_chest_id):
        distances = {start_chest_id: 0}
        previous = {}
        queue = [(0, start_chest_id)]
        
        while queue:
            current_distance, current = heappop(queue)
            if current_distance > distances[current]:
                continue
                
            if current == end_chest_id:
                path = [current]
                while path[-1] != start_chest_id:
                    path.append(previous[path[-1]])
                path.reverse()
                return path, current_distance
                
            for neighbor_id, edge_distance in self.neighbor_lookup(current):
                new_distance = current_distance + edge_distance
                if new_distance < distances.get(neighbor_id, float("inf")):
                    distances[neighbor_id] = new_distance
                    previous[neighbor_id] = current
                    heappush(queue, (new_distance, neighbor_id))
                  
        return [], float("inf")


def build_sample_graph():
    graph = Graph()

    chest_ids = ("C305", "C264", "C265", "C261", "C266", "C257", "C250", "C256")

    positions = {}
    for chest_id, area, x, y, source_ref in CHEST_SPAWNS:
        positions[chest_id] = (x, y)

    for chest_id in chest_ids:
        graph.add_node(chest_id)

    connections = (
        ("C305", "C264"),
        ("C305", "C256"),
        ("C264", "C265"),
        ("C265", "C261"),
        ("C261", "C266"),
        ("C261", "C257"),
        ("C266", "C257"),
        ("C257", "C250"),
        ("C250", "C256"),
    )

    for first_chest_id, second_chest_id in connections:
        distance = dist(positions[first_chest_id], positions[second_chest_id])
        graph.add_edge(first_chest_id, second_chest_id, distance)

    return graph


if __name__ == "__main__":
    print(f"Crossbones Isle | {len(CHEST_SPAWNS)} candidate spawns | target: {CHEST_TARGET}")
    print(f"Spawn data: {SOURCE_URL}")
    
    graph = build_sample_graph()
    start_chest_id = "C305"
    end_chest_id = "C257"

    print("Crossbones Isle chest network")
    print("Connections (map pixels)")
    for chest_id in graph.adjacency:
        neighbors = graph.neighbor_lookup(chest_id)
        connections = ", ".join(
            f"{neighbor_id} ({distance:.2f})"
            for neighbor_id, distance in neighbors
        )
        print(f"  {chest_id}: {connections or 'no neighbors'}")

    bfs_order = graph.bfs(start_chest_id)
    print(f"\nBFS from {start_chest_id}: {' → '.join(bfs_order)}")

    dfs_order = graph.dfs(start_chest_id)
    print(f"DFS from {start_chest_id}: {' → '.join(dfs_order)}")

    path, total_distance = graph.dijkstra(start_chest_id, end_chest_id)
    if path:
        print(f"\nShortest path: {' → '.join(path)}")
        print(f"Total distance: {total_distance:.2f} map pixels")
    else:
        print(f"\nNo path from {start_chest_id} to {end_chest_id}.")
