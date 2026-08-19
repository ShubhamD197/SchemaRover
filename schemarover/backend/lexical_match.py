"""
Your lexical_match.py, copied verbatim from what you shared, so the
harness measures YOUR code, not a rewrite of it.
"""

import re


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    return tokens


def lexical_match(nl_query: str, schema: dict) -> list[str]:
    query_tokens = set(tokenize(nl_query))
    matched_tables = set()

    for table_name, table_info in schema["tables"].items():
        table_tokens = set(tokenize(table_name))
        table_tokens_stripped = {t.rstrip("s") for t in table_tokens}

        if query_tokens & table_tokens or query_tokens & table_tokens_stripped:
            matched_tables.add(table_name)
            continue

        for col in table_info["columns"]:
            col_tokens = set(tokenize(col["name"]))
            if query_tokens & col_tokens:
                matched_tables.add(table_name)
                break

    return list(matched_tables)
