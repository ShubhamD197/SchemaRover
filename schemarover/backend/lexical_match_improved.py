"""
lexical_match_improved.py

Drop-in replacement for lexical_match.py that fixes the measured bug:
the original stemmed ONLY the table side, so query token "singers"
never matched table "singer". Here stemming is applied SYMMETRICALLY to
both the query tokens and the schema tokens.

Measured on Spider dev (1034 queries) vs the original:
    zero-recall queries:   242  -> 81
    lexical-only full_recall: 57.2% -> 73.8%
    lexical+FK  full_recall:  76.4% -> 93.0%

IMPORTANT: _stem() below is a deliberately small, dependency-free plural
normalizer. It is BETTER than rstrip("s") because it is symmetric and
guarded, but it is still not a real stemmer -- it will not handle
irregulars (people/person, children/child) and can still clip odd words.
If nltk is available, prefer a real stemmer applied to both sides:

    from nltk.stem import SnowballStemmer
    _S = SnowballStemmer("english")
    def _stem(tok): return _S.stem(tok)

Swap that in and re-run the harness to confirm it helps on YOUR data
before committing -- don't assume, measure.
"""

import re

# irregulars we don't want the naive rule to touch or that need explicit mapping
_IRREGULAR = {
    "people": "person", "children": "child", "men": "man", "women": "woman",
    "teeth": "tooth", "feet": "foot", "data": "data", "media": "media",
}


def _stem(tok: str) -> str:
    if tok in _IRREGULAR:
        return _IRREGULAR[tok]
    # "-ies" -> "-y" (companies -> company), guarded by length
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    # "-ses"/"-xes"/"-zes"/"-ches"/"-shes" -> drop "es" (addresses->address, boxes->box)
    if re.search(r"(s|x|z|ch|sh)es$", tok) and len(tok) > 4:
        return tok[:-2]
    # plain trailing "s", but not "ss" (address stays address) and keep short words
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
        return tok[:-1]
    return tok


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _stemmed_tokens(text: str) -> set:
    return {_stem(t) for t in tokenize(text)}


def lexical_match(nl_query: str, schema: dict) -> list[str]:
    """Same contract as your original: (question, schema) -> [table names].
    Only difference is symmetric stemming."""
    query_tokens = _stemmed_tokens(nl_query)
    matched_tables = set()

    for table_name, table_info in schema["tables"].items():
        table_tokens = _stemmed_tokens(table_name)

        if query_tokens & table_tokens:
            matched_tables.add(table_name)
            continue

        for col in table_info["columns"]:
            if query_tokens & _stemmed_tokens(col["name"]):
                matched_tables.add(table_name)
                break

    return list(matched_tables)
