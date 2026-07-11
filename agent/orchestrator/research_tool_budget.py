"""Per-researcher web-tool budgets without changing shared tool behavior."""

from __future__ import annotations

from threading import Lock
from typing import Any


class ResearchToolBudget:
    """Delegate to one tool until its researcher-local call budget is spent."""

    def __init__(self, tool: Any, limit: int) -> None:
        self._tool = tool
        self._limit = max(0, int(limit))
        self._used = 0
        self._lock = Lock()
        self.name = tool.name
        self.description = (
            f"{tool.description} Research budget: at most {self._limit} calls; "
            "when exhausted, stop exploring and submit the best available evidence."
        )
        self.tool_schema = dict(tool.tool_schema)
        self.tool_schema["description"] = self.description

    @property
    def used(self) -> int:
        return self._used

    @property
    def limit(self) -> int:
        return self._limit

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._used >= self._limit:
                return {
                    "budget_exhausted": True,
                    "message": (
                        f"{self.name} budget exhausted ({self._used}/{self._limit}). "
                        "Do not retry this tool; synthesize existing evidence and call submit_output."
                    ),
                }
            self._used += 1
        return self._tool.execute(*args, **kwargs)
