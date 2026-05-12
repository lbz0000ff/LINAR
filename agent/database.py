"""SQLite-backed conversation archive.

Stores every session and its messages in a local SQLite database under
memory/chat_history/history.db for later recall.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone


_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "chat_history")
_DB_PATH = os.path.join(_DB_DIR, "history.db")

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local connection (lazy, with WAL mode)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT,
            marker     TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            role       TEXT NOT NULL,
            content    TEXT,
            tool_name  TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);
    """)
    conn.commit()

    # ── migration: add turn column if missing ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN turn INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # already exists


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def reset_db():
    """Delete all data and reinitialize (for /reset)."""
    conn = _get_connection()
    conn.executescript("""
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS sessions;
    """)
    conn.commit()
    init_db()  # recreates tables using the same connection


def create_session(title: str = "") -> int:
    """Create a new session and return its id."""
    conn = _get_connection()
    conn.execute("INSERT INTO sessions (title) VALUES (?)", (title,))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def update_session_title(session_id: int, title: str):
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
        (title, session_id),
    )
    conn.commit()


def update_session_marker(session_id: int, marker: str):
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET marker = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
        (marker, session_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def save_message(session_id: int, role: str, content: str, tool_name: str = "", turn: int = 0):
    conn = _get_connection()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, tool_name, turn) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, tool_name or None, turn),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Recall helpers (for future use by the recall tool)
# ---------------------------------------------------------------------------

def get_session_messages(session_id: int):
    """Return all messages for a session, oldest first."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, role, content, tool_name, turn, created_at FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_by_marker(marker: str):
    """Return the first session matching a marker (for recall by tag)."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id, title, marker, created_at FROM sessions WHERE marker = ? ORDER BY id DESC LIMIT 1",
        (marker,),
    ).fetchone()
    return dict(row) if row else None


def get_recent_sessions(limit: int = 10):
    """Return the most recent sessions (for session list views)."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, title, marker, created_at FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
