"""
main.py — FastAPI backend (T1.4)

Endpoints (all but health + auth need `Authorization: Bearer <token>`):
  POST   /api/auth/signup | /api/auth/login   {email, password} -> {token, email}
  POST   /api/auth/logout
  GET    /api/auth/me
  GET    /api/connections                   -> this user's saved connections
  POST   /api/connect      {db_url, name?}  -> connect, save, return schema summary
  POST   /api/connections/{id}/connect      -> reconnect to a saved one
  DELETE /api/connections/{id}
  GET    /api/schema                        -> full schema of the user's active DB
  POST   /api/query        {question}       -> linked tables + SQL + results
  GET    /api/history                       -> this user's past queries (no rows)
  GET    /api/history/{id}                  -> one past answer, rows included
  GET    /api/health

Run:
    uvicorn main:app --reload --port 8000
"""

import hmac
import ipaddress
import os
import json
import socket
import sqlite3
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from auth import Auth, AuthError
from connection import ConnectionManager, ConnectionError_
from pipeline import get_schema, answer_question

load_dotenv()

app = FastAPI(title="SchemaRover API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

HISTORY_DB = Path(__file__).parent / "history.db"
auth = Auth(HISTORY_DB, os.environ.get("SCHEMAROVER_SECRET_KEY", ""))

# Per-user in-memory state: each user has their own active connection,
# schema, and embedder. Lost on restart — /api/query reconnects to the
# user's most recently used saved connection when that happens.
# ponytail: one SchemaEmbedder per user, so RAM grows ~100MB per active
# user; share embedders keyed by database if many users hit the same DB.
STATE = defaultdict(lambda: {"mgr": ConnectionManager(), "schema": None, "embedder": None})


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
    cols = [r[1] for r in con.execute("PRAGMA table_info(history)")]
    # older databases predate these columns; old rows keep NULLs
    for col, typ in [("user_id", "INTEGER"), ("result_json", "TEXT")]:
        if col not in cols:
            con.execute(f"ALTER TABLE history ADD COLUMN {col} {typ}")
    con.commit()
    con.close()


def log_history(user_id, db, res):
    con = sqlite3.connect(HISTORY_DB)
    con.execute(
        "INSERT INTO history (user_id,database,question,sql,linked_tables,total_tables,elapsed_ms,row_count,error,result_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, db, res["question"], res.get("sql"),
         json.dumps(res["linked"]["tables"]), res.get("total_tables_in_db", 0),
         res.get("elapsed_ms", 0), len(res.get("rows", [])), res.get("error"),
         # the full answer (rows are capped at max_rows), so reopening it from
         # history needs no LLM call or DB query. default=str covers Decimal/datetime.
         json.dumps(res, default=str)),
    )
    con.commit()
    con.close()


init_history()


# ---------------- auth ----------------

def _bearer(authorization: str) -> str:
    return authorization[7:] if authorization.lower().startswith("bearer ") else ""


def current_user(authorization: str = Header(default="")) -> dict:
    user = auth.user_for(_bearer(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


# ---------------- models ----------------

class Credentials(BaseModel):
    email: str
    password: str
    invite: str = ""


class ConnectRequest(BaseModel):
    db_url: str
    name: str = ""


class QueryRequest(BaseModel):
    question: str
    use_semantic: bool = True


# ---------------- endpoints ----------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/auth/signup")
def signup(c: Credentials):
    code = os.environ.get("SCHEMAROVER_SIGNUP_CODE", "")
    if code and not hmac.compare_digest(c.invite, code):
        raise HTTPException(status_code=403, detail="That invite code isn't valid.")
    try:
        token = auth.signup(c.email, c.password)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "email": c.email.strip().lower()}


@app.post("/api/auth/login")
def login(c: Credentials):
    try:
        token = auth.login(c.email, c.password)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"token": token, "email": c.email.strip().lower()}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    auth.logout(_bearer(authorization))
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    s = STATE[user["id"]]
    return {"email": user["email"], "connection": _summary(s) if s["schema"] else None}


def _summary(s: dict) -> dict:
    active, schema = s["mgr"].active, s["schema"]
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


# sqlite is deliberately absent: sqlite:/// would let a user open any file on
# this server, including history.db with everyone's password hashes. Eval uses
# sqlite directly, never through the API.
ALLOWED_DRIVERS = {"mysql", "mysql+pymysql", "postgresql", "postgresql+psycopg2"}


def _check_url(db_url: str):
    """Users choose where this server connects, so stop it being aimed inward:
    no odd drivers, no URL options (e.g. local_infile), no internal hosts."""
    try:
        u = make_url(db_url.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="That doesn't look like a database URL.")
    if u.drivername not in ALLOWED_DRIVERS:
        raise HTTPException(status_code=400, detail="Only MySQL and PostgreSQL URLs are supported.")
    if u.query:
        raise HTTPException(status_code=400, detail="Connection options in the URL aren't allowed.")
    if not u.host:
        raise HTTPException(status_code=400, detail="The URL needs a host.")
    if os.environ.get("SCHEMAROVER_ALLOW_PRIVATE_HOSTS", "").lower() == "true":
        return  # local dev: your DB is on localhost
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(u.host, u.port or 0)}
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Couldn't find that database host.")
    # ponytail: checks at resolve time; a DNS-rebinding host could flip between
    # this check and the real connect. Pin the resolved IP if that threat matters.
    if any(not ipaddress.ip_address(ip.split("%")[0]).is_global for ip in addrs):
        raise HTTPException(status_code=400, detail="Private or internal network hosts aren't allowed.")


def _open(user: dict, db_url: str, name: str = "") -> dict:
    """Connect this user to db_url, introspect it, and save it to their list."""
    _check_url(db_url)
    s = STATE[user["id"]]
    try:
        active = s["mgr"].connect(db_url)
    except ConnectionError_ as e:
        raise HTTPException(status_code=400, detail=str(e))
    s["schema"] = get_schema(active.engine)
    s["embedder"] = None  # rebuilt lazily on first semantic query
    auth.save_connection(user["id"], name.strip() or active.database, active.url, active.safe_url())
    return _summary(s)


@app.post("/api/connect")
def connect(req: ConnectRequest, user: dict = Depends(current_user)):
    return _open(user, req.db_url, req.name)


@app.get("/api/connections")
def list_connections(user: dict = Depends(current_user)):
    return auth.list_connections(user["id"])


@app.post("/api/connections/{conn_id}/connect")
def use_connection(conn_id: int, user: dict = Depends(current_user)):
    try:
        url = auth.connection_url(user["id"], conn_id)
    except AuthError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _open(user, url)


@app.delete("/api/connections/{conn_id}")
def delete_connection(conn_id: int, user: dict = Depends(current_user)):
    auth.delete_connection(user["id"], conn_id)
    return {"ok": True}


@app.get("/api/schema")
def schema_endpoint(user: dict = Depends(current_user)):
    s = STATE[user["id"]]
    if s["schema"] is None:
        raise HTTPException(status_code=400, detail="Not connected to a database.")
    return s["schema"]


def _get_embedder(s: dict):
    """Build the SchemaEmbedder once per connected DB (never per query)."""
    if s["embedder"] is not None:
        return s["embedder"]
    try:
        from Semantic_matcher import SchemaEmbedder
        s["embedder"] = SchemaEmbedder(s["schema"])
    except Exception as e:
        print(f"[warn] semantic stage unavailable, continuing without it: {e}")
        s["embedder"] = None
    return s["embedder"]


@app.post("/api/query")
def query(req: QueryRequest, user: dict = Depends(current_user)):
    s = STATE[user["id"]]
    if s["schema"] is None:
        # server restarted or first visit: fall back to the last DB they used
        try:
            _open(user, auth.connection_url(user["id"]))
        except (AuthError, HTTPException):
            raise HTTPException(status_code=400, detail="Connect to a database first.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set in .env")

    active = s["mgr"].active
    embedder = _get_embedder(s) if req.use_semantic else None

    res = answer_question(
        question=req.question,
        engine=active.engine,
        schema=s["schema"],
        api_key=api_key,
        embedder=embedder,
        dialect=active.dialect,
    )
    log_history(user["id"], active.database, res)
    return res


@app.get("/api/history")
def history(limit: int = 50, user: dict = Depends(current_user)):
    con = sqlite3.connect(HISTORY_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ts, database, question, sql, linked_tables, total_tables, elapsed_ms, row_count, error,"
        " result_json IS NOT NULL AS has_result"
        " FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user["id"], limit)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/history/{entry_id}")
def history_entry(entry_id: int, user: dict = Depends(current_user)):
    """One past answer, exactly as it was returned — scoped to its owner."""
    con = sqlite3.connect(HISTORY_DB)
    row = con.execute(
        "SELECT ts, result_json FROM history WHERE id = ? AND user_id = ?", (entry_id, user["id"])
    ).fetchone()
    con.close()
    if not row or not row[1]:
        raise HTTPException(status_code=404, detail="That result wasn't saved.")
    return {**json.loads(row[1]), "ts": row[0]}


# ---------------- static frontend ----------------
# Serves the built Vite app. Any non-/api path falls through to index.html so
# client-side routes like /admin work on a hard refresh.
UI_DIST = Path(__file__).parent.parent / "ui" / "dist"

if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        return FileResponse(UI_DIST / "index.html")

else:
    @app.get("/")
    def index():
        return {"message": "SchemaRover API. Run `npm run build` in ui/ to serve the frontend."}
