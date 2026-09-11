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

import hmac
import os
import json
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


# ---------------- admin gate ----------------
# /api/connect points this server at an arbitrary database, so it is privileged.
# One shared token, set in .env. Not user accounts — this is a single-operator console.
ADMIN_TOKEN = os.environ.get("SCHEMAROVER_ADMIN_TOKEN", "")


def require_admin(x_admin_token: str = Header(default="")):
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="SCHEMAROVER_ADMIN_TOKEN is not set in .env — admin endpoints are disabled.",
        )
    if not hmac.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


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


@app.post("/api/connect", dependencies=[Depends(require_admin)])
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


@app.get("/api/schema", dependencies=[Depends(require_admin)])
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


@app.get("/api/history", dependencies=[Depends(require_admin)])
def history(limit: int = 50):
    con = sqlite3.connect(HISTORY_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ---------------- static frontend ----------------
# Serves the built Vite app. Any non-/api path falls through to index.html so
# client-side routes like /admin work on a hard refresh.
UI_DIST = Path(__file__).parent.parent / "ui" / "dist"
LEGACY = Path(__file__).parent.parent / "frontend" / "legacy-index.html"

if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        return FileResponse(UI_DIST / "index.html")

else:
    @app.get("/")
    def index():
        if LEGACY.exists():
            return FileResponse(LEGACY)
        return {"message": "SchemaRover API. Run `npm run build` in ui/ to serve the frontend."}
