# SchemaRover — conventions for Claude Code
Training-free NL→SQL over any MySQL/PostgreSQL DB. Three-stage hybrid
schema linking (lexical + semantic + FK traversal) retrieves a relevant
table subset before generation.

## Stack
FastAPI + SQLAlchemy backend, vanilla HTML/JS frontend, Gemini Flash
(temp 0.0, for reproducibility), SQLite history.

## Layout
backend/  connection.py pipeline.py validator.py main.py
          lexical_match_improved.py fk_traversal.py Semantic_matcher.py
          eval_harness.py spider_adapter.py ddl_adapter.py
frontend/ index.html
docs      PLAN.md (what to do next)  DECISIONS.md (why we chose things)
          RESULTS.md (every measured number)

Evaluation data lives one level up, in CodeBase/:
  tables.json dev.json                    Spider
  sakila_schema.json sakilla.json         Sakila, 16 tables
  adventureworks_ddl.sql
  adventureworks_schema.json
  adventureworks_eval.json                AdventureWorks, 68 tables, 80 q

## Hard rules
- READ-ONLY. Only SELECT reaches the database. validator.py is
  deny-by-default; never loosen it to make a query work.
- Never hardcode a database. Connection strings come in at runtime.
- Never commit .env or real credentials.
- Gemini temperature stays 0.0 — the paper's numbers must reproduce.
- Build SchemaEmbedder ONCE per database, never per query.

## Measurement rules (important)
- full_recall (all gold tables retrieved) caps end-to-end accuracy, so it
  is the primary metric.
- **NEVER report full_recall without "schema sent" next to it.** full_recall
  can always be maxed by sending more tables; a system that sends the whole
  database scores 100%. Every harness run prints a "send everything"
  baseline for exactly this reason. See DECISIONS.md D6.
- Exact-set-match is NOT the goal. A surplus table costs tokens; a missing
  table costs the answer.
- Never claim a change helps without running eval_harness.py before and
  after and showing both numbers.
- Judge changes on AdventureWorks (68 tables), not Spider. Spider is the
  small-schema control where every method ties.

## Known measured baselines
Full tables in RESULTS.md. Headlines:

Spider dev (1034 q, 4.5 tables avg) — the CONTROL, not the result
  lexical improved + FK        full_recall  93.8%   schema sent 66%
  lexical + semantic + FK      full_recall 100.0%   schema sent 91.5% <- meaningless
                                                    (send-everything ties)

Sakila (20 q, 16 tables)
  lexical improved             full_recall   0.0%   schema sent 11.9%
  lexical + semantic + FK      full_recall  85.0%   schema sent 70.6%

AdventureWorks (80 q, 68 tables) — WHERE THE CLAIM LIVES
  lexical improved             full_recall  23.8%   schema sent 11.7%
  lexical + FK                 full_recall  63.7%   schema sent 34.2%
  lexical + semantic           full_recall  91.2%   schema sent 29.9%  <- best trade
  lexical + semantic + FK      full_recall 100.0%   schema sent 57.8%
  send everything (baseline)   full_recall 100.0%   schema sent  100%

## Session rules
- Implement exactly the task named. No refactoring, no "while I was here."
- No performance claim without before/after harness output.
- If a change makes metrics worse, say so and revert. Failed experiments
  are recorded in PLAN.md as ablations, not hidden.