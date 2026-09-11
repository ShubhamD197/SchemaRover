"""
pipeline.py — the three-stage schema linking + generation pipeline (T1.3)

Flow:
  question + schema
    -> stage 1: lexical match      (symmetric stemming — FIXED)
    -> stage 2: semantic match     (embeddings, optional)
    -> union of the two = seed set
    -> stage 3: FK traversal       (CONDITIONAL — see below)
    -> prompt builder (only the retrieved subset)
    -> LLM (Gemini Flash, temp 0.0)
    -> validator (read-only)
    -> executor
  returns: answer rows + generated SQL + which tables were retrieved

FK EXPANSION: MEASURED TRADE-OFF (default = always expand)
----------------------------------------------------------
Measured on Spider dev (1034 queries), lexical-improved seed:

    blind FK (always expand)   full_recall=93.8%  prec=49.9%  avg=2.97
    conditional FK (heuristic) full_recall=88.2%  prec=62.4%  avg=2.57

Conditional expansion buys ~12.5 pts of precision but COSTS ~5.6 pts of
full_recall. That is a bad trade here: full_recall is the hard ceiling on
end-to-end accuracy (a missing table makes correct SQL impossible),
whereas low precision only costs prompt tokens and some hallucination
risk. Losing 5.6% of queries permanently is worse than carrying ~0.4
extra tables.

So the DEFAULT is always-expand. `conditional_fk=True` is kept as a flag
because the comparison is a good ablation row in the paper.

UPDATE — the prediction above came true (task A1)
-------------------------------------------------
We re-measured on a real 68-table schema and the warning was justified.
One hop adds +1.3 tables on Spider and +15.3 on AdventureWorks, because
real databases have hub tables and toy ones do not (AdventureWorks has 16
tables pointing at `product`).

So expansion is now capped by degree: we do not expand OUTWARD from a
table with more than `max_degree` foreign-key neighbours. Measured:

    dataset          max_degree=off        max_degree=8
    Spider dev       100.0% / 91.5% sent   100.0% / 91.5% sent  (identical)
    Sakila            85.0% / 70.6% sent    85.0% / 70.6% sent  (identical)
    AdventureWorks   100.0% / 57.8% sent   100.0% / 48.7% sent  (better)

Identical recall everywhere, 9 points less schema on the large database,
no dataset made worse — so 8 is the default. Sweep it before changing:

    python eval_harness.py adventureworks --sweep-degree
"""

import re
import time
from typing import Optional

from sqlalchemy import inspect

from lexical_match_improved import lexical_match
from fk_traversal import expand_with_fk_traversal

# words suggesting the question spans more than one entity
_RELATIONAL_HINTS = re.compile(
    r"\b(each|per|their|its|for every|along with|and their|"
    r"who|which|whose|that (?:has|have|are|is)|belong|associated|"
    r"related|linked|between|both|as well as|together)\b",
    re.I,
)


# ---------------- schema introspection ----------------

def get_schema(engine) -> dict:
    """Introspect a live DB into the canonical schema dict."""
    inspector = inspect(engine)
    schema = {"tables": {}}

    for table_name in inspector.get_table_names():
        columns = [
            {"name": c["name"], "type": str(c["type"])}
            for c in inspector.get_columns(table_name)
        ]
        pk = inspector.get_pk_constraint(table_name).get("constrained_columns", []) or []

        fks = []
        for fk in inspector.get_foreign_keys(table_name):
            if not fk.get("constrained_columns") or not fk.get("referred_columns"):
                continue
            fks.append({
                "column": fk["constrained_columns"][0],
                "ref_table": fk["referred_table"],
                "ref_column": fk["referred_columns"][0],
            })

        schema["tables"][table_name] = {
            "columns": columns, "primary_key": pk, "foreign_keys": fks,
        }
    return schema


# ---------------- stage 3: conditional FK ----------------

def should_expand(question: str, seed: list, conditional: bool = False) -> bool:
    if len(seed) == 0:
        return False                      # nothing to expand from
    if not conditional:
        return True                       # DEFAULT: recall > precision (see docstring)
    if len(seed) >= 2:
        return True                       # join almost certainly needed
    return bool(_RELATIONAL_HINTS.search(question))


def link_schema(question: str, schema: dict, embedder=None, max_hops: int = 1,
                conditional_fk: bool = False, max_degree: int | None = 8) -> dict:
    """Run the three stages. Returns retrieved tables + per-stage detail
    (the detail is what makes the demo legible and the paper's ablation easy)."""
    lexical = set(lexical_match(question, schema))

    semantic = set()
    if embedder is not None:
        try:
            semantic = set(embedder.match(question))
        except Exception:
            semantic = set()   # never let the optional stage break the request

    seed = lexical | semantic
    expanded = should_expand(question, list(seed), conditional_fk)
    final = (set(expand_with_fk_traversal(list(seed), schema, max_hops, max_degree))
             if expanded else set(seed))

    # last-resort: never hand the LLM an empty schema
    if not final and schema["tables"]:
        final = set(list(schema["tables"].keys())[:3])

    return {
        "lexical": sorted(lexical),
        "semantic": sorted(semantic),
        "fk_expanded": expanded,
        "added_by_fk": sorted(final - seed),
        "tables": sorted(final),
    }


# ---------------- prompt builder ----------------

def build_schema_text(schema: dict, tables: list) -> str:
    lines = []
    for t in tables:
        info = schema["tables"].get(t)
        if not info:
            continue
        cols = ", ".join(
            f"{c['name']} ({c['type']})" for c in info["columns"]
        )
        lines.append(f"TABLE {t}({cols})")
        if info["primary_key"]:
            lines.append(f"  PRIMARY KEY: {', '.join(info['primary_key'])}")
        for fk in info["foreign_keys"]:
            if fk["ref_table"] in tables:
                lines.append(
                    f"  FOREIGN KEY: {t}.{fk['column']} -> "
                    f"{fk['ref_table']}.{fk['ref_column']}"
                )
    return "\n".join(lines)


PROMPT_TEMPLATE = """You are an expert SQL analyst. Write ONE {dialect} SELECT query answering the question.

Use ONLY the tables and columns below. Join strictly along the stated FOREIGN KEY paths — never invent a relationship.

SCHEMA:
{schema_text}

RULES:
- Output ONLY the SQL. No explanation, no markdown fences.
- SELECT only. Never write or modify data.
- If the question cannot be answered from this schema, output exactly: CANNOT_ANSWER

QUESTION: {question}

SQL:"""


def build_prompt(question: str, schema: dict, tables: list, dialect: str = "MySQL") -> str:
    return PROMPT_TEMPLATE.format(
        dialect=dialect,
        schema_text=build_schema_text(schema, tables),
        question=question,
    )


# ---------------- LLM ----------------

_CLIENT = None


def _client(api_key: str):
    """One client per process — the old code rebuilt it (and re-did the TLS
    handshake) on every single query."""
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=api_key)
    return _CLIENT


def generate_sql(prompt: str, api_key: str, model: str = "gemini-3.6-flash") -> str:
    """Gemini Flash at temperature 0 for deterministic, reproducible output
    (required so the paper's numbers are reproducible).

    THINKING BUDGET — measured, this is the whole latency story.
    Translating a question into SQL against a schema we already handed the
    model is not a reasoning task, but Flash spends "thinking" tokens on it
    anyway. Measured on the AdventureWorks employee/department question:

        default thinking   1590 thought tokens for 93 tokens of SQL   10.03s
        thinking_level low  493 thought tokens for 78 tokens of SQL    6.32s

    94% of generated tokens were invisible reasoning. Gemini 3.x refuses
    thinking_budget=0 (400 INVALID_ARGUMENT); "low" is as far down as it
    goes, so that is the floor here.

    This also moves off google-generativeai (dead, no thinking_config at
    all) onto google-genai, which is why the knob is reachable now.
    """
    from google.genai import types

    resp = _client(api_key).models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            # 1024 is ample now that thinking is capped; the old 4096 existed
            # only because thinking was eating the budget before the SQL.
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    return (resp.text or "").strip()


# ---------------- orchestration ----------------

def answer_question(
    question: str,
    engine,
    schema: dict,
    api_key: str,
    embedder=None,
    dialect: str = "MySQL",
    max_rows: int = 200,
) -> dict:
    """Full path. Always returns the generated SQL alongside the answer,
    so the user can see and verify what ran."""
    from validator import validate, enforce_limit, ValidationError
    from sqlalchemy import text

    t0 = time.time()
    link = link_schema(question, schema, embedder)
    prompt = build_prompt(question, schema, link["tables"], dialect)

    result = {
        "question": question,
        "linked": link,
        "sql": None,
        "columns": [],
        "rows": [],
        "error": None,
        "prompt_chars": len(prompt),
        "total_tables_in_db": len(schema["tables"]),
    }

    try:
        raw_sql = generate_sql(prompt, api_key)
    except Exception as e:
        result["error"] = f"LLM error: {e}"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    if "CANNOT_ANSWER" in raw_sql.upper():
        result["error"] = "The question can't be answered from the retrieved tables."
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    try:
        sql = validate(raw_sql)
        result["sql"] = sql
    except ValidationError as e:
        result["sql"] = raw_sql
        result["error"] = f"Rejected for safety: {e}"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    try:
        with engine.connect() as conn:
            cur = conn.execute(text(enforce_limit(sql, max_rows)))
            result["columns"] = list(cur.keys())
            result["rows"] = [list(r) for r in cur.fetchall()]
    except Exception as e:
        result["error"] = f"Execution failed: {str(e)[:300]}"

    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    return result
