"""
auth.py — user accounts, login sessions, and saved DB connections.

  passwords     hashlib.scrypt + per-user salt (stdlib, never stored plain)
  sessions      random token handed to the browser; only its SHA-256 is
                stored, so a leaked DB file can't be replayed as logins
  connections   saved connection strings hold DB passwords, so they are
                encrypted at rest (Fernet) with SCHEMAROVER_SECRET_KEY

Everything lives in the same SQLite file as the query history.
"""

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time

from cryptography.fernet import Fernet

SESSION_SECONDS = 7 * 24 * 3600


class AuthError(Exception):
    """Safe to show a user."""


class Auth:
    def __init__(self, db_path, secret_key: str):
        if not secret_key:
            raise RuntimeError(
                "SCHEMAROVER_SECRET_KEY is not set. Generate one with:\n"
                "  python -c \"import secrets;print(secrets.token_urlsafe(32))\""
            )
        self.db_path = db_path
        # Fernet wants exactly 32 url-safe base64 bytes; derive them from any string.
        self.fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))
        with self._db() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    pw_salt BLOB NOT NULL, pw_hash BLOB NOT NULL,
                    created DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL, safe_url TEXT NOT NULL,
                    url_hash TEXT NOT NULL, url_enc BLOB NOT NULL,
                    last_used REAL NOT NULL,
                    UNIQUE (user_id, url_hash)
                );
            """)

    def _db(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # ---------------- accounts ----------------

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)

    def signup(self, email: str, password: str) -> str:
        email = (email or "").strip().lower()
        if "@" not in email:
            raise AuthError("Enter a valid email address.")
        if len(password or "") < 8:
            raise AuthError("Password must be at least 8 characters.")
        salt = secrets.token_bytes(16)
        try:
            with self._db() as con:
                con.execute(
                    "INSERT INTO users (email, pw_salt, pw_hash) VALUES (?,?,?)",
                    (email, salt, self._hash(password, salt)),
                )
        except sqlite3.IntegrityError:
            raise AuthError("An account with that email already exists.")
        return self.login(email, password)

    def login(self, email: str, password: str) -> str:
        email = (email or "").strip().lower()
        with self._db() as con:
            u = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        # same message for "no such user" and "wrong password" — don't leak which emails exist
        if not u or not hmac.compare_digest(self._hash(password or "", u["pw_salt"]), u["pw_hash"]):
            raise AuthError("Wrong email or password.")
        token = secrets.token_urlsafe(32)
        with self._db() as con:
            con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            con.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (_sha(token), u["id"], time.time() + SESSION_SECONDS),
            )
        return token

    def user_for(self, token: str):
        """Session token -> {id, email}, or None if missing/expired."""
        if not token:
            return None
        with self._db() as con:
            row = con.execute(
                "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash = ? AND s.expires > ?",
                (_sha(token), time.time()),
            ).fetchone()
        return dict(row) if row else None

    def logout(self, token: str):
        with self._db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))

    # ---------------- saved connections ----------------

    def save_connection(self, user_id: int, name: str, url: str, safe_url: str) -> int:
        """Insert, or bump last_used if this user already saved this URL."""
        with self._db() as con:
            con.execute(
                "INSERT INTO connections (user_id, name, safe_url, url_hash, url_enc, last_used)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT (user_id, url_hash) DO UPDATE SET last_used = excluded.last_used",
                (user_id, name, safe_url, _sha(url), self.fernet.encrypt(url.encode()), time.time()),
            )
            return con.execute(
                "SELECT id FROM connections WHERE user_id = ? AND url_hash = ?", (user_id, _sha(url))
            ).fetchone()["id"]

    def list_connections(self, user_id: int) -> list:
        with self._db() as con:
            rows = con.execute(
                "SELECT id, name, safe_url, last_used FROM connections"
                " WHERE user_id = ? ORDER BY last_used DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def connection_url(self, user_id: int, conn_id=None) -> str:
        """Decrypted URL of one saved connection (or the most recently used one).
        Scoped by user_id so nobody can open someone else's connection by id."""
        with self._db() as con:
            if conn_id is None:
                row = con.execute(
                    "SELECT url_enc FROM connections WHERE user_id = ? ORDER BY last_used DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT url_enc FROM connections WHERE user_id = ? AND id = ?", (user_id, conn_id)
                ).fetchone()
        if not row:
            raise AuthError("Saved connection not found.")
        return self.fernet.decrypt(row["url_enc"]).decode()

    def delete_connection(self, user_id: int, conn_id: int):
        with self._db() as con:
            con.execute("DELETE FROM connections WHERE user_id = ? AND id = ?", (user_id, conn_id))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _self_check():
    import os
    import tempfile

    path = os.path.join(tempfile.mkdtemp(), "t.db")
    a = Auth(path, "test-secret")

    tok = a.signup("Alice@Example.com", "password123")
    alice = a.user_for(tok)
    assert alice["email"] == "alice@example.com"

    for bad in [("alice@example.com", "password123"), ("x", "password123"), ("b@b.co", "short")]:
        try:
            a.signup(*bad)
            raise AssertionError(f"signup should fail: {bad}")
        except AuthError:
            pass
    try:
        a.login("alice@example.com", "wrong-password")
        raise AssertionError("wrong password accepted")
    except AuthError:
        pass

    url = "mysql+pymysql://root:s3cret@localhost/sakila"
    cid = a.save_connection(alice["id"], "sakila", url, "mysql+pymysql://root:****@localhost/sakila")
    assert a.save_connection(alice["id"], "sakila", url, "x") == cid, "same URL must not duplicate"
    assert a.connection_url(alice["id"], cid) == url
    assert a.connection_url(alice["id"]) == url  # most recent
    with sqlite3.connect(path) as con:
        assert b"s3cret" not in con.execute("SELECT url_enc FROM connections").fetchone()[0], "stored plain"

    bob = a.user_for(a.signup("bob@example.com", "password456"))
    assert a.list_connections(bob["id"]) == []
    try:
        a.connection_url(bob["id"], cid)
        raise AssertionError("bob read alice's connection")
    except AuthError:
        pass

    a.logout(tok)
    assert a.user_for(tok) is None
    a.delete_connection(alice["id"], cid)
    assert a.list_connections(alice["id"]) == []
    print("auth self-check OK")


if __name__ == "__main__":
    _self_check()
