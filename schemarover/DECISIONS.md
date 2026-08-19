# SchemaRover — Decision Log

Every important choice we made, and **why**. Read this when you forget why
something is the way it is, or when a reviewer asks "why did you do it
that way?"

Each entry has the same shape:

- **Decision** — what we chose.
- **Why** — the reason.
- **What we gave up** — the cost. Every choice has one. If an entry has no
  cost, we did not think hard enough.
- **Evidence** — the numbers, if we have any.
- **Status** — Firm / Open / Changed.

> **Rule for this file:** nothing gets written here as "Firm" because it
> sounds right. It gets written here because we measured it, or because we
> can say plainly what we traded away.

---

## D1. Retrieve the tables first, then generate the SQL

**Decision.** Do not put the whole database schema in the prompt. Work out
which few tables the question is about, and show the model only those.

**Why.** A big database has too many tables to fit in a prompt. When you
send everything, the prompt gets expensive and the model starts inventing
columns and joining tables that have no relationship. Training a model per
database is not realistic for a normal organisation.

**What we gave up.** If retrieval misses a table, the correct answer becomes
impossible — the model cannot use a table it never saw. We have moved the
risk from "the model gets confused" to "the retriever misses something".
That is a good trade only if retrieval is reliable, which is why we measure
it so heavily.

**Status.** Firm. This is the whole project.

---

## D2. Three retrieval stages, not one

**Decision.** Run three different matchers and take the union:
1. **Lexical** — match words in the question to table/column names.
2. **Semantic** — an embedding model, so "movie" can find the table `film`.
3. **FK traversal** — walk the foreign-key links to pull in connecting tables.

**Why.** They fail in different ways, so together they cover more:
- Lexical is precise but literal. It cannot know "movie" means `film`.
- Semantic handles different wording but is fuzzy and needs a cut-off score.
- Neither can know that joining two tables needs a *third* linking table
  that nobody mentioned out loud. Only the foreign-key graph knows that.

**What we gave up.** Three stages mean three sets of settings to get right,
and the union always retrieves more tables than any single stage alone.

**Evidence — the semantic stage is now proven, on real schemas.** We used to
carry an honest caveat that semantic matching might add less than we hoped.
On Spider that was arguable. On real databases it is not:

| full_recall | Sakila (16 tables) | AdventureWorks (68 tables) |
|---|---|---|
| lexical only | **0.0%** | 23.8% |
| lexical + semantic | 45.0% | **91.2%** |

On Sakila, lexical matching alone gets *zero* questions fully right — the
questions say "movie" and the table is called `film`. That is exactly the
failure this stage exists to fix.

**Stage 3 is the one now in doubt, not stage 2.** See D7.

**Status.** Firm on structure. Stage 2 confirmed. Stage 3's *expansion rule*
is Open.

---

## D3. The database connection is given at runtime

**Decision.** The user pastes a connection string into the app. Nothing is
read from a config file, and no database is baked into the code.

**Why.** The claim of this project is "point it at any database and it
works, with no setup". That claim is only true if the code has never met the
database before. An earlier version read one fixed URL from a `.env` file —
that was a hardcoded connection pretending to be a connection manager.

**What we gave up.** We have to handle connection errors nicely at runtime
instead of assuming a good connection, and we cannot pre-compute anything
about the database ahead of time.

**Status.** Firm. This is a hard rule in CLAUDE.md.

---

## D4. Read-only, enforced twice

**Decision.** Only a single plain `SELECT` ever reaches the database.
`validator.py` refuses everything else by default. On top of that, the
database user should only have SELECT permission.

**Why.** We execute SQL written by a language model against somebody's real
database. That is the single most dangerous thing this system does. One
layer of defence is not enough.

**What we gave up.** The validator is strict enough to reject some perfectly
safe queries — for example any query using the `REPLACE()` string function,
or a column literally named `comment`, because those words are on the
blocked list. We accept those false alarms rather than loosen the rule.

**Honest limit.** The validator is defence in depth, not a proof. The real
guarantee is the SELECT-only database user. Say that before a reviewer says
it for you.

**Status.** Firm. Never loosen it to make a query work.

---

## D5. The model runs at temperature 0

**Decision.** Gemini Flash, temperature 0.0.

**Why.** Same question, same schema, same SQL. Our paper's numbers have to
be reproducible by someone else. A model that gives different answers each
run cannot be measured.

**What we gave up.** Slightly less creative phrasing of SQL, and no easy way
to sample several candidate queries and pick the best one.

**Status.** Firm.

---

## D6. full_recall is the main metric — but never on its own

**Decision.** The headline retrieval metric is **full_recall**: the share of
questions where we retrieved *every* table the correct answer needs. It is
always reported next to **compression** (what share of the database we sent)
and **prompt tokens**.

**Why full_recall.** If one needed table is missing, correct SQL is
impossible no matter how good the model is. So full_recall is the ceiling on
how accurate the whole system can ever be. A surplus table only costs
tokens; a missing table costs the entire answer. That asymmetry is why
precision, F1 and exact-set-match are all the wrong headline — they punish
sending a harmless extra table as heavily as losing the answer.

**Why not on its own — this is the important part.** full_recall can always
be pushed to 100% by simply sending more tables. A system that sends the
*entire database* scores a perfect 100%. So a high full_recall means nothing
unless you also say how much of the schema you sent to get it.

**Evidence — the moment we learned this.** On Spider dev, our best
configuration scored **100% full_recall** while sending **3.98 tables out of
a 4.52-table average database — 91.5% of the schema.** That is not a
result. That is retrieval being switched off by the small size of the
benchmark. We nearly reported it as an achievement.

**What we changed because of it.** The harness now always prints a
"send everything" baseline. Any real method has to beat that baseline on
compression while matching it on full_recall. On a small database, nothing
can — and showing that is now part of the argument, not a weakness we hide.

**Status.** Changed (was full_recall alone), now Firm.

---

## D7. Foreign-key expansion always fires — and this is now under review

**Decision (original).** After lexical and semantic matching, always expand
one hop along the foreign-key graph. Do not try to be clever about when.

**Why (original).** We built a "conditional" version that only expanded when
the question looked like it needed a join. Measured on Spider it bought
12.5 points of precision but cost 5.6 points of full_recall. Losing 5.6% of
questions permanently is worse than carrying 0.4 extra tables, so we
rejected our own fix. This was a good decision *for Spider*.

**Evidence (Spider dev, 1034 questions):**

| | full_recall | precision | avg tables |
|---|---|---|---|
| always expand | **93.8%** | 49.9% | 2.97 |
| conditional | 88.2% | **62.4%** | 2.57 |

**Why it is now under review.** Small databases have no hub tables. Real
ones do. Measured across Spider by database size, the average table has
about 2 neighbours regardless of size — but the *busiest* table grows fast:

| schema size | avg neighbours | busiest table's neighbours |
|---|---|---|
| 2–5 tables | 1.30 | 1.82 |
| 6–10 | 1.78 | 3.47 |
| 11–20 | 2.10 | 5.26 |
| 21+ | 1.46 | 12.00 |

If one matched table happens to be a hub, one hop drags in a dozen tables.

**Evidence that it does break (AdventureWorks, 68 tables, 80 questions):**

| | tables sent | share of schema |
|---|---|---|
| lexical only | 7.92 | 11.7% |
| lexical + FK | **23.24** | **34.2%** |

On Spider, one hop added about 1.3 tables. On AdventureWorks it added
**15.3**. The trade-off that justified always-expand on small schemas
inverts on large ones. `pipeline.py` predicted exactly this in its own
docstring and told us to re-measure before assuming the default still held.

**And the inversion is now measured directly.** On AdventureWorks, with the
semantic stage on:

| | full_recall | schema sent | prompt tokens |
|---|---|---|---|
| lexical + semantic | 91.2% | **29.9%** | **1471** |
| lexical + semantic + FK | **100.0%** | 57.8% | 3153 |

Blind expansion buys the last 8.8 points of recall and **doubles the
prompt**. On Spider the same stage cost almost nothing. This is the single
clearest result we have, and it is the opposite of what we concluded from
Spider alone.

It does **not** mean stage 3 should be deleted — the questions it exists for
(reaching `product` through the `specialofferproduct` bridge) are precisely
the ones still failing without it. It means expansion must become
selective instead of blind.

**What happens next.** Stage 3 keeps its place in the architecture — this is
a change to *how it decides*, not a new component. Options to measure:
refuse to expand into tables above some number of connections, or only
expand along paths that *connect two tables we already matched* rather than
radiating outward from every one.

**RESOLVED (task A1) — expansion is now capped by degree.** We do not expand
outward from a table with more than `max_degree` foreign-key neighbours. The
table itself is still kept if a matcher chose it; we just refuse to inherit
its whole neighbourhood. Capping the *source* is the right knob: at one hop
the cost is decided entirely by how many neighbours the matched tables have.

Swept 1, 2, 3, 4, 5, 6, 8, 12 and off on all three databases. `max_degree=8`:

| dataset | off | max_degree=8 |
|---|---|---|
| Spider dev | 100.0% / 91.5% sent | 100.0% / 91.5% sent (identical) |
| Sakila | 85.0% / 70.6% sent | 85.0% / 70.6% sent (identical) |
| AdventureWorks | 100.0% / 57.8% sent | **100.0% / 48.7% sent** |

Same recall everywhere, 9 points less schema on the large database, no
dataset made worse. On AdventureWorks the whole gain comes from refusing to
expand out of just two tables: `product` (16 neighbours) and
`salesorderheader` (9). Sakila is unaffected because its busiest table has
only 4 neighbours — at 16 tables you are below where hubs bite.

**Honest note on size of effect.** We predicted degree capping would cut the
prompt sharply. It did not — 57.8% to 48.7% is useful but modest. The
threshold sweep (D14) turned out to matter more.

**Status.** Changed → Firm. `max_degree=8` is the default in `pipeline.py`.
Re-sweep before changing it: `python eval_harness.py adventureworks --sweep-degree`.

---

## D8. Embed the table name and each column separately

**Decision.** In the semantic stage, embed the table name as one item and
every column as its own item. A table's score is its single best-scoring
piece.

**Why.** Originally each table was embedded as one blob: name plus all its
columns mashed together. That drowns the one column that matters. For
example `payment` became "payment, payment_id, customer_id, staff_id,
rental_id, amount, payment_date" — so the question "total revenue" was
compared against an average that buried `amount` under five irrelevant ID
and date columns, and the table scored too low to be retrieved.

**What we gave up.** More items to embed, so building the index is slower
and uses more memory. On a 68-table database that is 465 column items
instead of 68 blobs.

**Important:** this is a *resolution* fix, not injected domain knowledge. We
did not add a synonym list.

**CORRECTION — the motivating example does not actually work.** We claimed
this fix makes "revenue" find `payment.amount` on Sakila. Measured, it does
not. For the question "Show the total revenue generated by each movie
category", the scores are:

    0.542  film_category  via film_category
    0.420  film           via film.rental_rate
    0.346  category       via category
    ...
    0.176  payment        via payment.amount     <- needed, far below 0.30

`payment.amount` scores 0.176 against a 0.30 threshold. The table is missed,
and that single miss is why 2 of Sakila's 20 questions fail. Worse, `film`
matched for a *spurious* reason — `film.rental_rate` looks like "revenue"
and "rented" without meaning it.

The fix is still an improvement over blob embedding, and the design reason
for it stands. But the example we have been telling people about is wrong,
and a general-purpose sentence embedder simply does not know that revenue
is stored in a column called `amount`. Stop quoting that example.

**Status.** Firm as a design choice, but its stated benefit is overclaimed.
Fixing the underlying weakness is an open problem, not a settled one.

---

## D9. Build the embedding index once per database, never per question

**Decision.** `SchemaEmbedder` is created when a database is connected and
cached. It is never rebuilt per query.

**Why.** Embedding a whole schema is the slowest thing in the pipeline.
Doing it per question would make the app unusable and would make our timing
numbers meaningless.

**What we gave up.** Memory is held for as long as a database is connected,
and a schema change during a session is not picked up until reconnect.

**Status.** Firm. Hard rule in CLAUDE.md.

---

## D10. Keep the old, buggy lexical matcher in the repo

**Decision.** `lexical_match.py` stays exactly as it was, next to the fixed
`lexical_match_improved.py`.

**Why.** It is the baseline. Without it we cannot show a before/after, and
the story of finding that bug is some of our strongest evidence that we
measured rather than guessed.

**What we gave up.** A confusing extra file that a newcomer might import by
mistake. (This actually happened: the harness imported the old one for a
while, which meant our headline numbers could not be reproduced from the
repo at all.)

**Status.** Firm, but the harness now names both explicitly so the mistake
cannot repeat silently.

---

## D11. Evaluate on schema files, not on running database servers

**Decision.** `ddl_adapter.py` reads a plain `.sql` schema file into the same
dictionary shape that live introspection produces. Retrieval is measured
from that.

**Why.** To measure *retrieval* we only need the shape of the database —
table names, column names, foreign keys. We do not need a single row of
data, and we do not need a database server. This means we can evaluate on a
68-table real-world database without installing Postgres or SQL Server.

**What we gave up.** We cannot measure end-to-end *execution* accuracy this
way, because there are no rows to query. That needs a real loaded database,
and we will do it on Sakila in MySQL, which is already set up.

**Also worth knowing.** We first tried Spider 2.0's ready-made
AdventureWorks SQLite file. It had been flattened to 13 tables with **zero
foreign keys**, which makes it useless to us — our third stage is entirely
foreign-key based. Always check that a downloaded database kept its
constraints.

**Status.** Firm.

---

## D12. AdventureWorks is the large-schema evaluation target

**Decision.** Evaluate on three databases, each with a different job:

| Database | Tables | Job |
|---|---|---|
| Spider dev | 4.5 avg | Comparable to other papers. The **small-schema control**. |
| Sakila | 16 | A real, well-known schema. The demo. |
| AdventureWorks | 68 | A real business schema. **Where the claim lives.** |

**Why.** Spider is the standard benchmark so we keep it, but three quarters
of its questions run on databases with 5 tables or fewer, and only one of
its 166 dev databases has more than 20 tables. It simply cannot show whether
retrieval quality holds as a schema grows — there is nothing large in it.

AdventureWorks is a genuine business database: 68 tables, 465 columns, 91
foreign keys, with real hub tables. Its questions need on average **2.3 of
68 tables — 3.4% of the schema.** On Spider the equivalent figure is about
**38%**. That gap is the entire reason this project exists.

**What we gave up.** We had to write the AdventureWorks questions and their
correct answers ourselves (80 of them), which is slower than using a
ready-made benchmark and opens us to the criticism that we wrote questions
that suit our system. See D13.

**Status.** Firm.

---

## D13. How we decide the "correct" tables for our own questions

**Decision.** For our hand-written sets, the expected tables are the
**smallest set that answers the question, following the database's declared
foreign-key paths.** Questions are written from the schema **before** the
system is run on them, and then frozen.

**Why.** There is often more than one valid way to join. In Sakila, "movies
in Store 1" can be answered without the `store` table at all, because
`inventory` already carries a `store_id`. If we let ourselves pick the
answer after seeing what the system retrieved, our numbers would be
meaningless. Writing the questions first, and following declared foreign
keys, keeps us honest and matches what a retrieval system can actually
discover.

**What we gave up.** Some questions are marked wrong when the system found a
different but equally valid set of tables. We accept that as the cost of a
rule we cannot bend after the fact.

**Status.** Firm. Written into the top of each eval file.

---

## D14. The semantic threshold stays at 0.30 — now with evidence

**Decision.** Keep the similarity cut-off at 0.30.

**Why this needed checking.** 0.30 was picked by hand and never tested. It
is the single biggest control on how much we send: the semantic stage alone
retrieves about 20 of AdventureWorks' 68 tables for questions needing 2.3.

**Evidence.** Swept 0.20 to 0.60 on both real databases, with the FK cap on
(AdventureWorks, 80 questions):

| threshold | full_recall | schema sent | tokens |
|---|---|---|---|
| 0.20 | 100.0% | 69.0% | 3779 |
| 0.25 | 100.0% | 58.6% | 3224 |
| **0.30** | **100.0%** | **48.7%** | **2684** |
| 0.35 | 97.5% | 40.3% | 2220 |
| 0.40 | 95.0% | 33.7% | 1847 |

0.30 is the knee: the cheapest threshold that still reaches 100%. Lower
costs tokens for nothing, higher starts losing answers. Sakila agrees —
0.20, 0.25 and 0.30 all give 85%, so 0.30 is the cheapest of the three.

**The result is that our guess was right.** That is a duller outcome than
finding a better number, but it is now defensible instead of arbitrary.

**Related finding.** Without FK expansion, threshold 0.25 alone reaches
98.8% on AdventureWorks at 39.3% sent — cheaper than any FK configuration
at similar recall. Lowering the threshold partly *substitutes* for FK
traversal, because embeddings relate tables for the same reasons foreign keys
do. Worth a sentence in the paper.

**Status.** Firm.

---

## D15. The "never return zero" fallback is harmless — we were wrong about it

**Decision.** Leave it alone. It was previously flagged as a live bug.

**What we claimed.** That the fallback inside `Semantic_matcher.match()`
injects a table into *every* question, contaminating the seed before FK
expansion.

**What we measured.** It never fires below threshold 0.45. Results with the
fallback on and off are byte-identical from 0.20 through 0.45 on both real
databases — at any sane threshold, something always clears the bar. It only
changes anything at 0.50+, which we would never use.

**Why record a non-result.** Because we nearly spent a session "fixing" it.
The rule that saved us was checking before changing.

**Status.** Firm (no change). Revisit only if the threshold ever goes above
0.45.

---

# Still open — decisions we have NOT made yet

These are real gaps. Say them out loud before a reviewer finds them.

**O1. The semantic cut-off score of 0.30 was never calibrated.**
It was picked by hand and never tested against data. It should be chosen by
sweeping values from 0.25 to 0.50 and reading the curve — and calibrated on
Sakila or AdventureWorks, not Spider, because on a 4-table database the
choice barely matters.

**O2. The "never return zero" fallback is in the wrong place.**
Inside `Semantic_matcher.match()`, if nothing clears the threshold, it
returns the single best-scoring table anyway. Because it sits *inside* the
semantic stage, it injects a table into **every single question**, before
the union and before FK expansion. So foreign-key traversal then expands
outward from a table that may be completely irrelevant. It should move up to
the pipeline, or be removed.

**O3. We do not prune columns, only tables.**
We send whole tables. On AdventureWorks, `salesorderheader` alone has 26
columns and `product` has 25. Once schemas are large, most of the prompt is
columns, not tables — so a table-only retriever has a ceiling on how
efficient it can get. This is the one open item that might need a change to
the architecture diagram, so we will not touch it until the scaling results
tell us whether it is worth it.

**O4. End-to-end accuracy is still unmeasured.**
Everything above measures *retrieval*. We have never measured how often the
final SQL actually returns the right answer. Until we do, we quote
full_recall as a ceiling and never as accuracy.

**O5. One connection, shared by everyone.**
`main.py` keeps a single global connection and schema. Two people using the
app at once would share a database. Fine for a demo, not fine for a
deployment. Worth one sentence in the paper's limitations.
