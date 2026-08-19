"""
connection.py — Connection Manager (T1.2)

Replaces the hardcoded DB_URL approach. The user supplies a connection
string at RUNTIME, which is what makes the "works on any database, zero
config" claim actually true.

Responsibilities:
  - validate the URL shape before trying to connect
  - open + test the connection (fail fast, with a readable message)
  - hold one active connection per session
  - never let a bad URL surface as a raw SQLAlchemy traceback
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

SUPPORTED_PREFIXES = (
    "mysql+pymysql://",
    "mysql://",
    "postgresql+psycopg2://",
    "postgresql://",
    "sqlite:///",  # needed for Spider evaluation
)


class ConnectionError_(Exception):
    """Readable connection failure, safe to show a user."""


@dataclass
class ActiveConnection:
    url: str
    engine: Engine
    dialect: str
    database: str

    def safe_url(self) -> str:
        """URL with the password masked — for logs and UI."""
        if "@" not in self.url:
            return self.url
        scheme, rest = self.url.split("://", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:****@{host}"


class ConnectionManager:
    def __init__(self):
        self._active: Optional[ActiveConnection] = None

    def connect(self, db_url: str) -> ActiveConnection:
        db_url = (db_url or "").strip()

        if not db_url:
            raise ConnectionError_("No database URL provided.")

        if not db_url.startswith(SUPPORTED_PREFIXES):
            raise ConnectionError_(
                "Unsupported database URL. Expected one of: "
                "mysql+pymysql://user:pass@host:port/db, "
                "postgresql://user:pass@host:port/db, or sqlite:///path.db"
            )

        try:
            # pool_pre_ping avoids handing out dead connections after idle
            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as e:
            raise ConnectionError_(self._humanize(e)) from e
        except Exception as e:  # driver import errors, malformed URLs
            raise ConnectionError_(f"Could not connect: {type(e).__name__}: {e}") from e

        self._active = ActiveConnection(
            url=db_url,
            engine=engine,
            dialect=engine.dialect.name,
            database=engine.url.database or "",
        )
        return self._active

    @property
    def active(self) -> ActiveConnection:
        if self._active is None:
            raise ConnectionError_("Not connected to any database yet.")
        return self._active

    def is_connected(self) -> bool:
        return self._active is not None

    def table_count(self) -> int:
        return len(inspect(self.active.engine).get_table_names())

    def disconnect(self):
        if self._active:
            self._active.engine.dispose()
            self._active = None

    @staticmethod
    def _humanize(e: SQLAlchemyError) -> str:
        msg = str(e).lower()
        if "access denied" in msg or "password authentication failed" in msg:
            return "Access denied — check the username and password."
        if "unknown database" in msg or "does not exist" in msg:
            return "That database name doesn't exist on the server."
        if "can't connect" in msg or "connection refused" in msg or "timed out" in msg:
            return "Couldn't reach the database server — check host, port, and that it's running."
        if "no module named" in msg or "modulenotfounderror" in msg:
            return "Missing database driver. Install pymysql (MySQL) or psycopg2-binary (PostgreSQL)."
        return f"Connection failed: {str(e)[:200]}"


# module-level singleton used by the API
manager = ConnectionManager()
