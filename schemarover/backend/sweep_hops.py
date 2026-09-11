"""
sweep_hops.py — how far to walk the foreign-key graph, and how hard to
cap hubs while doing it.

WHY
---
With threshold 0.30 and a degree cap of 8, AdventureWorks misses nothing,
but Sakila still misses 3 of 20 questions. All three fail the same way:
the tables they need are TWO hops away, not one.

    film -> inventory -> rental -> payment
    customer -> address -> city -> country

One hop cannot reach them at any threshold. So the question is whether a
second hop is affordable — and that is exactly what the degree cap is for:
without a cap a second hop is ruinous, with one it may not be.

RUN
    python sweep_hops.py sakila adventureworks
"""

import sys

from eval_harness import DATASETS, evaluate, m_send_everything
from lexical_match_improved import lexical_match as lexical_improved
from fk_traversal import expand_with_fk_traversal

THRESHOLD = 0.30
CAPS = [2, 3, 4, 5, 8, None]
HOPS = [1, 2]


def run(dataset):
    from Semantic_matcher import SchemaEmbedder

    cases = DATASETS[dataset]()
    embedders, seeds = {}, {}

    def seed_for(question, schema):
        key = id(schema)
        if key not in embedders:
            embedders[key] = SchemaEmbedder(schema)
        ck = (key, question)
        if ck not in seeds:
            seeds[ck] = list(set(lexical_improved(question, schema)) |
                             set(embedders[key].match(question)))
        return seeds[ck]

    def make(hops, cap):
        def matcher(question, schema):
            return expand_with_fk_traversal(
                seed_for(question, schema), schema, hops, cap)
        return matcher

    print(f"\n{'='*80}\nHOPS x DEGREE CAP — {dataset} — {len(cases)} questions "
          f"(threshold {THRESHOLD})\n{'='*80}")

    rows = []
    for hops in HOPS:
        for cap in CAPS:
            label = f"hops={hops}  max_degree={'off' if cap is None else cap}"
            rows.append(evaluate(make(hops, cap), cases, label))
    base = evaluate(m_send_everything, cases, "send everything (baseline)")

    print(f"\n  SUMMARY — {dataset}")
    print(f"  {'variant':<30} {'full_recall':>12} {'tables':>8} "
          f"{'schema sent':>12} {'tokens':>8}")
    for r in rows + [base]:
        print(f"  {r['label']:<30} {r['full_recall']:>11.1%} {r['pred_size']:>8.2f} "
              f"{r['compression']:>11.1%} {r['tokens']:>8.0f}")


if __name__ == "__main__":
    for n in ([a for a in sys.argv[1:] if not a.startswith("--")] or ["sakila"]):
        run(n)
