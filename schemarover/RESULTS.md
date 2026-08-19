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
