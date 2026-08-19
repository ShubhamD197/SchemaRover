"""
ddl_adapter.py — read a plain .sql schema file into our schema dict.

WHY THIS EXISTS
---------------
To measure retrieval we only need the SHAPE of a database: table names,
column names, and foreign keys. We do NOT need the rows, and we do NOT
need a running database server. A .sql schema file has all the shape in
it, so this reads that file directly.

That means we can evaluate on a big real database (AdventureWorks, 68
tables) without installing Postgres or SQL Server.

Output is the SAME dict shape that spider_adapter.py and
pipeline.get_schema() produce, so every matcher runs on it unchanged:

    {"tables": {"<table>": {
        "columns": [{"name":..., "type":...}, ...],
        "primary_key": [...],
        "foreign_keys": [{"column":..., "ref_table":..., "ref_column":...}],
    }}}

Handles both styles seen in the wild:
  - constraints written INSIDE the CREATE TABLE block (MySQL / sakila)
  - constraints added AFTERWARDS via ALTER TABLE (Postgres / AdventureWorks)

Schema prefixes ("Person.Address") are stripped -- we key on the bare
table name, matching how the rest of the system talks about tables.

Run it directly to convert a file and see a summary:
    python ddl_adapter.py ../../adventureworks_ddl.sql adventureworks.json
"""

import json
import re
import sys

# lines inside a CREATE TABLE block that describe a constraint, not a column
_NOT_A_COLUMN = re.compile(
    r"^\s*(constraint|check|primary\s+key|foreign\s+key|unique|key|index)\b", re.I
)

_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`\[\]]+)\s*\(", re.I)
_FK = re.compile(
    r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+([\w.\"`\[\]]+)\s*\(([^)]+)\)", re.I
)
_PK = re.compile(r"PRIMARY\s+KEY\s*\(([^)]+)\)", re.I)
_ALTER = re.compile(r"ALTER\s+TABLE\s+([\w.\"`\[\]]+)\s+ADD\b", re.I)


def _bare(name: str) -> str:
    """'Person.Address' / '`actor`' / '[dbo].[Person]' -> 'address'."""
    name = name.strip().strip(";").replace('"', "").replace("`", "")
    name = name.replace("[", "").replace("]", "")
    return name.split(".")[-1].strip().lower()


def _cols(text: str) -> list[str]:
    """'(a, b)' body -> ['a','b'], lowercased and unquoted."""
    return [_bare(c) for c in text.split(",") if c.strip()]


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def parse_ddl(sql: str) -> dict:
    """Parse a .sql schema file into the schema dict."""
    sql = _strip_comments(sql)
    schema = {"tables": {}}

    # ---- pass 1: CREATE TABLE blocks (columns, plus any inline constraints)
    for m in _CREATE.finditer(sql):
        table = _bare(m.group(1))
        body = _block_body(sql, m.end() - 1)
        entry = {"columns": [], "primary_key": [], "foreign_keys": []}

        for line in _split_top_level(body):
            line = line.strip()
            if not line:
                continue
            if _NOT_A_COLUMN.match(line):
                _apply_constraint(entry, line)
                continue
            parts = line.split()
            if len(parts) >= 2:
                entry["columns"].append(
                    {"name": _bare(parts[0]), "type": parts[1].rstrip(",")}
                )

        schema["tables"][table] = entry

    # ---- pass 2: ALTER TABLE ... ADD CONSTRAINT (Postgres style)
    for m in _ALTER.finditer(sql):
        table = _bare(m.group(1))
        if table not in schema["tables"]:
            continue
        stmt = sql[m.end(): sql.find(";", m.end())]
        _apply_constraint(schema["tables"][table], stmt)

    return schema


def _apply_constraint(entry: dict, text: str):
    """Record a PRIMARY KEY or FOREIGN KEY found in `text` onto `entry`."""
    fk = _FK.search(text)
    if fk:
        local, ref_table, ref_cols = _cols(fk.group(1)), _bare(fk.group(2)), _cols(fk.group(3))
        for i, col in enumerate(local):
            entry["foreign_keys"].append({
                "column": col,
                "ref_table": ref_table,
                "ref_column": ref_cols[i] if i < len(ref_cols) else ref_cols[0],
            })
        return
    pk = _PK.search(text)
    if pk and not entry["primary_key"]:
        entry["primary_key"] = _cols(pk.group(1))


def _block_body(sql: str, open_paren: int) -> str:
    """Text between the CREATE TABLE '(' and its matching ')'."""
    depth = 0
    for i in range(open_paren, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[open_paren + 1: i]
    return sql[open_paren + 1:]


def _split_top_level(body: str) -> list[str]:
    """Split on commas that are NOT inside parentheses, so 'varchar(60)'
    and 'PRIMARY KEY (a, b)' stay in one piece."""
    out, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def load_ddl(path: str) -> dict:
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_ddl(f.read())


def summarise(schema: dict) -> str:
    t = schema["tables"]
    ncol = sum(len(i["columns"]) for i in t.values())
    nfk = sum(len(i["foreign_keys"]) for i in t.values())
    npk = sum(1 for i in t.values() if i["primary_key"])
    orphans = [n for n, i in t.items() if not i["columns"]]
    s = f"tables={len(t)} columns={ncol} foreign_keys={nfk} tables_with_pk={npk}"
    if orphans:
        s += f"\n  WARNING: {len(orphans)} tables parsed with no columns: {orphans[:5]}"
    return s


def _self_check():
    """Tiny end-to-end check on both DDL styles. Fails loudly if the
    parser breaks. Run: python ddl_adapter.py --check"""
    mysql_style = """
    CREATE TABLE `actor` (
      actor_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
      first_name VARCHAR(45) NOT NULL,
      PRIMARY KEY  (actor_id)
    ) ENGINE=InnoDB;
    CREATE TABLE film_actor (
      actor_id SMALLINT UNSIGNED NOT NULL,
      film_id SMALLINT UNSIGNED NOT NULL,
      PRIMARY KEY (actor_id, film_id),
      CONSTRAINT fk_fa_actor FOREIGN KEY (actor_id) REFERENCES actor (actor_id)
    ) ENGINE=InnoDB;
    """
    s = parse_ddl(mysql_style)
    assert set(s["tables"]) == {"actor", "film_actor"}, s["tables"]
    assert [c["name"] for c in s["tables"]["actor"]["columns"]] == ["actor_id", "first_name"]
    assert s["tables"]["actor"]["primary_key"] == ["actor_id"]
    assert s["tables"]["film_actor"]["primary_key"] == ["actor_id", "film_id"]
    assert s["tables"]["film_actor"]["foreign_keys"] == [
        {"column": "actor_id", "ref_table": "actor", "ref_column": "actor_id"}
    ], s["tables"]["film_actor"]["foreign_keys"]

    postgres_style = """
    CREATE TABLE Address(
      AddressID SERIAL,
      City varchar(30) NOT NULL
    );
    CREATE TABLE StateProvince(
      StateProvinceID SERIAL
    );
    ALTER TABLE Person.Address ADD
      CONSTRAINT "PK_Address" PRIMARY KEY (AddressID);
    ALTER TABLE Person.Address ADD
      CONSTRAINT "FK_Address_StateProvince" FOREIGN KEY
      (StateProvinceID) REFERENCES Person.StateProvince(StateProvinceID);
    """
    s = parse_ddl(postgres_style)
    assert s["tables"]["address"]["primary_key"] == ["addressid"]
    assert s["tables"]["address"]["foreign_keys"] == [
        {"column": "stateprovinceid", "ref_table": "stateprovince",
         "ref_column": "stateprovinceid"}
    ], s["tables"]["address"]["foreign_keys"]
    print("ddl_adapter self-check: OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        _self_check()
        sys.exit(0)

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    schema = load_ddl(sys.argv[1])
    print(summarise(schema))

    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=1)
        print(f"wrote {sys.argv[2]}")
