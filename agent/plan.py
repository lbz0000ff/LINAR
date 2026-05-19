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


# ── DAG-based task plan (multi-agent / parallel execution) ────────────────


class DAGNodeStatus(str, Enum):
    """Status of a node in a DAG-based multi-agent task plan."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # waiting on dependency


@dataclass
class DAGNode:
    """A node in a DAG-based task plan.

    ``depends_on`` lists node IDs that must complete before this one
    can start — this is what enables parallel vs serial execution.
    """
    id: str
    description: str
    agent_hint: str = "any"          # e.g. "file_agent", "analysis_agent"
    depends_on: list[str] = field(default_factory=list)
    status: DAGNodeStatus = DAGNodeStatus.PENDING
    result: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "agent_hint": self.agent_hint,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
        }

    @staticmethod
    def from_dict(data: dict) -> DAGNode:
        """Create a DAGNode from a dictionary (inverse of to_dict)."""
        return DAGNode(
            id=data["id"],
            description=data["description"],
            agent_hint=data.get("agent_hint", "any"),
            depends_on=data.get("depends_on", []),
            status=DAGNodeStatus(data.get("status", "pending")),
            result=data.get("result", ""),
        )


@dataclass
class DAGPlan:
    """A DAG-based task plan enabling parallel sub-task execution.

    Compared to ``TaskPlan`` (linear, sequential), this model:
    - Explicitly tracks dependencies between sub-tasks
    - Supports parallel execution (tasks with no inter-dependency)
    - Provides topological ordering for scheduling
    - Is the foundation for multi-agent dispatching
    """
    goal: str
    nodes: dict[str, DAGNode] = field(default_factory=dict)

    def add_node(self, node: DAGNode) -> None:
        self.nodes[node.id] = node

    def get_ready(self) -> list[DAGNode]:
        """Return nodes whose dependencies are all completed (ready to run)."""
        return [
            n for n in self.nodes.values()
            if n.status == DAGNodeStatus.PENDING
            and all(
                self.nodes[d].status == DAGNodeStatus.COMPLETED
                for d in n.depends_on
            )
        ]

    def get_failed(self) -> list[DAGNode]:
        """Return all nodes that have failed."""
        return [n for n in self.nodes.values() if n.status == DAGNodeStatus.FAILED]

    def get_blocked(self) -> list[DAGNode]:
        """Return nodes blocked by a failed dependency."""
        return [
            n for n in self.nodes.values()
            if n.status == DAGNodeStatus.PENDING
            and any(
                self.nodes.get(d) is not None
                and self.nodes[d].status == DAGNodeStatus.FAILED
                for d in n.depends_on
            )
        ]

    def topological_sort(self) -> list[str]:
        """Return node IDs in topological order (respecting dependencies).

        Raises ``ValueError`` if a cycle is detected.
        """
        visited: set[str] = set()
        result: list[str] = []

        def _dfs(nid: str, path: set[str]) -> None:
            if nid in visited:
                return
            if nid in path:
                raise ValueError(f"Cycle detected involving node '{nid}'")
            path.add(nid)
            node = self.nodes[nid]
            for dep_id in node.depends_on:
                _dfs(dep_id, path)
            visited.add(nid)
            result.append(nid)

        for nid in self.nodes:
            if nid not in visited:
                _dfs(nid, set())
        return result

    @property
    def is_complete(self) -> bool:
        return all(
            n.status == DAGNodeStatus.COMPLETED
            for n in self.nodes.values()
        )

    def format_for_prompt(self) -> str:
        """Alias to format_dag — polymorphic use with tool_plan.py."""
        return self.format_dag()

    def format_dag(self) -> str:
        """Render the DAG for display / LLM prompt injection."""
        status_chars = {
            DAGNodeStatus.PENDING: "[ ]",
            DAGNodeStatus.IN_PROGRESS: "[>]",
            DAGNodeStatus.COMPLETED: "[x]",
            DAGNodeStatus.FAILED: "[!]",
            DAGNodeStatus.BLOCKED: "[-]",
        }
        lines = [
            "## DAG Task Plan",
            f"Goal: {self.goal}",
            "Nodes:",
        ]
        for nid in self.topological_sort():
            node = self.nodes[nid]
            marker = status_chars.get(node.status, "[?]")
            deps = f" (after: {', '.join(node.depends_on)})" if node.depends_on else ""
            agent = f" [{node.agent_hint}]"
            result_sfx = f" -> {node.result}" if node.result else ""
            lines.append(f"  {marker} {nid}{agent}: {node.description}{deps}{result_sfx}")
        ready = self.get_ready()
        if ready:
            lines.append(f"\nReady to execute: {', '.join(r.id for r in ready)}")
        else:
            lines.append("\nNo nodes ready (waiting for dependencies)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @staticmethod
    def from_dict(data: dict) -> DAGPlan:
        """Create a DAGPlan from a dictionary (inverse of to_dict)."""
        plan = DAGPlan(goal=data["goal"])
        for nid, node_data in data.get("nodes", {}).items():
            plan.add_node(DAGNode.from_dict(node_data))
        return plan
