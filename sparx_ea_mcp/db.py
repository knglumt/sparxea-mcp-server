"""
Single-driver (pyodbc) database layer.

Every query in this module (and in repository.py, which is the only other
module allowed to call it) is a parameterized, ANSI-SQL SELECT. Nothing in
this server ever writes to the EA repository - this is intentional,
matching the request to build a *reading* MCP server.
"""

from __future__ import annotations

import contextlib
import datetime
import decimal
import logging
from typing import Any, Iterable, Optional

import pyodbc

from .config import Backend, get_config

logger = logging.getLogger("sparx_ea_mcp.db")

# Belt-and-braces guard: refuse to execute anything that isn't a read.
# repository.py should never produce such statements, but this stops a
# future bug (or a misbehaving caller) from turning this into a write path.
_DISALLOWED_KEYWORDS = (
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ",
    "MERGE ", "EXEC ", "EXECUTE ", "CREATE ", "GRANT ", "REVOKE ",
)


def _assert_read_only(sql: str) -> None:
    stripped = sql.strip().upper()
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        raise ValueError("Only SELECT statements are permitted by this server.")
    padded = f" {stripped} "
    for kw in _DISALLOWED_KEYWORDS:
        if kw in padded:
            raise ValueError(f"Statement contains disallowed keyword: {kw.strip()}")


@contextlib.contextmanager
def get_connection():
    cfg = get_config()
    conn = pyodbc.connect(cfg.connection_string(), timeout=cfg.connect_timeout)
    try:
        if cfg.backend in (Backend.MYSQL, Backend.MARIADB):
            # MySQL/MariaDB treat "double quoted" text as a string literal
            # unless ANSI_QUOTES is enabled, which repository.py's queries
            # rely on for quoting reserved-word columns like "Default".
            cur = conn.cursor()
            cur.execute("SET SESSION sql_mode = CONCAT(@@sql_mode, ',ANSI_QUOTES')")
            cur.close()
        yield conn
    finally:
        conn.close()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<binary data, {len(value)} bytes - not returned>"
    if isinstance(value, str):
        return value.strip("\x00")
    return value


def run_query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    """Execute a SELECT and return rows as a list of plain, JSON-safe dicts."""
    _assert_read_only(sql)
    params = list(params)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        if cursor.description is None:
            return []
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [
            {col: _normalize_value(val) for col, val in zip(columns, row)}
            for row in rows
        ]


def run_query_one(sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = run_query(sql, params)
    return rows[0] if rows else None


def check_connection() -> dict:
    """
    Report which DBMS this server is actually talking to, using ODBC's own
    standard introspection calls (SQLGetInfo) rather than a vendor-specific
    query, so this works identically regardless of backend.
    """
    with get_connection() as conn:
        return {
            "configured_backend": get_config().backend.value,
            "dbms_name": conn.getinfo(pyodbc.SQL_DBMS_NAME),
            "dbms_version": conn.getinfo(pyodbc.SQL_DBMS_VER),
            "driver_name": conn.getinfo(pyodbc.SQL_DRIVER_NAME),
            "database_name": conn.getinfo(pyodbc.SQL_DATABASE_NAME),
        }
