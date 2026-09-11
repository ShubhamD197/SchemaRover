"""
obfuscate.py — rename a schema the way a real legacy database is named,
without touching its structure.

WHY
---
Benchmark schemas are written in clean English. Spider has `singer`,
`concert`, `stadium`. AdventureWorks has `employeedepartmenthistory` — which
literally contains the words "employee" and "department".

That is why our role breakdown showed name matching already finding almost
every connector table: the names give the answer away.

Production schemas do not look like that. They look like:

    T_EMP_DEPT_HIST_01     FLG_ACTV      DIM_PROD_D      tblOrdHdr

So a benchmark measures name matching on easy mode, and every reported
schema-linking score inherits that. This module lets us measure the same
system on the same questions with the names taken away.

WHAT IT CHANGES AND WHAT IT DOES NOT
------------------------------------
Renamed:   table names, column names.
Untouched: every primary key, every foreign key, the entire graph shape,
           the questions, and the gold answers (they are renamed to match).

So any stage that reads MEANING gets destroyed, and any stage that reads
STRUCTURE is completely unaffected. The gap between the two runs is exactly
how much a method was leaning on friendly naming.

Deterministic: the same schema always produces the same fake names, so runs
are reproducible.
"""

import hashlib

_CONS = "BCDFGHJKLMNPQRSTVWXZ"


def _code(text: str, length: int = 4) -> str:
    """A stable pronounceable-ish consonant code for a name."""
    digest = hashlib.md5(text.encode("utf-8")).digest()
    return "".join(_CONS[b % len(_CONS)] for b in digest[:length])


def _squeeze(name: str, keep: int = 12) -> str:
    """Legacy-style abbreviation: drop vowels, truncate, upper-case.

    `employeedepartmenthistory` -> `MPLYDPRTMNT`
    `film_actor`                -> `FLM_CTR`

    This is the REALISTIC middle case. Column-length limits and house style
    produced thousands of tables named like this. A human still half-reads
    them; an embedding model mostly cannot.
    """
    head = name[0]
    rest = "".join(c for c in name[1:] if c.lower() not in "aeiou" or c == "_")
    return (head + rest)[:keep].upper().strip("_")


def obfuscate_schema(schema: dict, prefix: str = "T", level: str = "opaque"):
    """Return (renamed_schema, {old_lower: new_lower}).

    level="abbrev"  vowels dropped, truncated   -> `MPLYDPRTMNT`
                    realistic legacy naming; some lexical signal survives
    level="opaque"  replaced by a hash code     -> `T_KQVR_17`
                    worst case; no meaning survives at all

    Structure is identical in both. Only the words change.
    """
    if level not in ("abbrev", "opaque"):
        raise ValueError(f"level must be 'abbrev' or 'opaque', got {level!r}")

    tables = sorted(schema["tables"])

    if level == "opaque":
        tmap = {t.lower(): f"{prefix}_{_code(t)}_{i:02d}" for i, t in enumerate(tables)}
    else:
        tmap, used = {}, set()
        for i, t in enumerate(tables):
            cand = _squeeze(t)
            while cand.lower() in used:          # abbreviating can collide
                cand = f"{_squeeze(t, 10)}{i:02d}"
            used.add(cand.lower())
            tmap[t.lower()] = cand

    def cmap(table_name: str, column: str) -> str:
        if level == "abbrev":
            return _squeeze(column, 10)
        # column codes are salted per table, so identical column names in
        # different tables do not accidentally line up and leak a hint
        return f"F_{_code(table_name + '.' + column.lower(), 4)}"

    out = {"tables": {}}
    for name, table in schema["tables"].items():
        new_name = tmap[name.lower()]
        out["tables"][new_name] = {
            "columns": [{"name": cmap(name, c["name"]), "type": c.get("type", "TEXT")}
                        for c in table.get("columns", [])],
            "primary_key": [cmap(name, c) for c in table.get("primary_key", [])],
            "foreign_keys": [
                {
                    "column": cmap(name, fk["column"]),
                    "ref_table": tmap.get(fk["ref_table"].lower(), fk["ref_table"]),
                    "ref_column": cmap(fk["ref_table"], fk["ref_column"]),
                }
                for fk in table.get("foreign_keys", [])
                # a FK to a table that is not in the schema cannot be renamed
                # consistently, so drop it rather than corrupt the graph
                if fk["ref_table"].lower() in tmap
            ],
        }
    return out, {k: v.lower() for k, v in tmap.items()}


def obfuscate_cases(cases, level: str = "opaque"):
    """Rewrite a list of (question, schema, gold, db) with names removed.

    Schemas are cached by identity, so all questions sharing a database keep
    sharing one obfuscated schema object (the embedder cache depends on this).
    """
    seen = {}
    out = []
    for question, schema, gold, db in cases:
        key = id(schema)
        if key not in seen:
            seen[key] = obfuscate_schema(schema, level=level)
        new_schema, tmap = seen[key]
        out.append((question, new_schema, {tmap[g] for g in gold if g in tmap}, db))
    return out


def _self_check():
    schema = {"tables": {
        "employee": {
            "columns": [{"name": "BusinessEntityID", "type": "INT"},
                        {"name": "JobTitle", "type": "TEXT"}],
            "primary_key": ["BusinessEntityID"],
            "foreign_keys": [{"column": "BusinessEntityID", "ref_table": "person",
                              "ref_column": "BusinessEntityID"}]},
        "person": {
            "columns": [{"name": "BusinessEntityID", "type": "INT"},
                        {"name": "FirstName", "type": "TEXT"}],
            "primary_key": ["BusinessEntityID"], "foreign_keys": []},
    }}

    new, tmap = obfuscate_schema(schema)

    # no English survives anywhere
    blob = str(new).lower()
    for word in ("employee", "person", "jobtitle", "firstname", "businessentity"):
        assert word not in blob, f"{word} leaked into {blob}"

    # structure is bit-for-bit preserved
    assert len(new["tables"]) == 2
    from fk_traversal import build_fk_graph
    old_shape = sorted(len(v) for v in build_fk_graph(schema).values())
    new_shape = sorted(len(v) for v in build_fk_graph(new).values())
    assert old_shape == new_shape, (old_shape, new_shape)

    # roles survive, because roles are read from structure not names
    from table_roles import classify_tables
    assert classify_tables(new)[tmap["employee"]] == "subtype"

    # the FK still points at the renamed parent, and the PK column matches it
    emp = new["tables"][tmap["employee"].upper() if False else
                        [t for t in new["tables"] if t.lower() == tmap["employee"]][0]]
    assert emp["foreign_keys"][0]["ref_table"].lower() == tmap["person"]
    assert emp["foreign_keys"][0]["column"] == emp["primary_key"][0]

    # deterministic
    assert obfuscate_schema(schema)[1] == tmap

    # abbrev keeps a readable stub but loses whole words
    ab, abmap = obfuscate_schema(schema, level="abbrev")
    assert abmap["employee"] == "emply", abmap
    assert abmap["person"] == "prsn", abmap
    assert "employee" not in str(ab).lower()
    # structure survives abbreviation too
    assert sorted(len(v) for v in build_fk_graph(ab).values()) == old_shape
    assert classify_tables(ab)[abmap["employee"]] == "subtype"

    print("obfuscate self-check: OK")


if __name__ == "__main__":
    _self_check()
