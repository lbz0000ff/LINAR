"""[DISCARDED]Tool for monitoring long-running tasks via background threads.

Usage (LLM-facing):
    watch(promise_id="img-1", check_type="ws",
          job_id="abc123", poll_url="ws://localhost:8188/ws")
"""

import time
import json
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from .tool import Tool

# Module-level executor — not a Pydantic field (cannot deepcopy ThreadPoolExecutor)
_WATCH_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=4)


def shutdown_watch_executor():
    """Call on agent shutdown to stop background monitor threads."""
    _WATCH_EXECUTOR.shutdown(wait=False)


class Tool_Watch(Tool):
    name: str = "watch"
    description: str = (
        "Register a long-running job for background monitoring. "
        "After starting a task that returns a job_id / prompt_id, call "
        "this tool to have the system watch it for you, then use "
        "resolve_promise(promise_id) to get the result. "
        "Do NOT poll manually. "
        "For check_type: prefer 'ws' if the service offers a WebSocket "
        "endpoint (lowest latency); fall back to 'http_poll' otherwise. "
        "Use cancel_promise(promise_id) if the task is no longer needed."
    )
    tool_schema: dict = {
        "name": "watch",
        "description": (
            "Register a long-running job for background monitoring. "
            "After starting a task that returns a job_id / prompt_id, call "
            "this tool to have the system watch it for you, then use "
            "resolve_promise(promise_id) to get the result. "
            "Do NOT poll manually. "
            "For check_type: prefer 'ws' if the service offers a WebSocket "
            "endpoint (lowest latency); fall back to 'http_poll' otherwise. "
            "Use cancel_promise(promise_id) if the task is no longer needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "promise_id": {
                    "type": "string",
                    "description": "Unique ID for this promise (e.g. 'img-cat-1').",
                },
                "check_type": {
                    "type": "string",
                    "enum": ["ws", "file", "process", "http_poll"],
                    "description": (
                        "How to detect completion:\n"
                        "  ws        - WebSocket URL in poll_url, wait for completion message\n"
                        "  file      - job_id is the file path; wait for it to exist\n"
                        "  process   - job_id is a PID; wait for the process to exit\n"
                        "  http_poll - poll poll_url every interval seconds"
                    ),
                },
                "job_id": {
                    "type": "string",
                    "description": "Job identifier (prompt_id, file path, PID, etc.)",
                },
                "poll_url": {
                    "type": "string",
                    "description": "URL for ws / http_poll checks",
                },
                "interval": {
                    "type": "integer",
                    "description": "Polling interval in seconds (default 30, used only for http_poll)",
                    "default": 30,
                },
            },
            "required": ["promise_id", "check_type", "job_id"],
        },
    }

    agent_ref: Any = None

    def execute(self, promise_id: str = "", check_type: str = "",
                job_id: str = "", poll_url: str = "",
                interval: int = 30) -> str:
        agent = self.agent_ref
        if agent is None:
            return "Error: watch not connected to agent."

        # Validate
        if agent.get_promise(promise_id):
            return f"Error: promise '{promise_id}' already exists."

        if check_type not in ("ws", "file", "process", "http_poll"):
            return f"Error: unknown check_type '{check_type}'. Use ws/file/process/http_poll."

        # Register promise
        agent.create_promise(promise_id, meta={
            "start_time": time.time(),
            "check_type": check_type,
            "job_id": job_id,
            "poll_url": poll_url,
            "interval": interval,
        })

        # Start background monitor
        _WATCH_EXECUTOR.submit(_monitor, agent, promise_id,
                               check_type, job_id, poll_url, interval)

        return json.dumps({
            "promise_id": promise_id,
            "status": "monitoring",
            "check_type": check_type,
            "message": f"Watching {check_type} task '{job_id}'. "
                       f"Use resolve_promise('{promise_id}') to check result.",
        }, ensure_ascii=False)

    # -----------------------------------------------------------------
    # Background monitor
    # -----------------------------------------------------------------


def _monitor(agent, promise_id: str, check_type: str,
             job_id: str, poll_url: str, interval: int):
    """Background thread: periodically check job status until done/failed/cancelled."""
    failures = 0
    while True:
        try:
            info = agent.get_promise(promise_id)
            if info is None or info["status"] in ("cancelled", "failed", "resolved"):
                return  # Thread done
        except Exception:
            return

        try:
            result = _check_once(check_type, job_id, poll_url)
        except Exception as e:
            result = {"done": False, "error": str(e)}

        if result.get("done"):
            agent.resolve_promise(promise_id, result.get("data", {}))
            return

        if result.get("external_cancel"):
            agent.fail_promise(promise_id, result["error"])
            return

        if result.get("error"):
            failures += 1
            if failures >= 3:
                agent.fail_promise(promise_id, result["error"])
                return
            time.sleep(interval)
            continue

        failures = 0  # Successful check, reset failure count
        time.sleep(interval)


def _check_once(check_type: str, job_id: str, poll_url: str = "") -> dict:
    """Single completion check. Returns {"done": bool, "data": ..., "error": ...}."""
    import os
    import subprocess

    if check_type == "http_poll" and poll_url:
        import requests
        try:
            resp = requests.get(poll_url, timeout=10)
            data = resp.json()
            # 1. 显式状态字段匹配
            status = data.get("status")
            if isinstance(status, str):
                status_lower = status.lower()
                if status_lower in ("completed", "succeeded", "done", "success", "complete", "finished"):
                    return {"done": True, "data": data}
                if status_lower == "cancelled":
                    return {"external_cancel": True, "error": f"Job {job_id} externally cancelled"}
                if status_lower in ("running", "queued", "pending", "processing"):
                    return {"done": False}
            if data.get("done") or data.get("finished"):
                return {"done": True, "data": data}

            # 2. 通用启发式：非空响应 = 完成
            #    兼容 ComfyUI /history/{id} 等返回 {id: {...history...}} 的 API
            if data:
                # 如果 job_id 在响应中作为 key 存在，通常是完成状态
                if job_id in data:
                    return {"done": True, "data": data}
                return {"done": True, "data": data}
            return {"done": False}
        except Exception as e:
            return {"error": str(e)}

    if check_type == "file":
        exists = os.path.exists(job_id)
        if exists:
            return {"done": True, "data": {"file": job_id}}
        return {"done": False}

    if check_type == "process":
        # Check if PID is alive
        try:
            pid = int(job_id)
            if os.name == "nt":
                # Windows
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                alive = str(pid) in result.stdout
            else:
                try:
                    os.kill(pid, 0)
                    alive = True
                except (OSError, ProcessLookupError):
                    alive = False
            if not alive:
                return {"done": True, "data": {"pid": pid, "status": "exited"}}
            return {"done": False}
        except (ValueError, subprocess.TimeoutExpired):
            return {"error": f"Failed to check process {job_id}"}

    if check_type == "ws":
        # WebSocket check — in v1, falls back to http_poll
        # Future: use websockets library for blocking read
        if poll_url and poll_url.startswith("http"):
            return _check_once("http_poll", job_id, poll_url)
        return {"error": "ws check requires poll_url"}

    return {"error": f"Unknown check_type: {check_type}"}
