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

    def add_event(
        self,
        type: str,
        uri: str = "",
        summary: str = "",
        tool_name: str = "",
        tool_call_id: str = "",
    ) -> None:
        """Append an event.

        *type* — ``"image"`` | ``"tool"`` | ``"file"``
        """
        self._events.append({
            "id": f"obs_{time.time_ns()}",
            "type": type,
            "uri": uri,
            "summary": summary,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "ts": time.time(),
            "attached": False,
        })
        log.debug("ObservationStore add: type=%s uri=%.80s", type, uri)

    def add_image(
        self,
        uri: str,
        tool_name: str = "",
        tool_call_id: str = "",
    ) -> None:
        """Shorthand for registering an image reference."""
        self.add_event(
            "image",
            uri=uri,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )

    def pop_attachable_image_events(self, max_n: int = 3) -> list[dict]:
        """Return the last *max_n* image events for this round.

        Images are returned in chronological order and the consumed
        entries stay in the event log for traceability.
        """
        pending = [
            event for event in self._events
            if event["type"] == "image" and not event.get("attached", False)
        ]
        selected = pending[-max_n:]
        for event in pending:
            event["attached"] = True
        if len(pending) > max_n:
            log.warning(
                "ObservationStore skipped %s older pending images; attaching the latest %s",
                len(pending) - max_n,
                max_n,
            )
        return [dict(event) for event in selected]

    def pop_attachable_images(self, max_n: int = 3) -> list[str]:
        """Backward-compatible URI-only view of attachable image events."""
        return [
            event["uri"]
            for event in self.pop_attachable_image_events(max_n=max_n)
        ]

    def has_images(self) -> bool:
        return any(
            event["type"] == "image" and not event.get("attached", False)
            for event in self._events
        )

    @property
    def events(self) -> list[dict]:
        return list(self._events)
