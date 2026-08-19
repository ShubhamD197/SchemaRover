# SchemaRover — Plan

> Training-free NL→SQL over any MySQL/PostgreSQL database. Three-stage
> schema linking (lexical + semantic + FK traversal) retrieves only the
> relevant tables before generation.

Companion files: **DECISIONS.md** (why we chose things) and **CLAUDE.md**
(rules for coding sessions). Read DECISIONS.md before changing anything
that has a "Firm" status.

---

## 1. The problem

Language models write good SQL when they can see a small schema. Real
databases are not small. Sending the whole schema makes the prompt
expensive and makes the model invent columns and joins that do not exist.
Training a model per database is not realistic.

## 2. The idea

Retrieve, then generate. Work out which few tables the question is about,
and show the model only those.

## 3. The claim we are actually making

**Not** "we beat state-of-the-art accuracy" — fine-tuned models win that
fight. Our claim:

> A training-free, zero-configuration system that keeps retrieval quality
> high **while sending a small and shrinking fraction of the schema** as
> the database grows, where full-schema injection degrades.

The evidence is a curve: retrieval quality and prompt size plotted against
number of tables. **That curve is the paper.**

## 4. What we found that changed the plan

Our best configuration scored **100% full_recall on Spider dev** — while
sending **3.98 of 4.52 tables — 91.5% of the schema.** That is not a
result. On a 4-table database, "retrieving" 4 tables is not retrieval.

Three quarters of Spider's questions run on databases with 5 tables or
fewer, and only 1 of its 166 dev databases has more than 20. **Spider
cannot show our claim, because there is nothing large in it.**

So we added real large schemas — and the picture changed completely:

| | Spider (4.5 tables) | Sakila (16) | AdventureWorks (68) |
|---|---|---|---|
| full config, full_recall | 100% | 85.0% | 100% |
| full config, **schema sent** | **91.5%** | **70.6%** | **57.8%** |
| tables added by one FK hop | +1.3 | +3.3 | **+15.3** |

Best current configuration on the large database is **lexical + semantic
with no FK expansion**: 91.2% full_recall while sending 29.9% of the schema
(1471 tokens instead of 5305 — a 3.6× reduction). Adding blind FK expansion
buys the last 8.8 points of recall and **doubles the prompt**.

Full numbers in **RESULTS.md**.

One foreign-key hop adds about one table on Spider and **fifteen** on
AdventureWorks, because real databases have hub tables and toy ones do not.
This is not a small regression — it is the trade-off from D7 inverting, and
it is the most interesting thing we have found. See DECISIONS.md D6 and D7.

**Reframing:** Spider is now our *control* — the regime where filtering is
unnecessary and every method ties. The contribution is what happens outside
it.

## 5. Success metrics

| Metric | Target | Why |
|---|---|---|
| full_recall | ≥ 90% **on AdventureWorks** | ceiling on end-to-end accuracy |
| schema sent | < 20% on 68-table DB | this is the efficiency claim |
| prompt tokens | beat full-schema baseline by 3×+ | what efficiency costs in money |
| execution accuracy | beat full-schema baseline on large schemas | the headline |
| zero-config connect | any MySQL/PG URL | the practical claim |

**Rule: full_recall is never reported without schema-sent next to it.**
A "send everything" baseline is printed in every run for exactly this
reason. See DECISIONS.md D6.

## 6. Non-goals

- Beating fine-tuned models on raw Spider accuracy.
- Write operations. **Read-only, always.**
- Multi-turn conversation.
- NoSQL.

---

# What we evaluate on

| Dataset | Tables | Questions | Role | Status |
|---|---|---|---|---|
| Spider dev | 2–26 (avg 4.5) | 1034 | small-schema control, comparable to other papers | ready |
| Sakila | 16 | 20 | real schema, the demo | ready, needs more questions |
| AdventureWorks | 68 | 80 | **where the claim lives** | ready |
| Distractor-augmented Spider | 4 → 100+ | 1034 × k | the scaling curve | to build |

Schemas are read from `.sql` files by `ddl_adapter.py` — no database server
needed to measure retrieval. See DECISIONS.md D11.

---

# Task list

One task per coding session. Do not run ahead — the order exists because
later steps are meaningless without earlier ones.

## DONE

- [x] **T1.1** Fix lexical matcher (symmetric stemming).
- [x] **T1.2** `connection.py` — runtime connection manager, no hardcoded DB.
- [x] **T1.3** `pipeline.py` — introspect → link → prompt → LLM → validate → execute.
- [x] **T1.4** `main.py` — FastAPI: connect / schema / query / history.
- [x] **T1.5** Frontend — single page showing retrieved tables and SQL.
- [x] **T1.6** `validator.py` — read-only enforcement.
- [x] **T2.4** Cache `SchemaEmbedder` once per database.
- [x] **T3.0** Rewire the harness to measure the **shipped** path, with all
      variants named. *(It was importing the old buggy matcher, so none of
      our published numbers could be reproduced from the repo.)*
- [x] **T3.1** Add compression ratio + prompt tokens + "send everything"
      baseline to the harness.
- [x] **T3.2** `ddl_adapter.py` — read any `.sql` schema into our dict shape.
- [x] **T3.3** AdventureWorks (68 tables) loaded, 80 questions written.
- [x] **T3.4** Measure all variants on Spider / Sakila / AdventureWorks.

## PHASE A — fix what the big-schema numbers exposed

- [ ] **A1** Make FK expansion **degree-aware**. Do not expand into hub
      tables above some connection count. Sweep the cut-off; plot
      full_recall vs schema-sent on AdventureWorks. *This replaces the old
      "conditional FK" task, which was measured on Spider and rejected —
      see DECISIONS.md D7. The rejection was correct for Spider and is
      wrong for AdventureWorks.*
- [ ] **A2** Try **connective expansion**: only pull in a table if it sits
      on a path *between two already-matched tables*, instead of radiating
      outward from every match. Compare against A1.
- [ ] **A3** Move the "never return zero" fallback out of
      `Semantic_matcher.match()`. It currently injects a table into every
      single question before FK expansion runs. See DECISIONS.md O2.
- [ ] **A4** Calibrate the semantic threshold (currently 0.30, chosen by
      hand). Sweep 0.25–0.50 **on AdventureWorks and Sakila**, not Spider.
      Pick from the curve. See DECISIONS.md O1.

**Gate for Phase A:** full_recall ≥ 90% on AdventureWorks while sending
under 20% of the schema. If no configuration reaches it, that is the
finding — report it.

## PHASE B — the scaling curve (the paper's main figure)

- [ ] **B1** Build distractor augmentation: take each Spider question's own
      schema and merge in *k* other Spider schemas as noise, k ∈ {0,1,2,4,8,16}.
      Gold tables never change, so this costs **zero new labelling**.
- [ ] **B2** Run every variant across the sweep. **Plot full_recall and
      schema-sent against table count.** This is Figure 1.
- [ ] **B3** Confirm the AdventureWorks finding on the curve: at what table
      count does blind FK expansion stop paying for itself?

## PHASE C — end to end

- [ ] **C1** Load Sakila into MySQL (data, not just schema) and measure
      **execution accuracy**: does the SQL return the right answer?
- [ ] **C2** Full-schema-injection baseline, same model, same prompt
      template, temperature 0.
- [ ] **C3** Extend Sakila to 50+ questions. Write them **before** running
      the system on them, then freeze. 20 questions means each one is worth
      5 percentage points — too coarse to conclude anything.
- [ ] **C4** Error taxonomy: bucket every failure by cause.

## PHASE D — paper and polish

- [ ] **D1** Column-level pruning, **only if** Phase B says table-level
      retrieval has hit its ceiling. This is the one item that may need a
      change to the architecture diagram, so it needs evidence first.
      See DECISIONS.md O3.
- [ ] **D2** Rotate the database password in `.env` and confirm it is
      ignored by git.
- [ ] **D3** Write the paper. Motivation = section 4 above. Related work
      from the 14-paper doc; cite G-SQL (FK constraints → executable SQL),
      View-SQL + HSRNet (multi-table joins are the bottleneck),
      Sketch Filling + Shakespeare-SQL (RAG).
- [ ] **D4** Rename any remaining QueryBridge references to SchemaRover.

---

# How to run things

```bash
cd CodeBase/schemarover/backend

python ddl_adapter.py --check                  # parser self-test
python eval_harness.py spider                  # small-schema control
python eval_harness.py sakila                  # 16 tables
python eval_harness.py adventureworks          # 68 tables — the real test
python eval_harness.py all --semantic          # everything, slower
```

# Working rules

1. **One task per session.** Broad requests produce sprawling, wrong code.
2. **Numbers or it did not happen.** No claim that a change helped without
   harness output from before and after.
3. **Never report full_recall alone.** Always with schema-sent beside it.
4. **A result that contradicts the thesis goes in the paper as a finding,**
   not tuned away. Our two best pieces of evidence so far are both cases
   where we measured our own idea and it was wrong.
5. **Record the reasoning in DECISIONS.md,** not just the code change.
6. Commit after each task, so a bad change is easy to undo.
