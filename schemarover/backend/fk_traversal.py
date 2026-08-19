"""
Your fk_traversal.py, copied verbatim (build_fk_graph +
expand_with_fk_traversal). Unchanged so the harness measures your logic.
"""

from collections import defaultdict


def build_fk_graph(schema: dict) -> dict:
    graph = defaultdict(set)
    for table_name, table_info in schema["tables"].items():
        for fk in table_info["foreign_keys"]:
            ref_table = fk["ref_table"]
            graph[table_name].add(ref_table)
            graph[ref_table].add(table_name)
    return graph


def expand_with_fk_traversal(matched_tables, schema, max_hops: int = 1):
    graph = build_fk_graph(schema)
    result = set(matched_tables)
    frontier = set(matched_tables)
    for _ in range(max_hops):
        next_frontier = set()
        for table in frontier:
            neighbors = graph.get(table, set())
            next_frontier |= neighbors
        result |= next_frontier
        frontier = next_frontier
    return list(result)
