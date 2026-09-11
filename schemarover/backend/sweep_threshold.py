"""
sweep_threshold.py — task A4: calibrate the semantic cut-off score.

WHY
---
The semantic stage keeps any table whose best-scoring piece clears a
similarity threshold. That threshold was set to 0.30 by hand and never
tested against data.

It matters a lot. On AdventureWorks the semantic stage retrieves about
20 tables out of 68 for questions that need 2.3 — so it, not foreign-key
expansion, is the biggest source of prompt bloat.

This sweeps the threshold and prints the curve, so the value gets chosen
from evidence instead of taste.

It also sweeps the "never return zero" fallback on and off (task A3),
because the two interact: raise the threshold and more questions match
nothing, which makes the fallback fire more often. You cannot read one
curve without the other.

Embeddings are built ONCE per database and every threshold reuses them,
and each question's scores are cached, so the whole sweep costs about the
same as a single run.

RUN
    python sweep_threshold.py adventureworks
    python sweep_threshold.py adventureworks sakila
"""

import sys

from eval_harness import DATASETS, evaluate, m_send_everything
from lexical_match_improved import lexical_match as lexical_improved
from fk_traversal import expand_with_fk_traversal

THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


def make_scorer():
    """One embedder per schema, one score-list per question. Everything
    downstream is just filtering, so thresholds are nearly free."""
    from Semantic_matcher import SchemaEmbedder

    embedders, scores = {}, {}

    def ranked(question, schema):
        key = id(schema)
        if key not in embedders:
            embedders[key] = SchemaEmbedder(schema)
        ck = (key, question)
        if ck not in scores:
            scores[ck] = embedders[key].match_with_scores(question)
        return scores[ck]

    return ranked


def build_variant(ranked, threshold, fallback, max_degree, use_fk):
    def matcher(question, schema):
        hits = [t for t, s in ranked(question, schema) if s >= threshold]
        if not hits and fallback:
            top = ranked(question, schema)
            if top:
                hits = [top[0][0]]
        seed = set(lexical_improved(question, schema)) | set(hits)
        if not use_fk:
            return list(seed)
        return expand_with_fk_traversal(list(seed), schema, 1, max_degree)

    return matcher


def run(dataset, use_fk=False, max_degree=8):
    cases = DATASETS[dataset]()
    ranked = make_scorer()

    print(f"\n{'='*80}\nA4 THRESHOLD SWEEP — {dataset} — {len(cases)} questions"
          f"{'  (+FK cap %s)' % max_degree if use_fk else '  (no FK)'}\n{'='*80}")

    rows = []
    for fallback in (True, False):
        for th in THRESHOLDS:
            label = f"threshold={th:.2f}  fallback={'on ' if fallback else 'off'}"
            m = build_variant(ranked, th, fallback, max_degree, use_fk)
            rows.append(evaluate(m, cases, label))

    base = evaluate(m_send_everything, cases, "send everything (baseline)")

    print(f"\n  SUMMARY — {dataset}")
    print(f"  {'variant':<36} {'full_recall':>12} {'tables':>8} "
          f"{'schema sent':>12} {'tokens':>8}")
    for r in rows + [base]:
        print(f"  {r['label']:<36} {r['full_recall']:>11.1%} {r['pred_size']:>8.2f} "
              f"{r['compression']:>11.1%} {r['tokens']:>8.0f}")
    return rows


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["adventureworks"]
    with_fk = "--fk" in sys.argv
    for n in names:
        run(n, use_fk=with_fk)
