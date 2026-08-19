"""
fk_traversal.py — stage 3 of schema linking.

Builds an undirected graph out of the foreign keys and walks outward from
the tables the first two stages matched, to pull in connecting tables that
the question never named. "Singers and their concerts" needs the link
table `singer_in_concert`, which nobody says out loud.

WHY THERE IS NOW A `max_degree` KNOB (task A1)
----------------------------------------------
Walking one hop outward is cheap on a small database and expensive on a
real one, because real databases have HUB tables. In AdventureWorks about
fifteen tables point at `product`. So the moment `product` is matched, one
hop drags in all fifteen — and the question "how many products do we sell?"
ends up sending half the database.

Measured, one hop adds:

    Spider         (4.5 tables avg)   +1.3 tables
    Sakila         (16 tables)        +3.3 tables
    AdventureWorks (68 tables)       +15.3 tables

`max_degree` caps this: if a table has more neighbours than the cap, we do
NOT expand outward from it. The table itself is still kept if a matcher
picked it — we just refuse to inherit its entire neighbourhood.

    max_degree=None   expand from everything (the original behaviour)
    max_degree=4      do not expand out of any table with >4 neighbours

Note this caps expansion FROM a hub, not INTO one. At one hop that is the
mechanism that matters: the cost of a hop is decided by how many neighbours
each already-matched table has.

Sweep it and read the curve before picking a value:
    python eval_harness.py adventureworks --sweep-degree
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


def expand_with_fk_traversal(matched_tables, schema, max_hops: int = 1,
                             max_degree: int | None = None):
    """Grow the matched set outward along foreign keys.

    max_degree: if set, never expand outward from a table that has more
                than this many foreign-key neighbours (a hub). See the
                module docstring.
    """
    graph = build_fk_graph(schema)
    result = set(matched_tables)
    frontier = set(matched_tables)

    for _ in range(max_hops):
        next_frontier = set()
        for table in frontier:
            neighbors = graph.get(table, set())
            if max_degree is not None and len(neighbors) > max_degree:
                continue  # hub — inheriting its whole neighbourhood floods the prompt
            next_frontier |= neighbors
        result |= next_frontier
        frontier = next_frontier

    return list(result)


def _self_check():
    """One star-shaped schema: `hub` is referenced by 5 leaves. Expanding
    from a leaf should reach the hub; expanding from the hub should be
    blocked once max_degree drops below its neighbour count."""
    schema = {"tables": {"hub": {"columns": [], "primary_key": [], "foreign_keys": []}}}
    for i in range(5):
        schema["tables"][f"leaf{i}"] = {
            "columns": [], "primary_key": [],
            "foreign_keys": [{"column": "hub_id", "ref_table": "hub", "ref_column": "id"}],
        }

    # no cap: starting at the hub pulls in all 5 leaves
    assert len(expand_with_fk_traversal(["hub"], schema)) == 6

    # cap below the hub's degree: the hub stays, its neighbourhood does not
    assert expand_with_fk_traversal(["hub"], schema, max_degree=4) == ["hub"]

    # a leaf has 1 neighbour, so it still reaches the hub under the same cap
    assert set(expand_with_fk_traversal(["leaf0"], schema, max_degree=4)) == {"leaf0", "hub"}

    print("fk_traversal self-check: OK")


if __name__ == "__main__":
    _self_check()
