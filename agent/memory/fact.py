"""Fact store — the persistent state for the memory system.

A Fact is one atomic, self-contained sentence that describes some
long-term state about the user, the agent, or the project.

``FactStore`` is the canonical storage — all facts live in a single
JSON file (``fact_pool.json``) that is memory-mapped at load time.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_FACT_POOL_PATH = os.path.join(_MEMORY_DIR, "fact_pool.json")
_VERSION_PATH = os.path.join(_MEMORY_DIR, "compiled_version.txt")

# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    """One atomic, self-contained memory unit."""

    id: str = ""
    content: str = ""
    topic: str = ""
    source: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active: bool = True
    supersedes: str | None = None
    view_score: float = 0.0
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Fact:
        return Fact(**d)


# ---------------------------------------------------------------------------
# FactStore
# ---------------------------------------------------------------------------


class FactStore:
    """In-memory fact pool backed by a single JSON file.

    Thread-safe for reads and writes (single-threaded writes via RLock).
    """

    def __init__(self, path: str | None = None, version_path: str | None = None) -> None:
        self._path = path or _FACT_POOL_PATH
        self._version_path = version_path or _VERSION_PATH
        self._lock = threading.RLock()
        self._facts: dict[str, Fact] = {}
        self._next_id: int = 1
        self._dirty: bool = False
        self._properties: list[dict[str, str]] = []  # [{key:, value:}, ...]
        self._load()

    # ── persistence ───────────────────────────────────────────

    def _load(self) -> None:
        """Load facts from JSON, or start empty."""
        os.makedirs(_MEMORY_DIR, exist_ok=True)
        if not os.path.isfile(self._path):
            log.debug("No fact pool found at %s, starting empty", self._path)
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            self._next_id = raw.get("next_id", 1)
            self._properties = raw.get("properties", [])
            for d in raw.get("facts", []):
                f = Fact.from_dict(d)
                self._facts[f.id] = f
            log.debug("Loaded %d facts (next_id=%d)", len(self._facts), self._next_id)
        except (json.JSONDecodeError, KeyError) as e:
            log.error("Failed to load fact pool: %s — starting empty", e)

    def save(self) -> None:
        """Write facts to JSON. No-op if nothing changed."""
        if not self._dirty:
            return
        with self._lock:
            blob = {
                "version": 1,
                "next_id": self._next_id,
                "properties": self._properties,
                "facts": [f.to_dict() for f in self._facts.values()],
            }
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            self._dirty = False
            log.debug("Fact pool saved (%d facts)", len(self._facts))

    # ── id generation ────────────────────────────────────────

    def _next_fact_id(self) -> str:
        n = self._next_id
        self._next_id += 1
        self._dirty = True
        return f"fact_{n:03d}"

    # ── commit ────────────────────────────────────────────────

    def commit(self, fact: Fact, conflicting: Fact | None = None) -> Fact:
        """Write a new fact to the store.

        If *conflicting* is provided, the old fact is marked inactive
        and the new fact records a ``supersedes`` link.
        """
        with self._lock:
            if conflicting is not None:
                conflicting.active = False
                fact.supersedes = conflicting.id
            fact.id = self._next_fact_id()
            fact.view_score = 0.3  # initial bias
            fact.created_at = datetime.now(timezone.utc).isoformat()
            self._facts[fact.id] = fact
            self._dirty = True
            log.debug("Committed %s (supersedes=%s)", fact.id, fact.supersedes)
        return fact

    # ── queries ───────────────────────────────────────────────

    def all(self, active: bool | None = True) -> list[Fact]:
        """Return all facts, optionally filtered by *active* status."""
        if active is None:
            return list(self._facts.values())
        return [f for f in self._facts.values() if f.active == active]

    def get_by_topic(self, topic: str, active: bool | None = True) -> list[Fact]:
        """Return facts belonging to *topic*.

        *active* controls filtering:
        ``True`` (default) — only active facts.
        ``False`` — only inactive facts.
        ``None`` — all facts regardless of active status.
        """
        if active is None:
            return [f for f in self._facts.values() if f.topic == topic]
        return [f for f in self._facts.values()
                if f.topic == topic and f.active == active]

    def get_by_id(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def count(self, active: bool | None = True) -> int:
        if active is None:
            return len(self._facts)
        return sum(1 for f in self._facts.values() if f.active == active)

    # ── properties ───────────────────────────────────────────

    def set_properties(self, props: list[dict[str, str]]) -> None:
        self._properties = props
        self._dirty = True

    def get_properties(self) -> list[dict[str, str]]:
        return list(self._properties)

    # ── view scores (called by compiler) ─────────────────────

    def update_view_scores(self, selected_ids: list[str], decay: float = 0.8) -> None:
        """Decay all active fact scores, then boost selected ones.

        Called once per compilation cycle.
        """
        with self._lock:
            for f in self._facts.values():
                if f.active:
                    f.view_score = round(f.view_score * decay, 4)
            for fid in selected_ids:
                fact = self._facts.get(fid)
                if fact and fact.active:
                    fact.view_score = round(fact.view_score + 1.0, 4)
            self._dirty = True

    # ── compile-tracking ─────────────────────────────────────

    def mark_compiled(self) -> None:
        """Persist a compile-version marker so we can skip redundant compiles."""
        with self._lock:
            # Use float precision to match ``os.path.getmtime()`` resolution.
            stamp = str(time.time())
            os.makedirs(os.path.dirname(self._version_path), exist_ok=True)
            with open(self._version_path, "w") as f:
                f.write(stamp)

    def has_changed_since_last_compile(self) -> bool:
        """Return ``True`` if facts have been committed since the last compile.

        Checks modification time of fact_pool.json vs the marker file.
        If either file is missing, returns ``True`` (needs compile).
        """
        if not os.path.isfile(self._path):
            return True
        pool_mtime = os.path.getmtime(self._path)
        if not os.path.isfile(self._version_path):
            return True
        with open(self._version_path) as f:
            raw = f.read().strip()
        if not raw:
            return True
        try:
            compiled_mtime = float(raw)
        except ValueError:
            return True
        return pool_mtime > compiled_mtime
