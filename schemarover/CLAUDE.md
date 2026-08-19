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
          eval_harness.py spider_adapter.py
frontend/ index.html

## Hard rules
- READ-ONLY. Only SELECT reaches the database. validator.py is
  deny-by-default; never loosen it to make a query work.
- Never hardcode a database. Connection strings come in at runtime.
- Never commit .env or real credentials.
- Gemini temperature stays 0.0 — the paper's numbers must reproduce.
- Build SchemaEmbedder ONCE per database, never per query.

## Measurement rules (important)
- The metric that matters is full_recall (all gold tables retrieved).
  It caps end-to-end accuracy. Precision is secondary.
- Exact-set-match is NOT the goal. Surplus tables are cheap; a missing
  table is fatal.
- Never claim a change helps without running eval_harness.py before and
  after and showing both numbers.

## Known measured baselines (Spider dev, 1034 q)
lexical original          full_recall 57.2%  prec 66.1%
lexical original + FK     full_recall 76.4%  prec 42.5%
lexical improved          full_recall 73.8%  prec 77.1%
lexical improved + FK     full_recall 93.8%  prec 49.9%   <- current default
lexical improved + condFK full_recall 88.2%  prec 62.4%
