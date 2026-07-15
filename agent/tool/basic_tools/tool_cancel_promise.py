"""[DISCARDED]Tool for cancelling a previously registered watch task.

Usage:
    cancel_promise(promise_id="img-1")
"""

from typing import Any
from .tool import Tool


class Tool_CancelPromise(Tool):
    name: str = "cancel_promise"
    description: str = (
        "Cancel a previously registered watch task. "
        "The background monitor thread will stop, and the promise status "
        "will be set to 'cancelled'. "
        "Use this when a long-running task is no longer needed "
        "(e.g. user changed their mind about an image generation)."
    )
    tool_schema: dict = {
        "name": "cancel_promise",
        "description": (
            "Cancel a previously registered watch task. "
            "The background monitor thread will stop, and the promise status "
            "will be set to 'cancelled'. "
            "Use when a long-running task is no longer needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "promise_id": {
                    "type": "string",
                    "description": "The promise ID returned by watch().",
                },
            },
            "required": ["promise_id"],
        },
    }

    agent_ref: Any = None

    def execute(self, promise_id: str = "") -> str:
        agent = self.agent_ref
        if agent is None:
            return "Error: cancel_promise not connected to agent."

        info = agent.get_promise(promise_id)
        if info is None:
            return f"Error: unknown promise '{promise_id}'."
        if info["status"] == "cancelled":
            return f"Promise '{promise_id}' is already cancelled."
        if info["status"] == "resolved":
            return f"Promise '{promise_id}' is already resolved — cannot cancel."

        ok = agent.cancel_promise(promise_id)
        if ok:
            return f"Cancelled promise '{promise_id}'. Background monitor will stop."
        return f"Failed to cancel promise '{promise_id}'."
