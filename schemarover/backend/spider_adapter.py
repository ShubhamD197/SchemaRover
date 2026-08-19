"""
spider_adapter.py

Bridges Spider's tables.json into the exact schema-dict shape your
schema_introspect.get_schema() emits, so lexical_match / semantic /
fk_traversal run against Spider databases with ZERO changes to your code.

get_schema() shape (from your schema_introspect.py):
    {
      "tables": {
        "<table>": {
          "columns": [{"name": ..., "type": ...}, ...],
          "primary_key": [...],
          "foreign_keys": [
            {"column": ..., "ref_table": ..., "ref_column": ...}, ...
          ],
        }, ...
      }
    }

Also provides gold-table extraction from each dev query's parsed sql,
walking nested subqueries (where/having) and set ops
(intersect/union/except) so the ground truth is complete.
"""

import json


def build_schema_dict(tbl_entry: dict) -> dict:
    """Convert one tables.json entry -> your get_schema() dict shape."""
    tnames = tbl_entry["table_names_original"]
    cnames = tbl_entry["column_names_original"]   # [[tbl_idx, col_name], ...], [-1,'*'] first
    ctypes = tbl_entry["column_types"]            # parallel to cnames but WITHOUT the star? -> see note

    # column_types is parallel to column_names (same length, includes the star slot in Spider).
    # Guard length just in case.
    def col_type(i):
        return ctypes[i] if i < len(ctypes) else "text"

    schema = {"tables": {}}
    for t_idx, tname in enumerate(tnames):
        schema["tables"][tname] = {
            "columns": [],
            "primary_key": [],
            "foreign_keys": [],
        }

    # columns
    for col_idx, (t_idx, col_name) in enumerate(cnames):
        if t_idx == -1:      # the synthetic '*' column
            continue
        tname = tnames[t_idx]
        schema["tables"][tname]["columns"].append(
            {"name": col_name, "type": str(col_type(col_idx))}
        )

    # primary keys: indices into cnames
    for pk_col_idx in tbl_entry.get("primary_keys", []):
        # a PK entry can be an int or (rarely) a list for composite; normalize
        pk_list = pk_col_idx if isinstance(pk_col_idx, list) else [pk_col_idx]
        for ci in pk_list:
            t_idx, col_name = cnames[ci]
            if t_idx != -1:
                schema["tables"][tnames[t_idx]]["primary_key"].append(col_name)

    # foreign keys: [from_col_idx, to_col_idx] pairs, indices into cnames
    for from_ci, to_ci in tbl_entry.get("foreign_keys", []):
        from_t, from_col = cnames[from_ci]
        to_t, to_col = cnames[to_ci]
        schema["tables"][tnames[from_t]]["foreign_keys"].append({
            "column": from_col,
            "ref_table": tnames[to_t],
            "ref_column": to_col,
        })

    return schema


def load_spider(tables_path: str, dev_path: str):
    """Return (schemas_by_db, dev_list). schemas_by_db[db_id] is a
    get_schema()-shaped dict; also returns table_names_original per db
    for gold extraction."""
    tables = json.load(open(tables_path))
    dev = json.load(open(dev_path))
    schemas = {t["db_id"]: build_schema_dict(t) for t in tables}
    names_by_db = {t["db_id"]: t["table_names_original"] for t in tables}
    return schemas, names_by_db, dev


# ---------- gold table extraction ----------

def _collect_table_indices(sql: dict, acc: set):
    if not isinstance(sql, dict):
        return
    frm = sql.get("from", {})
    for unit in frm.get("table_units", []):
        if unit[0] == "table_unit":
            acc.add(unit[1])
        elif unit[0] == "sql":
            _collect_table_indices(unit[1], acc)
    for key in ("intersect", "union", "except"):
        if sql.get(key):
            _collect_table_indices(sql[key], acc)
    for clause in ("where", "having"):
        for cond in sql.get(clause, []):
            if isinstance(cond, list):
                for elem in cond:
                    if isinstance(elem, dict):
                        _collect_table_indices(elem, acc)


def gold_tables(entry: dict, names_by_db: dict) -> set:
    """Set of lowercased gold table names for one dev entry."""
    names = names_by_db[entry["db_id"]]
    idx = set()
    _collect_table_indices(entry["sql"], idx)
    return {names[i].lower() for i in idx}
