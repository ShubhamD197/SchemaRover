"""
role_breakdown.py — recall split by what KIND of table was missed.

WHY THIS EXISTS
---------------
One overall recall number hides the interesting part. "95% recall" does not
say WHICH 5% we lost, and the tables we lose are not a random sample.

The claim this script tests:

    Name-based matching (lexical + semantic) systematically misses CONNECTOR
    tables — junctions and weak entities — because nobody names them in a
    question and their names carry no meaning. Structure-based expansion is
    the only stage that recovers them.

If that is true, seed-only recall on connectors should be far below seed-only
recall on ordinary entities, and expansion should close most of the gap.

    python role_breakdown.py sakila adventureworks
"""

import sys
from collections import defaultdict

from eval_harness import DATASETS
from lexical_match_improved import lexical_match as lexical_improved
from fk_traversal import expand_with_fk_traversal, expand_with_path_completion
from table_roles import classify_tables

ROLES = ("entity", "subtype", "junction", "weak_entity")


def build_matchers():
    from Semantic_matcher import SchemaEmbedder
    cache = {}

    def seed(question, schema):
        key = id(schema)
        if key not in cache:
            cache[key] = SchemaEmbedder(schema)
        return list(set(lexical_improved(question, schema)) | set(cache[key].match(question)))

    return [
        ("seed only (lexical+semantic)", seed),
        ("+ blind FK expansion", lambda q, s: expand_with_fk_traversal(seed(q, s), s, max_hops=1)),
        ("+ path completion", lambda q, s: expand_with_path_completion(seed(q, s), s)),
    ]


def run(dataset):
    cases = DATASETS[dataset]()
    matchers = build_matchers()

    # how often does each role appear in the GOLD answers at all?
    gold_counts = defaultdict(int)
    for _q, schema, gold, _db in cases:
        roles = classify_tables(schema)
        for table in gold:
            gold_counts[roles.get(table, "entity")] += 1

    print(f"\n{'='*76}\n{dataset.upper()} — recall by table role  ({len(cases)} questions)\n{'='*76}")
    print("\ngold tables by role:")
    total_gold = sum(gold_counts.values()) or 1
    for role in ROLES:
        c = gold_counts[role]
        if c:
            print(f"  {role:12} {c:5}  ({c/total_gold:5.1%} of all required tables)")

    rows = []
    for label, matcher in matchers:
        hit = defaultdict(int)
        for question, schema, gold, _db in cases:
            roles = classify_tables(schema)
            pred = {t.lower() for t in matcher(question, schema)}
            for table in gold:
                if table in pred:
                    hit[roles.get(table, "entity")] += 1
        rows.append((label, hit))

    header = "  " + f"{'variant':<30}" + "".join(
        f"{r:>14}" for r in ROLES if gold_counts[r])
    print("\n" + header)
    for label, hit in rows:
        line = f"  {label:<30}"
        for role in ROLES:
            if not gold_counts[role]:
                continue
            line += f"{hit[role]/gold_counts[role]:>13.1%} "
        print(line)

    print("\n  (each cell = of the required tables of that role, how many we kept)")
    return rows


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["sakila", "adventureworks"]
    for name in names:
        run(name)
