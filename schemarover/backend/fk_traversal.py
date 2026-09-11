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


# ---------------------------------------------------------------------------
# PATH COMPLETION — the fix for the precision collapse
# ---------------------------------------------------------------------------
#
# THE PROBLEM WITH EXPANDING OUTWARD
# ----------------------------------
# expand_with_fk_traversal() asks the wrong question. It asks:
#
#     "who is next to a table I matched?"
#
# On AdventureWorks `employee` has 7 neighbours and `person` has 7 more, so
# matching three tables drags in about twenty. Measured: lexical+semantic
# sends 20.4 tables, and adding one blind hop takes it to 39.3 out of 68.
# Precision falls to 6.9%.
#
# THE RIGHT QUESTION
# ------------------
#     "does this table sit BETWEEN two things the user asked about?"
#
# That is what a join path is. A table earns its place in the prompt only if
# it CONNECTS two matched tables — not merely because it touches one.
#
#     "Show every employee and the department they work in"
#
#     matched: employee, department, person
#
#     employeedepartmenthistory  employee --1--> it --1--> department
#                                1 + 1 == 2, it lies on the path      KEEP
#     employeepayhistory         touches employee, leads nowhere else  DROP
#     jobcandidate               touches employee, leads nowhere else  DROP
#     salesperson, document, purchaseorderheader, ...                  DROP
#
# Four tables instead of thirty-nine, and the one table nobody would ever
# name out loud is still there.
#
# HOW "BETWEEN" IS DECIDED
# ------------------------
# Standard shortest-path membership. Node c lies on a shortest path between
# seeds s1 and s2 when
#
#     dist(s1, c) + dist(c, s2) == dist(s1, s2)
#
# We only look at pairs no further apart than `max_path_len`, so this stays
# cheap: one BFS per seed, each cut off at that depth.
#
# max_path_len=2 means "allow at most one table in the middle", which covers
# junction and weak-entity tables — the case that actually matters. Raise it
# to 3 to allow two-table bridges, at some cost in precision.

from collections import deque


def _bfs(graph, start, limit):
    """Distances from `start`, giving up past `limit` hops."""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if dist[node] >= limit:
            continue
        for neighbor in graph.get(node, ()):
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                queue.append(neighbor)
    return dist


def expand_with_path_completion(matched_tables, schema, max_path_len: int = 2,
                                include_identity_parents: bool = True):
    """Keep a table only if it lies on a short path BETWEEN two matched tables.

    Unlike expand_with_fk_traversal this never inherits a hub's neighbourhood,
    because a neighbour that leads nowhere else is not on a path to anything.

    include_identity_parents additionally pulls in any table that a matched
    table cannot be understood without — the parents named in its PRIMARY KEY.
    The path rule alone cannot do this, because such a parent is often a dead
    end that no path runs through:

        `employee` -> `person`         the names live in the parent
        `film_category` -> `category`  the junction is two bare integers

    These are not expansions. They are the rest of the thing already matched.
    See table_roles.close_over_identity.

    With fewer than two matched tables there are no pairs and so nothing to
    connect — the seed set is returned unchanged. That is correct: a
    single-table question needs no join.
    """
    graph = build_fk_graph(schema)
    seeds = set(matched_tables)

    if include_identity_parents:
        from table_roles import close_over_identity
        seeds = close_over_identity(seeds, schema)

    seeds = sorted(seeds)
    result = set(seeds)

    if len(seeds) < 2:
        return list(result)

    dist = {s: _bfs(graph, s, max_path_len) for s in seeds}

    for i, s1 in enumerate(seeds):
        d1 = dist[s1]
        for s2 in seeds[i + 1:]:
            d2 = dist[s2]
            gap = d1.get(s2)
            # unreachable, too far, or already touching (nothing sits between)
            if gap is None or gap > max_path_len or gap < 2:
                continue
            for node, dn in d1.items():
                if node not in result and dn + d2.get(node, 1 << 30) == gap:
                    result.add(node)

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

    _path_completion_self_check()
    print("fk_traversal self-check: OK")


def _path_completion_self_check():
    """The real AdventureWorks shape, shrunk down.

    employee is a hub: the bridge to department hangs off it, but so do three
    dead-end tables that no question about departments ever needs.
    """
    def fk(col, ref):
        return {"column": col, "ref_table": ref, "ref_column": "id"}

    schema = {"tables": {
        "department": {"columns": [], "primary_key": ["DepartmentID"], "foreign_keys": []},
        "person":     {"columns": [], "primary_key": ["BusinessEntityID"], "foreign_keys": []},
        "shift":      {"columns": [], "primary_key": ["ShiftID"], "foreign_keys": []},
        "employee": {"columns": [], "primary_key": ["BusinessEntityID"],
                     "foreign_keys": [fk("BusinessEntityID", "person")]},
        # the bridge — the only route from employee to department
        "employeedepartmenthistory": {
            "columns": [], "primary_key": ["BusinessEntityID", "DepartmentID",
                                           "ShiftID", "StartDate"],
            "foreign_keys": [fk("BusinessEntityID", "employee"),
                             fk("DepartmentID", "department"),
                             fk("ShiftID", "shift")]},
        # dead ends hanging off the employee hub
        "employeepayhistory": {"columns": [], "primary_key": ["BusinessEntityID", "RateChangeDate"],
                               "foreign_keys": [fk("BusinessEntityID", "employee")]},
        "jobcandidate":       {"columns": [], "primary_key": ["JobCandidateID"],
                               "foreign_keys": [fk("BusinessEntityID", "employee")]},
        "salesperson":        {"columns": [], "primary_key": ["BusinessEntityID"],
                               "foreign_keys": [fk("BusinessEntityID", "employee")]},
    }}

    seeds = ["employee", "department", "person"]

    # blind expansion inherits the whole employee neighbourhood
    blind = set(expand_with_fk_traversal(seeds, schema, max_hops=1))
    assert "employeepayhistory" in blind and "jobcandidate" in blind, blind
    assert len(blind) == 7, blind

    # path completion keeps the bridge and drops every dead end
    got = set(expand_with_path_completion(seeds, schema))
    assert got == {"employee", "department", "person",
                   "employeedepartmenthistory"}, got

    # employee is a 1:1 subtype of person, so person is pulled in even when
    # it was never matched and sits on no path
    got2 = set(expand_with_path_completion(["employee", "department"], schema))
    assert "person" in got2, got2
    assert "employeepayhistory" not in got2, got2
    without = set(expand_with_path_completion(["employee", "department"], schema,
                                              include_identity_parents=False))
    assert "person" not in without, without

    # one seed alone means no pairs, so nothing is CONNECTED — but the
    # subtype's other half still comes along, because it is the same entity
    assert set(expand_with_path_completion(["employee"], schema)) == {"employee", "person"}
    assert set(expand_with_path_completion(
        ["employee"], schema, include_identity_parents=False)) == {"employee"}

    # a bridge two hops away is out of reach at the default, found at 3
    far = {"tables": {
        "a": {"columns": [], "primary_key": ["id"], "foreign_keys": []},
        "m1": {"columns": [], "primary_key": ["id"], "foreign_keys": [fk("a_id", "a")]},
        "m2": {"columns": [], "primary_key": ["id"], "foreign_keys": [fk("m1_id", "m1")]},
        "b": {"columns": [], "primary_key": ["id"], "foreign_keys": [fk("m2_id", "m2")]},
    }}
    assert set(expand_with_path_completion(["a", "b"], far)) == {"a", "b"}
    assert set(expand_with_path_completion(["a", "b"], far, max_path_len=3)) == {
        "a", "b", "m1", "m2"}


if __name__ == "__main__":
    _self_check()
