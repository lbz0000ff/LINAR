"""Topic registry — lightweight topic definitions.

Topics are flat categories with a one-sentence definition that is
generated once and frozen.  They form a tree (each fact belongs to
exactly one topic), never a graph.

The initial topic set is hard-coded as a fallback; once persisted,
topics live in ``topics.json`` and can grow over time.
"""

from __future__ import annotations

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
        "name": "general",
        "definition": "general information that does not fit any other specific topic",
    },
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
        "description": "the agent's own behavior patterns, methodology, and long-term experience",
    },
    {
        "name": "workflow",
        "definition": "workflow preferences and toolchain configuration",
    },
]

# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


@dataclass
class Topic:
    """A flat semantic category for grouping facts."""

    name: str
    definition: str
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

    If no persisted file exists, creates one with the seed topics.
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

        # Seed on first run
        log.info("Seeding default topics")
        for sd in _SEED_TOPICS:
            t = Topic(name=sd["name"], definition=sd.get("definition", ""))
            self._topics[t.name] = t
        self._save()

    def save(self) -> None:
        """Persist topics to JSON."""
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

    def add(self, name: str, definition: str) -> Topic:
        """Add a new topic. Overwrites if *name* already exists."""
        t = Topic(name=name, definition=definition)
        self._topics[name] = t
        self._save()
        log.info("Added topic '%s': %s", name, definition)
        return t

    def get_definitions_text(self) -> str:
        """Return a formatted string of all topic definitions (for LLM prompts)."""
        lines = ["Available topics:"]
        for t in self._topics.values():
            lines.append(f"  - {t.name}: {t.definition}")
        return "\n".join(lines)

    def __contains__(self, name: str) -> bool:
        return name in self._topics
