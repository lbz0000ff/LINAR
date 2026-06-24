"""Abstract benchmark base class — datasets plug in via this interface."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalTask:
    """A single evaluation task/question."""

    task_id: str
    question: str
    expected_answer: str  # ground truth
    level: str = "1"      # difficulty level
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of evaluating a single task."""

    task_id: str
    question: str
    expected_answer: str
    actual_answer: str
    passed: bool
    score: float = 0.0         # 0.0 - 1.0
    token_cost: int = 0
    time_seconds: float = 0.0
    node_count: int = 0
    error: str | None = None
    details: dict = field(default_factory=dict)


class Benchmark:
    """Abstract benchmark — override ``load()`` to provide tasks."""

    name: str = "benchmark"
    description: str = ""

    async def load(self) -> list[EvalTask]:
        """Load evaluation tasks. Override in subclasses."""
        raise NotImplementedError

    async def judge(self, task: EvalTask, actual: str) -> bool:
        """Judge whether *actual* matches the expected answer.

        Default: exact substring match. Override for LLM-as-Judge.
        """
        return task.expected_answer.lower() in actual.lower()
