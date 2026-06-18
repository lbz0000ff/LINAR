"""Topic registry — lightweight topic definitions.

Topics are flat categories with a one-sentence definition that is
generated once and frozen.  They form a tree (each fact belongs to
exactly one topic), never a graph.
"""

from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------

_TOPICS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "state", "topics.json"
)

# ---------------------------------------------------------------------------
# Seed topics
# ---------------------------------------------------------------------------

_SEED_TOPICS: list[dict[str, str]] = [
    {
        "name": "preference",
        "definition": "user's personal preferences, habits, and behavioral tendencies",
    },
    {
        "name": "project",
        "definition": "current project state, decisions, and technical direction",
    },
    {
        "name": "behavior",
        "definition": "the agent's own behavior patterns, methodology, and long-term experience",
    },
    {
        "name": "workflow",
        "definition": "workflow preferences and toolchain configuration",
    },
]

_FUZZY_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


@dataclass
class Topic:
    """A flat semantic category for grouping facts."""

    name: str
    definition: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Topic:
        return Topic(**d)


# ---------------------------------------------------------------------------
# TopicRegistry
# ---------------------------------------------------------------------------


class TopicRegistry:
    """Load, save, and query topic definitions.

    If no persisted file exists, creates one with the seed topics on first run.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _TOPICS_PATH
        self._topics: dict[str, Topic] = {}
        self._load()

    # ── persistence ───────────────────────────────────────────

    def _load(self) -> None:
        """Load from JSON, or create seed file if missing."""
        if os.path.isfile(self._path):
            try:
                with open(self._path, encoding="utf-8") as f:
                    raw = json.load(f)
                for d in raw.get("topics", []):
                    t = Topic.from_dict(d)
                    self._topics[t.name] = t
                log.debug("Loaded %d topics from %s", len(self._topics), self._path)
                return
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Failed to load topics: %s — reseeding", e)

        log.info("Seeding default topics")
        for sd in _SEED_TOPICS:
            t = Topic(name=sd["name"], definition=sd.get("definition", ""))
            self._topics[t.name] = t
        self._save()

    def save(self) -> None:
        self._save()

    def _save(self) -> None:
        blob = {
            "version": 1,
            "topics": [t.to_dict() for t in self._topics.values()],
        }
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)
        log.debug("Saved %d topics", len(self._topics))

    # ── queries ───────────────────────────────────────────────

    def list_topics(self) -> list[Topic]:
        return list(self._topics.values())

    def find(self, name: str) -> Topic | None:
        return self._topics.get(name)

    def add(self, name: str, definition: str = "") -> Topic:
        """Add a new topic. Overwrites if *name* already exists."""
        t = Topic(name=name, definition=definition)
        self._topics[name] = t
        self._save()
        log.info("Added topic '%s': %s", name, definition or "(no definition)")
        return t

    def __contains__(self, name: str) -> bool:
        return name in self._topics

    # ── topic resolution ──────────────────────────────────────

    def resolve_topic(self, name: str) -> tuple[str, bool, bool]:
        """Resolve a topic name to an existing or new topic.

        Returns ``(resolved_name, is_new, fuzzy_matched)``:

        * Exact match → ``("preference", False, False)``
        * Fuzzy match → ``("preference", False, True)``  (spelling correction)
        * No match   → ``("custom_name", True, False)``  (new topic created)
        """
        name = name.strip().lower()
        if not name:
            name = "general"
            log.warning("Empty topic name, falling back to 'general'")

        # 1. Exact match
        if name in self._topics:
            return (name, False, False)

        # 2. Fuzzy match — difflib against all existing topic names
        best_name: str | None = None
        best_ratio = 0.0
        for existing in self._topics:
            ratio = difflib.SequenceMatcher(None, name, existing).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_name = existing

        if best_name and best_ratio >= _FUZZY_THRESHOLD:
            log.debug("Fuzzy matched topic '%s' → '%s' (ratio=%.2f)", name, best_name, best_ratio)
            return (best_name, False, True)

        # 3. No match — create new topic
        self.add(name)
        return (name, True, False)

    # ── helper for get_topic_list ─────────────────────────────

    def list_with_counts(self, fact_store: Any | None = None) -> list[dict[str, Any]]:
        """Return topic list with optional fact counts.

        Each entry: ``{"name": ..., "definition": ..., "fact_count": N}``
        """
        result = []
        for t in self._topics.values():
            entry = {"name": t.name, "definition": t.definition}
            if fact_store is not None:
                entry["fact_count"] = len(fact_store.get_by_topic(t.name, active=True))
            result.append(entry)
        return result
