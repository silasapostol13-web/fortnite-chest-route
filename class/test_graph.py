"""Run the required graph checks and print expected and actual results."""

from math import inf

from main import Graph, build_sample_graph


def check(label, expected, actual):
    print(f"\n{label}")
    print(f"  Expected: {expected}")
    print(f"  Actual:   {actual}")
    assert actual == expected, label
    print("  PASS")


if __name__ == "__main__":
    fortnite = build_sample_graph()
    check(
        "Fortnite BFS order",
        ["C305", "C264", "C256", "C265", "C250", "C261", "C257", "C266"],
        fortnite.bfs("C305"),
    )
    check(
        "Fortnite DFS order",
        ["C305", "C264", "C265", "C261", "C266", "C257", "C250", "C256"],
        fortnite.dfs("C305"),
    )

    graph = Graph()
    graph.add_edge("A", "B", 8)
    graph.add_edge("A", "C", 2)
    graph.add_edge("B", "D", 3)
    graph.add_edge("C", "B", 2)
    graph.add_edge("C", "D", 10)
    graph.add_node("E")

    check("E has no neighbors", [], graph.neighbor_lookup("E"))
    check("Dijkstra cannot reach E from A", ([], inf), graph.dijkstra("A", "E"))
    check("BFS on a cyclic graph", ["A", "B", "C", "D"], graph.bfs("A"))
    check("DFS on a cyclic graph", ["A", "B", "D", "C"], graph.dfs("A"))
    check(
        "Dijkstra shortest path from A to D",
        (["A", "C", "B", "D"], 7),
        graph.dijkstra("A", "D"),
    )
