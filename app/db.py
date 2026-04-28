"""SQLite connection helpers.

The collector and read paths are in the same process; SQLite is opened with
WAL so concurrent readers don't block the polling writer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    db_path = Path(db_path)
    if read_only:
        # URI form so we can open RO without creating the file.
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=30.0,
            check_same_thread=False,
        )
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,  # autocommit; explicit BEGIN when needed
        )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_schema(db_path: str | Path) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(db_path) as conn:
        conn.executescript(sql)
