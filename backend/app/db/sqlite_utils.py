from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe SQLite identifier: {value!r}")
    return f'"{value}"'


def connect_sqlite(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with conservative defaults for app tooling."""
    conn = sqlite3.connect(Path(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row["name"] == column_name for row in get_table_info(conn, table_name))


def get_table_info(conn: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})"))


def get_indexes(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    indexes: list[dict] = []
    for row in conn.execute(f"PRAGMA index_list({_quote_identifier(table_name)})"):
        index_name = str(row["name"])
        columns = [
            str(info["name"])
            for info in conn.execute(f"PRAGMA index_info({_quote_identifier(index_name)})")
            if info["name"] is not None
        ]
        indexes.append(
            {
                "name": index_name,
                "unique": bool(row["unique"]),
                "origin": row["origin"],
                "partial": bool(row["partial"]),
                "columns": columns,
            }
        )
    return indexes


def index_with_columns_exists(
    conn: sqlite3.Connection,
    table_name: str,
    columns: Iterable[str],
) -> bool:
    desired = list(columns)
    return any(index["columns"][: len(desired)] == desired for index in get_indexes(conn, table_name))


def safe_create_index(
    conn: sqlite3.Connection,
    index_name: str,
    table_name: str,
    columns: Iterable[str],
) -> dict:
    """Create an index only when the table/columns exist and no equivalent index exists."""
    columns = list(columns)
    result = {
        "index": index_name,
        "table": table_name,
        "columns": columns,
        "status": "unknown",
        "warning": None,
    }

    if not table_exists(conn, table_name):
        result["status"] = "skipped_missing_table"
        result["warning"] = f"table not found: {table_name}"
        return result

    missing = [column for column in columns if not column_exists(conn, table_name, column)]
    if missing:
        result["status"] = "skipped_missing_column"
        result["warning"] = f"missing columns on {table_name}: {', '.join(missing)}"
        return result

    if index_with_columns_exists(conn, table_name, columns):
        result["status"] = "skipped_existing_equivalent"
        return result

    index_sql = _quote_identifier(index_name)
    table_sql = _quote_identifier(table_name)
    columns_sql = ", ".join(_quote_identifier(column) for column in columns)
    conn.execute(f"CREATE INDEX IF NOT EXISTS {index_sql} ON {table_sql} ({columns_sql})")
    result["status"] = "created"
    return result

