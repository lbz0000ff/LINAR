"""Regression tests for async-aware research retrieval budgets."""

from __future__ import annotations

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.research_tool_budget import ResearchToolBudget


class _AsyncTool:
    name = "mcp_search"
    description = "search"
    tool_schema = {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}},
    }

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: object) -> dict[str, object]:
        await asyncio.sleep(0)
        self.calls += 1
        return {"message": "async ok", "kwargs": kwargs}


class _SyncTool:
    name = "web_search"
    description = "search"
    tool_schema = {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}},
    }

    def execute(self, **kwargs: object) -> dict[str, object]:
        return {"message": "sync ok", "kwargs": kwargs}


def test_budget_awaits_async_tool_and_returns_its_result() -> None:
    async def scenario() -> None:
        underlying = _AsyncTool()
        budget = ResearchToolBudget(underlying, limit=1)

        assert inspect.iscoroutinefunction(budget.execute)
        result = await budget.execute(query="linar")

        assert result == {"message": "async ok", "kwargs": {"query": "linar"}}
        assert underlying.calls == 1

    asyncio.run(scenario())


def test_budget_runs_sync_tool_through_the_same_async_api() -> None:
    async def scenario() -> None:
        budget = ResearchToolBudget(_SyncTool(), limit=1)

        result = await budget.execute(query="linar")

        assert result == {"message": "sync ok", "kwargs": {"query": "linar"}}

    asyncio.run(scenario())


def test_budget_exhaustion_does_not_call_async_tool_again() -> None:
    async def scenario() -> None:
        underlying = _AsyncTool()
        budget = ResearchToolBudget(underlying, limit=1)

        await budget.execute(query="first")
        exhausted = await budget.execute(query="second")

        assert exhausted["budget_exhausted"] is True
        assert underlying.calls == 1

    asyncio.run(scenario())
