"""
eval_harness.py

Measures schema-linking quality against Spider dev gold tables.

Metrics (per query, then aggregated):
  - recall    = |pred ∩ gold| / |gold|   -> did we keep every table the query NEEDS?
  - precision = |pred ∩ gold| / |pred|   -> how much junk did we drag in?
  - f1
  - exact_set = pred set == gold set     -> strict
  - full_recall (a.k.a. hit) = recall == 1.0
        ^ THIS is the one that matters most: if a needed table is missing,
          the correct SQL is literally unreachable no matter how good the LLM is.
          full_recall rate is the CEILING on downstream execution accuracy.

Precision matters too, but differently: every extra table inflates the
prompt and gives the LLM more chances to hallucinate a wrong join. So we
want full_recall as close to 100% as possible, and precision as high as
we can push it WITHOUT sacrificing recall.

A matcher is any function (question:str, schema:dict) -> list[str] of
table names. This lets us swap lexical / lexical+FK / hybrid+FK / etc.
"""

from collections import defaultdict
from spider_adapter import load_spider, gold_tables
from lexical_match_improved import lexical_match
from fk_traversal import expand_with_fk_traversal


def evaluate(matcher, schemas, names_by_db, dev, label=""):
    per_bucket = defaultdict(lambda: {
        "n": 0, "recall": 0.0, "precision": 0.0, "f1": 0.0,
        "exact": 0, "full_recall": 0, "pred_size": 0,
    })
    overall = {
        "n": 0, "recall": 0.0, "precision": 0.0, "f1": 0.0,
        "exact": 0, "full_recall": 0, "pred_size": 0,
    }

    for entry in dev:
        db = entry["db_id"]
        schema = schemas[db]
        gold = gold_tables(entry, names_by_db)
        if not gold:
            continue  # skip degenerate (shouldn't happen on dev)

        pred = {t.lower() for t in matcher(entry["question"], schema)}

        inter = pred & gold
        recall = len(inter) / len(gold)
        precision = len(inter) / len(pred) if pred else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        exact = int(pred == gold)
        full_recall = int(recall == 1.0)

        bucket = "1 table" if len(gold) == 1 else "2 tables" if len(gold) == 2 else "3+ tables"
        for tgt in (per_bucket[bucket], overall):
            tgt["n"] += 1
            tgt["recall"] += recall
            tgt["precision"] += precision
            tgt["f1"] += f1
            tgt["exact"] += exact
            tgt["full_recall"] += full_recall
            tgt["pred_size"] += len(pred)

    def fmt(d):
        n = d["n"] or 1
        return (f"recall={d['recall']/n:6.1%}  prec={d['precision']/n:6.1%}  "
                f"f1={d['f1']/n:6.1%}  full_recall={d['full_recall']/n:6.1%}  "
                f"exact={d['exact']/n:6.1%}  avg_pred={d['pred_size']/n:4.2f}  (n={d['n']})")

    print(f"\n===== {label} =====")
    print(f"OVERALL   {fmt(overall)}")
    for bucket in ("1 table", "2 tables", "3+ tables"):
        if per_bucket[bucket]["n"]:
            print(f"  {bucket:9} {fmt(per_bucket[bucket])}")
    return overall


# ---------- matcher variants ----------

def m_lexical_only(question, schema):
    return lexical_match(question, schema)


def m_lexical_fk(question, schema):
    seed = lexical_match(question, schema)
    return expand_with_fk_traversal(seed, schema, max_hops=1)


# ---------- semantic stage (T3.1) ----------
#
# One SchemaEmbedder per DATABASE, built once and cached. Rebuilding it
# per query would re-encode every table+column of the schema on every
# question -- that is the thing CLAUDE.md forbids, and it would make the
# 1034-query sweep take hours instead of minutes.

# Keyed by id(schema): schemas_by_db holds one stable dict object per
# database for the whole run, so this is a per-database cache while
# keeping the matcher contract at (question, schema).

_EMBEDDER_CACHE = {}


def get_embedder(schema):
    key = id(schema)
    if key not in _EMBEDDER_CACHE:
        from Semantic_matcher import SchemaEmbedder
        _EMBEDDER_CACHE[key] = SchemaEmbedder(schema)
    return _EMBEDDER_CACHE[key]


def m_lexical_semantic(question, schema):
    lex = set(lexical_match(question, schema))
    sem = set(get_embedder(schema).match(question))
    return list(lex | sem)


def m_lexical_semantic_fk(question, schema):
    seed = m_lexical_semantic(question, schema)
    return expand_with_fk_traversal(seed, schema, max_hops=1)


if __name__ == "__main__":
    import sys
    tables_path = sys.argv[1] if len(sys.argv) > 1 else "tables.json"
    dev_path = sys.argv[2] if len(sys.argv) > 2 else "dev.json"

    schemas, names_by_db, dev = load_spider(tables_path, dev_path)
    print(f"Loaded {len(schemas)} databases, {len(dev)} dev questions.")

    # Pre-build (and cache) one embedder per database that dev actually
    # touches, before any measurement runs.
    dev_dbs = sorted({e["db_id"] for e in dev})
    print(f"Building {len(dev_dbs)} SchemaEmbedders (one per dev database)...")
    for db in dev_dbs:
        get_embedder(schemas[db])
    print("Embedders ready.")

    results = {}
    results["lexical only"] = evaluate(
        m_lexical_only, schemas, names_by_db, dev, label="LEXICAL ONLY")
    results["lexical + FK"] = evaluate(
        m_lexical_fk, schemas, names_by_db, dev, label="LEXICAL + FK (1 hop)")
    results["lexical + semantic"] = evaluate(
        m_lexical_semantic, schemas, names_by_db, dev, label="LEXICAL + SEMANTIC")
    results["lexical + semantic + FK"] = evaluate(
        m_lexical_semantic_fk, schemas, names_by_db, dev,
        label="LEXICAL + SEMANTIC + FK (1 hop)")

    print("\n\n===== T3.1 SUMMARY (Spider dev) =====")
    print(f"{'variant':<26} {'full_recall':>11} {'precision':>10} {'avg tables':>11}")
    for label, d in results.items():
        n = d["n"] or 1
        print(f"{label:<26} {d['full_recall']/n:>10.1%} "
              f"{d['precision']/n:>10.1%} {d['pred_size']/n:>11.2f}")
