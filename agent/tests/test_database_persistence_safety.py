from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

import database as db
from hooks import HookContext, HookEvent
from hooks_builtin import persist_agent_response, persist_tool_result


@pytest.mark.parametrize(
    ("handler", "context_kwargs"),
    [
        (
            persist_agent_response,
            {"event": HookEvent.AGENT_RESPONSE, "agent_text": "answer"},
        ),
        (
            persist_tool_result,
            {
                "event": HookEvent.POST_TOOL_USE,
                "tool_name": "web_search",
                "tool_result": "result",
            },
        ),
    ],
)
def test_persistence_hooks_skip_agents_without_sessions(
    handler, context_kwargs, monkeypatch
) -> None:
    def unexpected_save(*_args, **_kwargs) -> None:
        raise AssertionError("sessionless agent attempted database persistence")

    monkeypatch.setattr(db, "save_message", unexpected_save)
    agent = SimpleNamespace(session_id=None, _conversation_round=1)
    context = HookContext(agent=agent, timestamp=0.0, **context_kwargs)

    asyncio.run(handler(context))


def test_save_message_rolls_back_failed_transaction(monkeypatch) -> None:
    class FailingConnection:
        def __init__(self) -> None:
            self.rolled_back = False

        def execute(self, *_args, **_kwargs):
            raise sqlite3.IntegrityError("invalid session")

        def rollback(self) -> None:
            self.rolled_back = True

    connection = FailingConnection()
    monkeypatch.setattr(db, "_get_connection", lambda: connection)

    with pytest.raises(sqlite3.IntegrityError, match="invalid session"):
        db.save_message(None, "agent", "answer")

    assert connection.rolled_back is True
