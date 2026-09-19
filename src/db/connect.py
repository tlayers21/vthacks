"""The one place a SQLite connection is created.

Every connection gets `PRAGMA foreign_keys = ON`. SQLite defaults this OFF *per
connection*, so the foreign keys declared in schema.sql are decorative until it is set --
without it you can insert an account pointing at a customer that does not exist.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config import settings


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts instead of tuples
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
