# SchemaRover

Ask any MySQL/PostgreSQL database questions in plain English. Training-free,
zero configuration.

## Run (5 minutes)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000

Paste a connection string, ask a question. The UI shows which tables were
retrieved, the generated SQL, and the results.

## Reproduce the schema-linking numbers

```bash
cd backend
python3 eval_harness.py /path/to/spider/tables.json /path/to/spider/dev.json
```

## What's implemented

- Connection Manager — runtime DB URL, validated, friendly errors
- Introspection — SQLAlchemy, any MySQL/PostgreSQL/SQLite
- Stage 1 lexical matching (symmetric stemming)
- Stage 2 semantic matching (sentence embeddings)
- Stage 3 FK graph traversal
- Prompt builder — retrieved subset only, FK paths stated explicitly
- Gemini Flash, temperature 0.0
- SQL validator — deny-by-default read-only, 11/11 tests passing
- Executor with row limits
- SQLite history logging
- Frontend showing the schema reduction, SQL, and results

See PLAN.md for the roadmap and CLAUDE.md for conventions.
