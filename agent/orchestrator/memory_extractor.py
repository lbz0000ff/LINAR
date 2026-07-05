"""Post-round memory extraction with error isolation."""

from __future__ import annotations

import asyncio

from logger import get_logger as _get_logger

log = _get_logger(__name__)


class MemoryExtractor:
    """Non-fatal memory extraction wrapper.

    Runs after each conversation round.  Failures are logged and
    silently swallowed — never raised to the caller.
    """

    def __init__(self, agent) -> None:
        self._agent = agent

    async def try_extract(self) -> None:
        """Extract memory facts if enabled and session exists."""
        cfg = getattr(self._agent, "cfg", {})
        if not cfg.get("memory", {}).get("enabled", True):
            return

        session_id = self._agent.session_id
        if not session_id:
            return

        try:
            from memory.fact import FactStore
            from memory.topic import TopicRegistry
            from memory.extractor import try_extract as _try_extract
            import database as db

            messages = db.get_session_messages(session_id)
            current_round = self._agent._conversation_round

            store = FactStore()
            tr = TopicRegistry()
            llm_cfg = cfg.get("aux") or cfg.get("llm", {})

            # Read extraction interval from config (default 6)
            interval = cfg.get("memory", {}).get("extraction", {}).get("interval", 6)

            await asyncio.to_thread(
                _try_extract,
                store, tr, messages,
                session_id, current_round, llm_cfg, interval,
            )
        except Exception as e:
            log.warning("Memory extraction skipped: %s", e)
