"""Evaluation metrics for deep research performance."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchMetrics:
    """Aggregated metrics for a batch of evaluation runs."""

    total_tasks: int = 0
    passed: int = 0
    failed: int = 0
    total_tokens: int = 0
    total_time_seconds: float = 0.0
    total_nodes: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_tasks if self.total_tasks else 0.0

    @property
    def avg_tokens_per_task(self) -> float:
        return self.total_tokens / self.total_tasks if self.total_tasks else 0.0

    @property
    def avg_time_per_task(self) -> float:
        return self.total_time_seconds / self.total_tasks if self.total_tasks else 0.0

    @property
    def avg_nodes_per_task(self) -> float:
        return self.total_nodes / self.total_tasks if self.total_tasks else 0.0

    def report(self) -> str:
        """Format metrics as a readable report."""
        lines = [
            "═" * 50,
            f"  Deep Research Evaluation Report",
            "═" * 50,
            f"  Tasks:     {self.passed}/{self.total_tasks} passed ({self.pass_rate:.1%})",
            f"  Tokens:    {self.total_tokens:,} total, {self.avg_tokens_per_task:,.0f} avg/task",
            f"  Time:      {self.total_time_seconds:.1f}s total, {self.avg_time_per_task:.1f}s avg/task",
            f"  Nodes:     {self.total_nodes} total, {self.avg_nodes_per_task:.1f} avg/task",
        ]
        if self.errors:
            lines.append(f"  Errors:    {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"    - {e}")
        lines.append("═" * 50)
        return "\n".join(lines)


def extract_node_count(dag_summary: str) -> int:
    """Count completed/failed nodes from a DAG execution summary."""
    count = 0
    for line in dag_summary.split("\n"):
        if line.strip().startswith("[") and "]" in line:
            count += 1
    return count
