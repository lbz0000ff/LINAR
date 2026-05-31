"""Tool for LLM to check the status of pending async operations (promises).

A promise represents an async operation that was submitted and is still running
in the background. This tool lets the LLM check whether a promise has resolved
without blocking — it returns immediately with the current status.

Usage:
    resolve_promise promise_id="comfyui_abc123"
    resolve_promise  # list all pending promises
"""

from typing import Any
from .tool import Tool


class Tool_ResolvePromise(Tool):
    name: str = "resolve_promise"
    description: str = (
        "Check the status of an async operation. "
        "Only use when the user explicitly asks about a completed task. "
        "DO NOT call on running tasks — it will be rejected."
    )
    tool_schema: dict = {
        "name": "resolve_promise",
        "description": (
            "Check the status of an async operation. "
            "Only use when the user explicitly asks about a completed task. "
            "DO NOT call on running tasks — it will be rejected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "promise_id": {
                    "type": "string",
                    "description": "Optional promise ID to check. If omitted, lists all pending promises.",
                },
            },
        },
    }

    # Rejection counter: tracks how many times each promise has been rejected
    _rejected_count: dict[str, int] = {}

    # Set by terminal when creating the agent
    agent_ref: Any = None

    def execute(self, promise_id: str = "") -> str:
        agent = self.agent_ref
        if agent is None:
            return "Error: resolve_promise not connected to agent."

        if not promise_id:
            # List ALL promises (pending AND resolved)
            pending = {pid: info for pid, info in agent._promises.items() if info["status"] == "pending"}
            resolved = {pid: info for pid, info in agent._promises.items() if info["status"] == "resolved"}
            failed = {pid: info for pid, info in agent._promises.items() if info["status"] == "failed"}
            cancelled = {pid: info for pid, info in agent._promises.items() if info["status"] == "cancelled"}
            total = len(pending) + len(resolved) + len(failed) + len(cancelled)
            if total == 0:
                return "No promises registered."
            parts = []
            if pending:
                parts.append("Pending:")
                for pid, info in pending.items():
                    msg = info.get("message", "running...")
                    parts.append(f"  ⏳ {pid} — {msg}")
            if resolved:
                parts.append("Resolved:")
                for pid in sorted(resolved):
                    parts.append(f"  ✓ {pid}")
            if failed:
                parts.append("Failed:")
                for pid in sorted(failed):
                    parts.append(f"  ✗ {pid}")
            if cancelled:
                parts.append("Cancelled:")
                for pid in sorted(cancelled):
                    parts.append(f"  - {pid}")
            return "\n".join(parts)

        info = agent.get_promise(promise_id)
        if info is None:
            return f"Unknown promise: '{promise_id}'. Use resolve_promise() with no arguments to see all promises."

        if info["status"] == "pending":
            # Rejection + circuit breaker: prevent agent from polling
            count = self._rejected_count.get(promise_id, 0) + 1
            self._rejected_count[promise_id] = count
            if count >= 2:
                return (
                    f"[BLOCKED] resolve_promise for '{promise_id}' has been "
                    f"rejected 2 times. The task will complete automatically. "
                    f"DO NOT call again."
                )
            return (
                f"[REJECTED] Task '{promise_id}' is still running. "
                f"Do NOT check its status. "
                f"The result will be delivered automatically when ready."
            )
        elif info["status"] == "resolved":
            result = info.get("result", {})
            return f"✓ Promise '{promise_id}' resolved.\n{result}"
        else:
            return f"Promise '{promise_id}' status: {info['status']}"
