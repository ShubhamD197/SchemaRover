"""
main.py — FastAPI backend (T1.4)

Endpoints:
  POST /api/connect   {db_url}          -> connect, introspect, return schema summary
  GET  /api/schema                      -> full schema of the active DB
  POST /api/query     {question}        -> linked tables + SQL + results
  GET  /api/history                     -> past queries
  GET  /api/health

Run:
    uvicorn main:app --reload --port 8000
"""

import os
import json
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from connection import manager, ConnectionError_
from pipeline import get_schema, answer_question

load_dotenv()

app = FastAPI(title="SchemaRover API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

HISTORY_DB = Path(__file__).parent / "history.db"

# in-memory session state
STATE = {"schema": None, "embedder": None}


# ---------------- history ----------------

def init_history():
    con = sqlite3.connect(HISTORY_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            database TEXT, question TEXT, sql TEXT,
            linked_tables TEXT, total_tables INTEGER,
            elapsed_ms INTEGER, row_count INTEGER, error TEXT
        )
    """)
    con.commit()
    con.close()


def log_history(db, res):
    con = sqlite3.connect(HISTORY_DB)
    con.execute(
        "INSERT INTO history (database,question,sql,linked_tables,total_tables,elapsed_ms,row_count,error)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (db, res["question"], res.get("sql"),
         json.dumps(res["linked"]["tables"]), res.get("total_tables_in_db", 0),
         res.get("elapsed_ms", 0), len(res.get("rows", [])), res.get("error")),
    )
    con.commit()
    con.close()


init_history()


# ---------------- models ----------------

class ConnectRequest(BaseModel):
    db_url: str


class QueryRequest(BaseModel):
    question: str
    use_semantic: bool = True


# ---------------- endpoints ----------------

@app.get("/api/health")
def health():
    return {"ok": True, "connected": manager.is_connected()}


@app.post("/api/connect")
def connect(req: ConnectRequest):
    try:
        active = manager.connect(req.db_url)
    except ConnectionError_ as e:
        raise HTTPException(status_code=400, detail=str(e))

    schema = get_schema(active.engine)
    STATE["schema"] = schema
    STATE["embedder"] = None  # rebuilt lazily on first semantic query

    return {
        "connected": True,
        "database": active.database,
        "dialect": active.dialect,
        "safe_url": active.safe_url(),
        "table_count": len(schema["tables"]),
        "tables": [
            {"name": t, "columns": len(i["columns"]), "foreign_keys": len(i["foreign_keys"])}
            for t, i in schema["tables"].items()
        ],
    }


@app.get("/api/schema")
def schema_endpoint():
    if STATE["schema"] is None:
        raise HTTPException(status_code=400, detail="Not connected to a database.")
    return STATE["schema"]


def _get_embedder():
    """Build the SchemaEmbedder once per connected DB (never per query)."""
    if STATE["embedder"] is not None:
        return STATE["embedder"]
    try:
        from Semantic_matcher import SchemaEmbedder
        STATE["embedder"] = SchemaEmbedder(STATE["schema"])
    except Exception as e:
        print(f"[warn] semantic stage unavailable, continuing without it: {e}")
        STATE["embedder"] = None
    return STATE["embedder"]


@app.post("/api/query")
def query(req: QueryRequest):
    if not manager.is_connected() or STATE["schema"] is None:
        raise HTTPException(status_code=400, detail="Connect to a database first.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set in .env")

    active = manager.active
    embedder = _get_embedder() if req.use_semantic else None

    res = answer_question(
        question=req.question,
        engine=active.engine,
        schema=STATE["schema"],
        api_key=api_key,
        embedder=embedder,
        dialect=active.dialect,
    )
    log_history(active.database, res)
    return res


@app.get("/api/history")
def history(limit: int = 50):
    con = sqlite3.connect(HISTORY_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/")
def index():
    f = Path(__file__).parent.parent / "frontend" / "index.html"
    if f.exists():
        return FileResponse(f)
    return {"message": "SchemaRover API. Frontend not found."}
