"""
eval_harness.py — measures how good our table retrieval is.

WHAT IT MEASURES
----------------
For each question we know which tables the correct answer really needs
("gold"). We compare that against the tables our system picked ("pred").

  recall      did we keep every table the question NEEDS?
  precision   how much junk did we drag in?
  full_recall recall == 1.0, i.e. we got ALL the needed tables
  exact       pred set == gold set exactly (strict, mostly ignore it)

  compression how much of the schema did we send?  (pred / all tables)
              LOWER IS BETTER. 100% means we sent the whole database and
              did no filtering at all.
  tokens      rough size of the schema text we put in the prompt.
              This is what "efficient" actually costs. LOWER IS BETTER.

WHY BOTH full_recall AND compression
------------------------------------
full_recall alone can always be maxed out by sending MORE tables — a
system that sends the entire database scores 100%. That is why the
"send everything" baseline is always printed: any real method has to
beat it on compression while matching it on full_recall. On a small
database nothing can, and that is the point.

HOW TO RUN
----------
    python eval_harness.py spider
    python eval_harness.py sakila
    python eval_harness.py adventureworks
    python eval_harness.py all
    python eval_harness.py adventureworks --semantic     (slower, needs
                                                          sentence-transformers)
"""

import json
import os
import sys
from collections import defaultdict

from spider_adapter import load_spider, gold_tables
from utils.lexical_match import lexical_match as lexical_original
from lexical_match_improved import lexical_match as lexical_improved
from fk_traversal import expand_with_fk_traversal, expand_with_path_completion
from pipeline import build_schema_text

# repo data folder (CodeBase/), two levels up from backend/
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


def _path(name):
    return os.path.join(DATA, name)


# ---------------- loading evaluation sets ----------------
# A "case" is one question: (question, schema, gold_table_set, db_id)


def load_spider_cases(tables_path=None, dev_path=None):
    schemas, names_by_db, dev = load_spider(
        tables_path or _path("tables.json"), dev_path or _path("dev.json")
    )
    cases = []
    for entry in dev:
        gold = gold_tables(entry, names_by_db)
        if gold:
            cases.append((entry["question"], schemas[entry["db_id"]], gold, entry["db_id"]))
    return cases


def load_json_cases(schema_file, eval_file):
    """For our own hand-written sets (sakila, adventureworks): a schema
    JSON produced by ddl_adapter.py plus an eval JSON of questions."""
    schema = json.load(open(_path(schema_file), encoding="utf-8"))
    spec = json.load(open(_path(eval_file), encoding="utf-8"))
    db = spec.get("database", eval_file)
    return [
        (q["nlp"], schema, {t.lower() for t in q["expected_tables"]}, db)
        for q in spec["queries"]
    ]


DATASETS = {
    "spider": load_spider_cases,
    "sakila": lambda: load_json_cases("sakila_schema.json", "sakilla.json"),
    "adventureworks": lambda: load_json_cases(
        "adventureworks_schema.json", "adventureworks_eval.json"
    ),
}

# Same questions, same structure, names stripped to legacy-style codes.
# See obfuscate.py — this is how we tell "found it by reading the name" apart
# from "found it by following the keys".
def _obfuscated(name, level):
    from obfuscate import obfuscate_cases
    return lambda: obfuscate_cases(DATASETS[name](), level=level)


for _base in ("spider", "sakila", "adventureworks"):
    DATASETS[_base + "_abbrev"] = _obfuscated(_base, "abbrev")
    DATASETS[_base + "_opaque"] = _obfuscated(_base, "opaque")


# ---------------- the measurement ----------------

_FIELDS = ("recall", "precision", "f1", "exact", "full_recall",
           "pred_size", "compression", "tokens")


def _blank():
    d = {f: 0.0 for f in _FIELDS}
    d["n"] = 0
    return d


def evaluate(matcher, cases, label=""):
    per_bucket = defaultdict(_blank)
    overall = _blank()

    for question, schema, gold, _db in cases:
        total_tables = len(schema["tables"]) or 1
        pred = {t.lower() for t in matcher(question, schema)}

        inter = pred & gold
        recall = len(inter) / len(gold)
        precision = len(inter) / len(pred) if pred else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

        # what the prompt actually costs: the schema text we would send.
        # ~4 characters per token is the usual rough estimate.
        real_names = [t for t in schema["tables"] if t.lower() in pred]
        tokens = len(build_schema_text(schema, real_names)) / 4

        row = {
            "recall": recall, "precision": precision, "f1": f1,
            "exact": float(pred == gold), "full_recall": float(recall == 1.0),
            "pred_size": len(pred), "compression": len(pred) / total_tables,
            "tokens": tokens,
        }

        bucket = f"{min(len(gold), 3)} table" + ("s" if len(gold) != 1 else "")
        if len(gold) >= 3:
            bucket = "3+ tables"
        for tgt in (per_bucket[bucket], overall):
            tgt["n"] += 1
            for f in _FIELDS:
                tgt[f] += row[f]

    def fmt(d):
        n = d["n"] or 1
        return (f"full_recall={d['full_recall']/n:6.1%}  recall={d['recall']/n:6.1%}  "
                f"prec={d['precision']/n:6.1%}  tables={d['pred_size']/n:5.2f}  "
                f"schema_sent={d['compression']/n:6.1%}  tokens={d['tokens']/n:6.0f}  "
                f"(n={d['n']})")

    print(f"\n----- {label} -----")
    print(f"  OVERALL   {fmt(overall)}")
    for bucket in ("1 table", "2 tables", "3+ tables"):
        if per_bucket[bucket]["n"]:
            print(f"  {bucket:9} {fmt(per_bucket[bucket])}")

    n = overall["n"] or 1
    return {f: overall[f] / n for f in _FIELDS} | {"n": overall["n"], "label": label}


# ---------------- the variants we compare ----------------

def m_send_everything(question, schema):
    """The baseline that does no retrieval at all. Any real method must
    beat this on schema_sent while matching it on full_recall."""
    return list(schema["tables"])


def m_lexical_original(question, schema):
    return lexical_original(question, schema)


def m_lexical(question, schema):
    return lexical_improved(question, schema)


def m_lexical_fk(question, schema):
    return expand_with_fk_traversal(lexical_improved(question, schema), schema, max_hops=1)


def m_lexical_path(question, schema):
    return expand_with_path_completion(lexical_improved(question, schema), schema)


def make_semantic_variants():
    """Built lazily: importing sentence-transformers is slow and it may
    not be installed. Embedders are cached per schema (never per query)."""
    from Semantic_matcher import SchemaEmbedder

    cache = {}

    def embedder_for(schema):
        key = id(schema)
        if key not in cache:
            cache[key] = SchemaEmbedder(schema)
        return cache[key]

    def m_lex_sem(question, schema):
        return list(set(lexical_improved(question, schema)) |
                    set(embedder_for(schema).match(question)))

    def m_lex_sem_fk(question, schema):
        return expand_with_fk_traversal(m_lex_sem(question, schema), schema, max_hops=1)

    def m_lex_sem_path(question, schema):
        return expand_with_path_completion(m_lex_sem(question, schema), schema)

    def m_lex_sem_path_nosub(question, schema):
        return expand_with_path_completion(m_lex_sem(question, schema), schema,
                                           include_identity_parents=False)

    def m_lex_sem_path3(question, schema):
        return expand_with_path_completion(m_lex_sem(question, schema), schema,
                                           max_path_len=3)

    return [("lexical + semantic", m_lex_sem),
            ("lexical + semantic + FK", m_lex_sem_fk),
            ("lexical + semantic + PATH", m_lex_sem_path),
            ("  PATH, no identity parents", m_lex_sem_path_nosub),
            ("  PATH, max_path_len=3", m_lex_sem_path3)]


BASE_VARIANTS = [
    ("send everything (baseline)", m_send_everything),
    ("lexical (original, buggy)", m_lexical_original),
    ("lexical (improved)", m_lexical),
    ("lexical + FK", m_lexical_fk),
    ("lexical + PATH", m_lexical_path),
]

# ---------------- A1: degree-aware FK expansion ----------------

DEGREE_CAPS = [1, 2, 3, 4, 5, 6, 8, 12, None]


def make_degree_sweep(use_semantic=True):
    """One variant per max_degree value, so we can read the trade-off off
    a curve instead of guessing a cap. See fk_traversal.max_degree."""
    if use_semantic:
        from Semantic_matcher import SchemaEmbedder
        cache = {}

        def seed(question, schema):
            key = id(schema)
            if key not in cache:
                cache[key] = SchemaEmbedder(schema)
            return list(set(lexical_improved(question, schema)) |
                        set(cache[key].match(question)))
    else:
        def seed(question, schema):
            return lexical_improved(question, schema)

    def make(cap):
        def matcher(question, schema):
            return expand_with_fk_traversal(
                seed(question, schema), schema, max_hops=1, max_degree=cap
            )
        return matcher

    stem = "lexical + semantic" if use_semantic else "lexical"
    variants = [(f"{stem} (no FK)", seed)]
    variants += [
        (f"{stem} + FK, max_degree={'off' if c is None else c}", make(c))
        for c in DEGREE_CAPS
    ]
    return variants


# ---------------- entry point ----------------

def run(dataset_name, use_semantic=False, sweep_degree=False):
    cases = DATASETS[dataset_name]()
    sizes = {len(s["tables"]) for _q, s, _g, _d in cases}
    print(f"\n{'='*78}\n{dataset_name.upper()}  —  {len(cases)} questions, "
          f"{min(sizes)}–{max(sizes)} tables per database\n{'='*78}")

    if sweep_degree:
        variants = [("send everything (baseline)", m_send_everything)]
        variants += make_degree_sweep(use_semantic)
    else:
        variants = list(BASE_VARIANTS)
        if use_semantic:
            variants += make_semantic_variants()

    results = [evaluate(m, cases, label) for label, m in variants]

    print(f"\n  SUMMARY — {dataset_name}")
    print(f"  {'variant':<30} {'full_recall':>12} {'precision':>10} "
          f"{'tables':>8} {'schema sent':>12} {'tokens':>8}")
    for r in results:
        print(f"  {r['label']:<30} {r['full_recall']:>11.1%} {r['precision']:>10.1%} "
              f"{r['pred_size']:>8.2f} {r['compression']:>11.1%} {r['tokens']:>8.0f}")
    return results


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sweep = "--sweep-degree" in sys.argv
    # the sweep is about the FK rule, so it uses the strongest seed available
    semantic = "--semantic" in sys.argv or (sweep and "--no-semantic" not in sys.argv)

    names = list(DATASETS) if (not args or args[0] == "all") else args
    for name in names:
        if name not in DATASETS:
            print(f"unknown dataset '{name}'. choose from: {', '.join(DATASETS)}, all")
            sys.exit(1)
        run(name, semantic, sweep)
