"""
validator.py — read-only SQL enforcement (T1.6)

The system executes LLM-generated SQL against a real user database. The
validator is the only thing standing between a bad generation and data
loss, so it is deliberately strict and DENY-BY-DEFAULT: anything that is
not a plain single SELECT/WITH query is rejected.

Layers:
  1. strip comments (block a payload hidden behind `--` or `/* */`)
  2. reject stacked statements (`SELECT 1; DROP TABLE x`)
  3. require the statement to START as SELECT or WITH
  4. blocklist destructive/DDL/DCL keywords as whole words
  5. block obvious file/system access functions

NOTE (be honest in the paper): this is defense-in-depth, not a proof of
safety. The real guarantee is connecting with a DB user that only has
SELECT permission. State that as the primary control; this validator is
the second layer.
"""

import re

BLOCKED_KEYWORDS = [
    # destructive DML
    "drop", "delete", "truncate", "update", "insert", "replace", "merge", "upsert",
    # DDL
    "alter", "create", "rename", "comment",
    # DCL / privileges
    "grant", "revoke",
    # transaction / session control
    "commit", "rollback", "savepoint", "set", "lock", "unlock",
    # procedural / execution
    "call", "execute", "exec", "do", "handler", "prepare", "deallocate",
    # server-level
    "shutdown", "kill", "flush", "reset", "restore", "backup", "vacuum", "analyze",
    # file access
    "outfile", "dumpfile", "infile", "load_file", "load",
    # postgres extras
    "copy", "pg_read_file", "pg_sleep", "pg_ls_dir",
]

BLOCKED_PATTERNS = [
    (re.compile(r"\binto\s+(out|dump)file\b", re.I), "file write attempt"),
    (re.compile(r"\bload_file\s*\(", re.I), "file read attempt"),
    (re.compile(r"\bpg_read_file\s*\(", re.I), "file read attempt"),
    (re.compile(r"\bsleep\s*\(", re.I), "time-delay function"),
    (re.compile(r"\bbenchmark\s*\(", re.I), "resource-abuse function"),
    (re.compile(r"\binformation_schema\b", re.I), "metadata table access"),
]


class ValidationError(Exception):
    pass


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)   # /* block */
    sql = re.sub(r"--[^\n]*", " ", sql)                 # -- line
    sql = re.sub(r"#[^\n]*", " ", sql)                  # # line (MySQL)
    return sql


def clean_sql(raw: str) -> str:
    """Strip markdown fences the LLM often adds, and trailing semicolons."""
    s = raw.strip()
    s = re.sub(r"^```(?:sql)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip().rstrip(";").strip()


def validate(raw_sql: str) -> str:
    """Return cleaned SQL if safe; raise ValidationError otherwise."""
    if not raw_sql or not raw_sql.strip():
        raise ValidationError("Empty query generated.")

    sql = clean_sql(raw_sql)
    probe = strip_comments(sql)

    # stacked statements: any semicolon with content after it
    if ";" in probe.rstrip(";"):
        raise ValidationError("Multiple SQL statements are not allowed.")

    stripped = probe.strip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValidationError("Only SELECT queries are allowed (read-only).")

    # Scan BOTH the comment-stripped text AND the raw text. Stripping alone
    # is not enough: `SELECT * FROM t -- ; DELETE FROM x` looks clean after
    # stripping, but the string actually sent to the driver still contains
    # DELETE. Deny-by-default means we refuse to send it at all.
    for surface in (probe, sql):
        for kw in BLOCKED_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", surface, re.I):
                raise ValidationError(
                    f"Blocked keyword detected: '{kw.upper()}' — read-only mode."
                )
        for pattern, reason in BLOCKED_PATTERNS:
            if pattern.search(surface):
                raise ValidationError(f"Blocked pattern detected: {reason}.")

    # no comment syntax at all in what we execute
    if re.search(r"(--|/\*|#)", sql):
        raise ValidationError("Comments are not allowed in generated SQL.")

    return sql


def enforce_limit(sql: str, max_rows: int = 200) -> str:
    """Append a LIMIT so a runaway SELECT can't return a million rows."""
    if re.search(r"\blimit\s+\d+", sql, re.I):
        return sql
    return f"{sql} LIMIT {max_rows}"
