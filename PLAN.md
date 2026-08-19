# SchemaRover — PRD & Task List

> Training-free NL→SQL over ANY MySQL/PostgreSQL database, using
> three-stage hybrid schema linking (lexical + semantic + FK traversal)
> to retrieve only relevant tables before generation.

## 1. Problem

LLMs write good SQL when they see a small schema. Real databases have
100+ tables. Dumping the whole schema causes hallucinated joins/columns,
huge prompts, and high cost. Fine-tuning per database is impractical.

## 2. Solution

Retrieve-then-generate. Introspect the DB automatically, retrieve the
relevant table subset per question, generate SQL from that subset only.
No training, no per-DB configuration.

## 3. Core claim for the paper

**Not** "we beat state-of-the-art accuracy." That fight is lost to
fine-tuned models. The defensible claim is:

> A training-free, zero-config system whose hybrid schema linking keeps
> retrieval quality high as schema size grows, where full-schema
> injection degrades.

Evidence = schema-linking metrics on Spider + end-to-end execution
accuracy vs a full-schema-injection baseline, **plotted against table
count**. The scaling curve IS the paper.

## 4. Success metrics

| Metric | Target | Why |
|---|---|---|
| full_recall (all gold tables retrieved) | ≥ 93% | ceiling on end-to-end accuracy |
| avg tables in prompt | < 4 | prompt cost / hallucination risk |
| execution accuracy vs baseline | beat it on large schemas | the paper's headline |
| zero-config connect | any MySQL/PG URL | the practical claim |

## 5. Non-goals

- Beating RESDSQL/fine-tuned SOTA on raw Spider accuracy.
- Write operations. **Read-only, always.**
- Multi-turn conversation (future work).
- NoSQL.

---

# Task list (phased, Claude Code friendly)

Each task = one Claude Code session. Keep sessions narrow.

## PHASE 1 — Demo path (DO THIS FIRST)
Goal: something reviewable end-to-end.

- [x] **T1.1** Fix lexical matcher (symmetric stemming). *Done — measured
      full_recall 57%→74% standalone, 76%→93% with FK.*
- [ ] **T1.2** `connection.py` — Connection Manager. Accept a DB URL at
      runtime, validate, return engine, friendly errors. No hardcoded
      `.env` DB.
- [ ] **T1.3** `pipeline.py` — wire introspect → lexical ∪ semantic → FK
      → prompt → LLM → validate → execute. One function, one call.
- [ ] **T1.4** `main.py` — FastAPI: `POST /connect`, `GET /schema`,
      `POST /query`, `GET /history`.
- [ ] **T1.5** Frontend — single page: connection form, question box,
      **matched tables**, **generated SQL**, results table, history.
      Showing the retrieved tables is the demo's whole point.
- [ ] **T1.6** `validator.py` — read-only enforcement.

## PHASE 2 — Correctness
- [ ] **T2.1** Make FK expansion **conditional** (biggest precision leak:
      181 dev queries hurt by blind 1-hop expansion on single-table gold).
- [ ] **T2.2** Calibrate semantic threshold by sweeping 0.25–0.50 on
      Spider; pick from the curve, not by guess. Current 0.30 is arbitrary.
- [ ] **T2.3** Gate/remove the "never return zero" fallback — it injects a
      confidently wrong table on unrelated questions.
- [ ] **T2.4** Cache `SchemaEmbedder` per database (never re-embed per query).
- [ ] **T2.5** Column-level pruning — send relevant columns, not whole tables.

## PHASE 3 — Evaluation (the paper)
- [ ] **T3.1** Run harness with semantic plugged in. Honest question:
      does semantic raise full_recall above lexical+FK alone? Be ready
      for "no."
- [ ] **T3.2** Baseline: full-schema injection, same LLM, same prompt.
- [ ] **T3.3** Execution accuracy on Spider dev (needs the DB zip locally).
- [ ] **T3.4** **Scaling plot**: accuracy & prompt tokens vs #tables.
      This is the figure the paper lives or dies on.
- [ ] **T3.5** Ablation: lexical only / +semantic / +FK / full.

## PHASE 4 — Paper & polish
- [ ] **T4.1** Rename everything QueryBridge → SchemaRover (the 14-paper
      doc still says QueryBridge).
- [ ] **T4.2** Rotate the leaked DB password; ensure `.env` is gitignored.
- [ ] **T4.3** Write paper: Related Work from the 14-paper doc; cite G-SQL
      (FK constraints → executable SQL), View-SQL + HSRNet (multi-table
      joins are THE bottleneck), Sketch Filling + Shakespeare-SQL (RAG).
- [ ] **T4.4** Error taxonomy of failure cases.

---

# How to use Claude Code effectively

1. **Put this file in the repo root.** Claude Code reads it for context.
   Start sessions with: "Read PLAN.md. Implement T1.2 only."
2. **One task per session.** Broad asks produce sprawling, wrong code.
3. **Make it prove things.** "Run the harness and show me the numbers
   before and after" — don't accept "this should improve it."
4. **Add a `CLAUDE.md`** with project conventions so you don't re-explain
   the stack every session.
5. **Commit after each task.** Easy rollback when a change makes metrics
   worse — and some will.
6. **Never let it tune against numbers it didn't run.** Measured > plausible.
