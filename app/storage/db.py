"""
Storage layer — SQLite database connection and table initialization.
"""

import sqlite3
import contextlib
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "fluxschema.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextlib.contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all required tables if they do not exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS field_mapping_table (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_name     TEXT NOT NULL,
                source_field    TEXT NOT NULL,
                canonical_field TEXT NOT NULL,
                confidence      REAL NOT NULL DEFAULT 0.5,
                frequency       INTEGER NOT NULL DEFAULT 1,
                last_seen       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(schema_name, source_field, canonical_field)
            );

            CREATE INDEX IF NOT EXISTS idx_fmt_lookup
                ON field_mapping_table(schema_name, source_field);

            CREATE TABLE IF NOT EXISTS correction_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_name     TEXT NOT NULL,
                source_field    TEXT NOT NULL,
                mapped_field    TEXT NOT NULL,
                method_used     TEXT NOT NULL,
                confidence      REAL NOT NULL,
                timestamp       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schema_statistics (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_name       TEXT NOT NULL,
                field_name        TEXT NOT NULL,
                occurrence_count  INTEGER NOT NULL DEFAULT 1,
                success_rate      REAL NOT NULL DEFAULT 1.0,
                UNIQUE(schema_name, field_name)
            );
        """)
