"""Per-researcher web-tool budgets without changing shared tool behavior."""

from __future__ import annotations

from threading import Lock
from typing import Any


class ResearchToolBudgetCounter:
    """Thread-safe counter shared by equivalent retrieval tools."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.used = 0
        self.lock = Lock()

    def try_acquire(self) -> bool:
        with self.lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


class ResearchToolBudget:
    """Delegate to one tool until its researcher-local call budget is spent."""

    def __init__(
        self,
        tool: Any,
        limit: int,
        counter: ResearchToolBudgetCounter | None = None,
    ) -> None:
        self._tool = tool
        self._counter = counter or ResearchToolBudgetCounter(limit)
        self.name = tool.name
        self.description = (
            f"{tool.description} Shared research budget: at most {self._counter.limit} calls; "
            "when exhausted, stop exploring and submit the best available evidence."
        )
        self.tool_schema = dict(tool.tool_schema)
        self.tool_schema["description"] = self.description

    @property
    def used(self) -> int:
        return self._counter.used

    @property
    def limit(self) -> int:
        return self._counter.limit

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if not self._counter.try_acquire():
            return {
                "budget_exhausted": True,
                "message": (
                    f"{self.name} shared budget exhausted "
                    f"({self._counter.used}/{self._counter.limit}). "
                    "Do not retry another equivalent tool; synthesize existing evidence "
                    "and call submit_output."
                ),
            }
        return self._tool.execute(*args, **kwargs)
