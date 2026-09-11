# SchemaRover — Measured Results

All numbers produced by `eval_harness.py`. Re-run any row with:

```bash
cd CodeBase/schemarover/backend
python eval_harness.py <spider|sakila|adventureworks|all> [--semantic]
```

**Read every row with two columns, not one.** `full_recall` says whether we
kept the tables the answer needs. `schema sent` says how much of the
database we had to send to manage it. A method is only good if it wins on
both. See DECISIONS.md D6.

---

## The three databases

| | Spider dev | Sakila | AdventureWorks |
|---|---|---|---|
| tables | 2–26 (avg 4.5) | 16 | 68 |
| questions | 1034 | 20 | 80 |
| tables the answer needs (avg) | 1.7 | 4.5 | 2.3 |
| **that as a share of the schema** | **38%** | **28%** | **3.4%** |

That last row is the whole story. On Spider, the average question needs
more than a third of the entire database, so there is almost nothing to
filter out. On AdventureWorks it needs 3.4%, so filtering is the entire
job.

---

## Results

### Spider dev — 1034 questions, 4.5 tables average

| variant | full_recall | precision | tables | schema sent | tokens |
|---|---|---|---|---|---|
| send everything (baseline) | 100.0% | 39.8% | 4.52 | 100.0% | 223 |
| lexical (original, buggy) | 57.2% | 66.1% | 1.25 | 31.7% | 57 |
| lexical (improved) | 76.0% | 78.1% | 1.66 | 43.0% | 75 |
| lexical + FK | 93.8% | 49.9% | 2.97 | 74.1% | 146 |
| lexical + semantic | 99.0% | 53.9% | 3.17 | 76.0% | 157 |
| lexical + semantic + FK | **100.0%** | 43.4% | 3.98 | **91.5%** | 201 |

**Do not quote the 100% without the 91.5%.** Retrieving 3.98 tables from a
4.52-table database is not retrieval — we send more than nine tenths of the
database and the "send everything" baseline ties us on the metric we were
optimising. This is the measurement that redirected the project.

Worse: on the 575 questions whose answer needs exactly **one** table, we
still send **89.9% of the schema**. There is no configuration of this
system that looks efficient on Spider, because there is nothing to remove.

Note how little room there is here: even the *buggy original* matcher sends
31.7% of the schema, and the best method sends 91.5%. The whole usable range
on Spider is narrow, because the databases are tiny.

### Sakila — 20 questions, 16 tables

| variant | full_recall | precision | tables | schema sent | tokens |
|---|---|---|---|---|---|
| send everything (baseline) | 100.0% | 27.8% | 16.00 | 100.0% | 989 |
| lexical (original, buggy) | 0.0% | 55.8% | 1.05 | 6.6% | 46 |
| lexical (improved) | 0.0% | 76.3% | 1.90 | 11.9% | 81 |
| lexical + FK | 25.0% | 52.6% | 5.20 | 32.5% | 318 |
| lexical + semantic | 45.0% | 59.9% | 5.95 | 37.2% | 323 |
| lexical + semantic + FK | **85.0%** | 38.2% | 11.30 | 70.6% | 694 |

**Our weakest result, and the most useful one.** Lexical matching alone
gets *zero* questions fully right, because Sakila's questions say "movie"
and the table is called `film`, and because every gold answer needs 3–7
tables. This is the case the three-stage design was built for, and it is
the clearest proof that the semantic stage earns its place: 0% → 45%
before FK is even involved.

But 85% at 70% of the schema is not good enough. Both numbers need work.

*Caveat: 20 questions means each one is worth 5 percentage points. Treat
these as counts (17/20), not percentages, until Phase C3 expands the set.*

### AdventureWorks — 80 questions, 68 tables

| variant | full_recall | precision | tables | schema sent | tokens |
|---|---|---|---|---|---|
| send everything (baseline) | 100.0% | 3.4% | 68.00 | 100.0% | 5305 |
| lexical (original, buggy) | 12.5% | 32.7% | 6.58 | 9.7% | 379 |
| lexical (improved) | 23.8% | 44.6% | 7.92 | 11.7% | 457 |
| lexical + FK | 63.7% | 13.2% | 23.24 | 34.2% | 1794 |
| **lexical + semantic** | **91.2%** | 15.9% | 20.36 | **29.9%** | **1471** |
| lexical + semantic + FK | 100.0% | 6.9% | 39.27 | 57.8% | 3153 |

---

## What these results actually say

**1. The efficiency claim is real but currently weak.** The share of schema
we send does fall as the database grows — 91.5% → 70.6% → 57.8% on the full
configuration. The trend is in the right direction. But sending 58% of a
68-table database is not a system anyone would call efficient. The claim is
directionally supported and quantitatively unconvincing.

**2. Blind foreign-key expansion is the problem at scale.** One hop adds:

| database | tables before FK | after FK | added |
|---|---|---|---|
| Spider (4.5 tables) | 1.66 | 2.97 | +1.3 |
| Sakila (16 tables) | 1.90 | 5.20 | +3.3 |
| AdventureWorks (68 tables) | 7.92 | 23.24 | **+15.3** |

This is the hub problem. Small databases have no hub tables; real ones
always do. The decision to always expand was measured on Spider and was
correct **for Spider** — and it inverts on real schemas. See DECISIONS.md D7.

**3. On the largest database, dropping FK entirely is currently the best
configuration.** On AdventureWorks, lexical + semantic gives 91.2%
full_recall at 29.9% of the schema. Adding FK buys the last 8.8 points of
recall and costs *twice the prompt* (29.9% → 57.8%, 1471 → 3153 tokens).

That is a genuine, defensible finding, and it inverts our previous
conclusion. It does **not** mean "delete stage 3" — the questions FK
expansion exists for (id 57, 75, 79: reaching `product` through
`specialofferproduct`) are exactly the ones still failing. It means the
expansion needs to be selective instead of blind. That is Phase A.

> **Superseded by A1 below.** Selective expansion now exists: with
> `max_degree=8` we get 100% full_recall at 48.7% of the schema, so FK
> expansion is worth keeping after all. The tables above are the
> pre-A1 state, kept because they are what motivated the fix.

**4. The semantic stage is carrying the system on real schemas.** On
Spider its contribution was arguable. On Sakila it takes full_recall from
0% to 45%. On AdventureWorks from 23.8% to 91.2%. The honest caveat we had
been carrying — "we may find semantic adds less than expected" — is now
resolved in its favour, on the databases that matter.

**5. Best current numbers against the baseline.** On AdventureWorks,
lexical + semantic sends **1471 tokens instead of 5305 — a 3.6× reduction —
while retrieving all needed tables for 91.2% of questions.** That is the
first honest version of the headline claim this project has had.

---

## What is still wrong

- **91.2% is below our 90%+ target only just, and 85% on Sakila is well
  below.** Both need Phase A.
- **Sakila needs 70% of the schema to reach 85%.** Worst compression of any
  configuration on any database.
- **1-table questions are the worst case for over-expansion.** On
  AdventureWorks, questions needing a single table still pull 30.95 tables
  with the full configuration — 45% of the database to answer "how many
  products do we sell?"
- **No end-to-end accuracy yet.** Everything here measures retrieval only.
  full_recall is a ceiling, never an accuracy figure.

---

# Tuning results (tasks A1 and A4)

Reproduce with:

```bash
python eval_harness.py adventureworks --sweep-degree   # A1
python sweep_threshold.py adventureworks sakila --fk   # A4
python sweep_hops.py sakila adventureworks             # hops x cap
```

## A1 — capping foreign-key expansion by hub degree

Do not expand outward from a table with more than `max_degree` neighbours.

| dataset | max_degree=off | max_degree=8 |
|---|---|---|
| Spider dev | 100.0% / 91.5% sent / 201 tok | 100.0% / 91.5% sent / 201 tok |
| Sakila | 85.0% / 70.6% sent / 694 tok | 85.0% / 70.6% sent / 694 tok |
| AdventureWorks | 100.0% / 57.8% sent / 3153 tok | **100.0% / 48.7% sent / 2684 tok** |

Identical recall on all three, 9 points less schema and 15% fewer tokens on
the large database, nothing made worse. **`max_degree=8` is now the default
in `pipeline.py`.**

The entire AdventureWorks gain comes from refusing to expand out of two
tables: `product` (16 neighbours) and `salesorderheader` (9). Sakila's
busiest table has only 4 neighbours, so no cap ≥4 changes anything there —
16 tables is below the size where hubs start to hurt.

Full AdventureWorks curve, for the trade-off:

| cap | full_recall | schema sent | tokens |
|---|---|---|---|
| no FK | 91.2% | 29.9% | 1471 |
| 1 | 93.8% | 33.5% | 1696 |
| 2 | 96.2% | 38.0% | 2011 |
| 6 | 97.5% | 46.5% | 2572 |
| **8** | **100.0%** | **48.7%** | **2684** |
| off | 100.0% | 57.8% | 3153 |

## A4 — calibrating the semantic threshold

Swept 0.20–0.60 on both real databases. **0.30 survives** — it is the knee,
the cheapest threshold still reaching 100% on AdventureWorks. Our original
hand-picked value was right; it is now defensible rather than arbitrary.

One finding worth the paper: **without FK expansion at all, threshold 0.25
reaches 98.8% at 39.3% of the schema (2003 tokens)** — cheaper than any FK
configuration at comparable recall. Lowering the threshold partly
*substitutes* for foreign-key traversal.

We also checked the "never return zero" fallback, which we had flagged as a
bug. It never fires below threshold 0.45 — results are identical with it on
and off across 0.20–0.45. It is not a problem. We nearly fixed a non-issue.

## Where the remaining failures are

At threshold 0.30 with `max_degree=8`:

- **AdventureWorks: 0 of 80 missed.**
- **Sakila: 3 of 20 missed.** All three need tables **three hops** from the
  seed, and raising `max_hops` to 2 does not reach them either:

| question | missing | why |
|---|---|---|
| total revenue by movie category | `payment` | `film → inventory → rental → payment` |
| total revenue by each actor's movies | `payment` | same chain |
| movies rented by customers in Canada | `country` | `customer → address → city → country` |

Two different root causes, and neither is a tuning problem:

1. **`payment` is a semantic miss, not a graph problem.** For "total
   revenue", `payment.amount` scores **0.176** — far below any usable
   threshold. Meanwhile `film` matches at 0.42 for a spurious reason
   (`film.rental_rate` looks like "revenue"). A general-purpose sentence
   embedder does not know revenue lives in a column called `amount`. This
   also disproves the example we had been using to justify column-level
   embedding — see DECISIONS.md D8.

2. **"Canada" is a value, not a schema word.** No schema-linking method can
   match a data value against the `country` table. This is *value linking*,
   a genuinely different problem (it is what the BIRD benchmark focuses on),
   and it is out of scope for this system. Say so rather than counting it as
   a tuning failure.

## Current best configuration

Threshold 0.30, `max_degree=8`, one hop:

| dataset | full_recall | schema sent | tokens vs send-everything |
|---|---|---|---|
| Spider dev | 100.0% | 91.5% | 201 vs 223 (1.1×) |
| Sakila | 85.0% | 70.6% | 694 vs 989 (1.4×) |
| AdventureWorks | 100.0% | 48.7% | 2684 vs 5305 (**2.0×**) |

The efficiency gain scales with schema size, which is the thesis. But 48.7%
on 68 tables is still not a strong claim, and the honest reading is that
this system is not yet efficient enough on large schemas. The next real
lever is column-level pruning, not more retrieval tuning — on AdventureWorks
`salesorderheader` alone has 26 columns.
