"""SQLite-backed conversation archive.

Stores every session and its messages in a local SQLite database under
memory/chat_history/history.db for later recall.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from logger import get_logger

log = get_logger(__name__)


_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "chat_history")
_DB_PATH = os.path.join(_DB_DIR, "history.db")

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local connection (lazy, with WAL mode)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
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

    # ── migration: add turn column if missing (legacy) ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN turn INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # already exists

    # ── migration 2026-06: rename turn → conversation_round ──
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "turn" in cols and "conversation_round" not in cols:
        try:
            conn.execute("ALTER TABLE messages RENAME COLUMN turn TO conversation_round")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE messages ADD COLUMN conversation_round INTEGER DEFAULT 0")
            conn.execute("UPDATE messages SET conversation_round = turn WHERE turn IS NOT NULL")

    # ── migration: add reasoning column if missing ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN reasoning TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # already exists

    # ── migration: add tool_call_id column if missing ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN tool_call_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # already exists

    # ── migration: add tool_calls column if missing ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN tool_calls TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # already exists

    # ── migration: add prompt_tokens column if missing ──
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN prompt_tokens INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # already exists

    # ── migration: add workspace_path column to sessions ──
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN workspace_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # already exists

    log.info("Database initialized at %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def reset_db():
    """Delete all data and reinitialize (for /reset)."""
    log.warning("Resetting database — all sessions will be lost")
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
    sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log.debug("Created session #%s", sid)
    return sid


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


def update_session_workspace(session_id: int, path: str):
    """Save workspace path for session recovery."""
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET workspace_path = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
        (path, session_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def save_message(session_id: int, role: str, content, tool_name: str = "", conversation_round: int = 0, reasoning: str = "", tool_call_id: str = "", tool_calls: str = "", prompt_tokens: int | None = None):
    # Ensure content is a string for DB storage
    if isinstance(content, list):
        import json
        content = json.dumps(content, ensure_ascii=False)
    conn = _get_connection()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, tool_name, conversation_round, reasoning, tool_call_id, tool_calls, prompt_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, role, content, tool_name or None, conversation_round, reasoning or None, tool_call_id or None, tool_calls or None, prompt_tokens),
    )
    conn.commit()
    log.debug("Saved %s message to session #%s (round=%s)", role, session_id, conversation_round)


# ---------------------------------------------------------------------------
# Recall helpers (for future use by the recall tool)
# ---------------------------------------------------------------------------

def get_session_messages(session_id: int):
    """Return all messages for a session, oldest first."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, role, content, tool_name, conversation_round, created_at, reasoning, tool_call_id, tool_calls, prompt_tokens FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_last_prompt_tokens(session_id: int) -> int | None:
    """Return the last saved prompt_tokens for a session, or None."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT prompt_tokens FROM messages WHERE session_id = ? AND prompt_tokens IS NOT NULL ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["prompt_tokens"] if row else None


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


def get_session_by_id(session_id: int):
    """Return a single session dict or None."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id, title, marker, created_at, updated_at, workspace_path FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_session(session_id: int):
    """Delete a session and all its messages."""
    conn = _get_connection()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def get_session_count() -> int:
    """Return total number of sessions."""
    conn = _get_connection()
    return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
