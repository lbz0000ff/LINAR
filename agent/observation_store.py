"""Lightweight observation store for tracking tool-discovered images.

Stores events as an append-only log.  The only operation used by the agent
loop is ``pop_attachable_images()`` which returns the most recent N image
URIs for attachment at the prompt-build boundary.

Future: ``query(intent, k=3)`` can be added without changing the schema.
"""

import time
import logging

log = logging.getLogger(__name__)


class ObservationStore:
    """Event log that tracks images discovered by tool executions.

    This is NOT a memory system — it is a structured queue consumed once
    per LLM round by ``_build_llm_messages()``.
    """

    def __init__(self):
        self._events: list[dict] = []

    def add_event(self, type: str, uri: str = "", summary: str = ""):
        """Append an event.

        *type* — ``"image"`` | ``"tool"`` | ``"file"``
        """
        self._events.append({
            "id": f"obs_{time.time_ns()}",
            "type": type,
            "uri": uri,
            "summary": summary,
            "ts": time.time(),
        })
        log.debug("ObservationStore add: type=%s uri=%.80s", type, uri)

    def add_image(self, uri: str):
        """Shorthand for registering an image reference."""
        self.add_event("image", uri=uri)

    def pop_attachable_images(self, max_n: int = 3) -> list[str]:
        """Return the last *max_n* image URIs for this round.

        Images are returned in chronological order and the consumed
        entries stay in the event log for traceability.
        """
        image_uris = [e["uri"] for e in self._events if e["type"] == "image"]
        return image_uris[-max_n:]

    def has_images(self) -> bool:
        return any(e["type"] == "image" for e in self._events)

    @property
    def events(self) -> list[dict]:
        return list(self._events)
