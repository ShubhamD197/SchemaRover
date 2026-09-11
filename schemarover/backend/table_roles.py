"""
table_roles.py — what KIND of table is this, judged from the catalog alone.

WHY THIS EXISTS
---------------
Some tables exist to describe something ("customer", "product"). Others exist
only to CONNECT two other tables. The connectors are the ones that break
retrieval, because:

  * nobody names them in a question — you say "employees and their
    departments", never "employee department history";
  * their names carry almost no meaning, so semantic matching cannot find
    them either;
  * and the query is impossible without them.

In AdventureWorks, `employee` has no DepartmentID column at all. The ONLY
route from an employee to a department is through `employeedepartmenthistory`.

So we detect connectors from structure, not from names. Names can be
`T_EMP_DEPT_HIST_01` and this still works — that is the whole point.

THE RULES
---------
Let PK = the primary-key columns, FKCOLS = every column that is a foreign key.

  junction     PK is made ENTIRELY of foreign keys, pointing at >= 2 tables.
               A pure many-to-many link row. Example: salesorderheadersalesreason
               PK (SalesOrderID, SalesReasonID) — both FKs, nothing else.

  subtype      PK is entirely ONE foreign key. A 1:1 extension of its parent —
               the same real-world thing, with its attributes split across two
               tables. Example: employee PK (BusinessEntityID) -> person.
               `employee` holds JobTitle and HireDate; `person` holds FirstName
               and LastName. Ask for an employee's name and you MUST join both.

  weak_entity  PK CONTAINS a foreign key but also has extra columns of its own.
               It cannot exist without its parent, and the extra columns tell
               its rows apart. Example: employeedepartmenthistory
               PK (BusinessEntityID, DepartmentID, ShiftID, StartDate)
               — three FKs plus StartDate as the discriminator.

  entity       everything else. Stands on its own.

Both junction and weak_entity are "connectors" — see is_connector().

All three dependent roles share one consequence, handled by identity_parents()
and close_over_identity(): a table whose PRIMARY KEY contains a foreign key
cannot be understood without that parent, so the parent comes along whenever
the child is picked.

This is the textbook definition of an identifying relationship, read straight
off the catalog. No training, no names, no configuration.
"""


def _cols(table, key):
    return {c.lower() for c in table.get(key, [])}


def classify_tables(schema: dict) -> dict:
    """Return {table_name_lower: role} for every table in the schema."""
    roles = {}
    for name, table in schema["tables"].items():
        pk = _cols(table, "primary_key")
        fks = table.get("foreign_keys", [])
        fk_cols = {fk["column"].lower() for fk in fks}
        # Only parents reached THROUGH the primary key count. A subtype like
        # `salesperson` (PK = BusinessEntityID -> employee) also has a
        # TerritoryID FK, but that one is not part of its identity, so it is
        # an entity, not a junction.
        parents = {fk["ref_table"].lower() for fk in fks if fk["column"].lower() in pk}

        if pk and fk_cols and pk <= fk_cols and len(parents) >= 2:
            role = "junction"
        elif pk and fk_cols and pk <= fk_cols and len(parents) == 1:
            role = "subtype"
        elif pk and (pk & fk_cols) and (pk - fk_cols):
            role = "weak_entity"
        else:
            role = "entity"

        roles[name.lower()] = role
    return roles


def is_connector(role: str) -> bool:
    """Connector tables exist to link other tables, not to describe anything."""
    return role in ("junction", "weak_entity")


def connector_tables(schema: dict) -> set:
    return {t for t, r in classify_tables(schema).items() if is_connector(r)}


def identity_parents(schema: dict) -> dict:
    """{table: {parents it cannot be understood without}}.

    THE RULE: if a foreign key is part of a table's PRIMARY KEY, then that
    parent is part of what the row *is*, not merely something it points at.
    Keep the child, and you must keep the parent.

    This one rule covers all three dependent roles:

      subtype      `employee` PK = (BusinessEntityID) -> person
                   Names live in `person`. Ask "which employee" and you need
                   both halves.

      junction     `film_category` PK = (film_id, category_id) -> film, category
                   On its own it is two meaningless integers. You cannot filter
                   for "Comedy" without `category`.

      weak_entity  `employeedepartmenthistory`
                   PK = (BusinessEntityID, DepartmentID, ShiftID, StartDate)
                   -> employee, department, shift

    Foreign keys OUTSIDE the primary key are deliberately excluded. They are
    ordinary references, not identity — `salesperson.TerritoryID` does not make
    a territory part of what a salesperson is.
    """
    out = {}
    for name, table in schema["tables"].items():
        pk = _cols(table, "primary_key")
        if not pk:
            continue
        parents = {fk["ref_table"].lower() for fk in table.get("foreign_keys", [])
                   if fk["column"].lower() in pk}
        parents.discard(name.lower())          # self-reference is not a parent
        if parents:
            out[name.lower()] = parents
    return out


def close_over_identity(tables, schema, max_rounds: int = 3) -> set:
    """Add every identity parent of everything in `tables`, repeatedly.

    Repeats because a parent can itself be dependent: a junction can point at
    a subtype, which points at its own parent. Bounded so a cyclic schema
    cannot spin.
    """
    parents = identity_parents(schema)
    by_lower = {t.lower(): t for t in schema["tables"]}

    result = set(tables)
    for _ in range(max_rounds):
        grown = set(result)
        for table in result:
            for parent in parents.get(table.lower(), ()):
                if parent in by_lower:
                    grown.add(by_lower[parent])
        if grown == result:
            break
        result = grown
    return result


def _self_check():
    schema = {"tables": {
        # plain entity: PK is its own column, no FK in the key
        "employee": {
            "columns": [], "primary_key": ["BusinessEntityID"],
            "foreign_keys": [{"column": "BusinessEntityID",
                              "ref_table": "person", "ref_column": "BusinessEntityID"}],
        },
        # weak entity: PK = 3 FKs + StartDate discriminator
        "employeedepartmenthistory": {
            "columns": [], "primary_key": ["BusinessEntityID", "StartDate",
                                           "DepartmentID", "ShiftID"],
            "foreign_keys": [
                {"column": "BusinessEntityID", "ref_table": "employee", "ref_column": "x"},
                {"column": "DepartmentID", "ref_table": "department", "ref_column": "x"},
                {"column": "ShiftID", "ref_table": "shift", "ref_column": "x"},
            ],
        },
        # pure junction: PK is exactly two FKs
        "salesorderheadersalesreason": {
            "columns": [], "primary_key": ["SalesOrderID", "SalesReasonID"],
            "foreign_keys": [
                {"column": "SalesOrderID", "ref_table": "salesorderheader", "ref_column": "x"},
                {"column": "SalesReasonID", "ref_table": "salesreason", "ref_column": "x"},
            ],
        },
        # the parent half of the employee subtype
        "person": {
            "columns": [], "primary_key": ["BusinessEntityID"], "foreign_keys": [],
        },
        "shift": {
            "columns": [], "primary_key": ["ShiftID"], "foreign_keys": [],
        },
        # standalone lookup: no FKs at all
        "department": {
            "columns": [], "primary_key": ["DepartmentID"], "foreign_keys": [],
        },
    }}

    roles = classify_tables(schema)
    assert roles["department"] == "entity", roles
    assert roles["salesorderheadersalesreason"] == "junction", roles
    assert roles["employeedepartmenthistory"] == "weak_entity", roles

    # `employee`'s PK is also its ONLY FK -> a 1:1 extension of person
    assert roles["employee"] == "subtype", roles

    assert connector_tables(schema) == {
        "employeedepartmenthistory", "salesorderheadersalesreason"}, connector_tables(schema)

    # the half of `employee` that holds the names comes along with it
    ip = identity_parents(schema)
    assert ip["employee"] == {"person"}, ip
    assert ip["salesorderheadersalesreason"] == {"salesorderheader", "salesreason"}, ip
    assert ip["employeedepartmenthistory"] == {"employee", "department", "shift"}, ip
    assert "department" not in ip, ip           # stands alone, no identity parents

    # closure: employee drags person; the bridge drags all three of its parents
    assert close_over_identity({"employee"}, schema) == {"employee", "person"}
    assert close_over_identity({"employeedepartmenthistory"}, schema) == {
        "employeedepartmenthistory", "employee", "department", "shift", "person"}

    print("table_roles self-check: OK")


if __name__ == "__main__":
    _self_check()
