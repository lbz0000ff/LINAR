"""Task decomposition data structures."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    """A single step in the task plan."""

    id: str
    description: str
    status: SubTaskStatus = SubTaskStatus.PENDING
    assigned_to: str = "self"  # extension point: future agent/skill name
    result: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "result": self.result,
        }


@dataclass
class TaskPlan:
    """Structured decomposition of a user goal into sub-tasks."""

    goal: str
    sub_tasks: list[SubTask] = field(default_factory=list)
    current_index: int = 0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def current_subtask(self) -> SubTask | None:
        """Return the currently active sub-task, or None if plan is complete."""
        if 0 <= self.current_index < len(self.sub_tasks):
            return self.sub_tasks[self.current_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.sub_tasks)

    def advance(self) -> SubTask | None:
        """Mark current sub-task as completed and move to the next.

        Returns the next sub-task (now IN_PROGRESS), or None if plan is complete.
        """
        current = self.current_subtask
        if current is not None:
            current.status = SubTaskStatus.COMPLETED
        self.current_index += 1
        nxt = self.current_subtask
        if nxt is not None:
            nxt.status = SubTaskStatus.IN_PROGRESS
        return nxt

    def fail_current(self, reason: str = "") -> SubTask | None:
        """Mark current sub-task as failed and advance to the next.

        Returns the next sub-task, or None if plan is complete.
        """
        current = self.current_subtask
        if current is not None:
            current.status = SubTaskStatus.FAILED
            if reason:
                current.result = reason
        self.current_index += 1
        nxt = self.current_subtask
        if nxt is not None:
            nxt.status = SubTaskStatus.IN_PROGRESS
        return nxt

    def format_for_prompt(self) -> str:
        """Render the plan as a structured text block for chat_history."""
        status_chars = {
            SubTaskStatus.PENDING: "[ ]",
            SubTaskStatus.IN_PROGRESS: "[>]",
            SubTaskStatus.COMPLETED: "[x]",
            SubTaskStatus.FAILED: "[!]",
        }
        lines = [
            "## Current Task Plan",
            f"Goal: {self.goal}",
            "Sub-tasks:",
        ]
        for st in self.sub_tasks:
            marker = status_chars.get(st.status, "[?]")
            result_suffix = f" -> {st.result}" if st.result else ""
            lines.append(f"  {marker} {st.id}: {st.description}{result_suffix}")
        lines.append(f"\nProgress: {self.current_index}/{len(self.sub_tasks)} completed")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "sub_tasks": [st.to_dict() for st in self.sub_tasks],
            "current_index": self.current_index,
            "is_complete": self.is_complete,
        }
