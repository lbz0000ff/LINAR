"""Bounded, node-scoped event forwarding for DAG subagents."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from logger import redact_sensitive

PREVIEW_LIMIT = 2000
FORWARDED_EVENT_TYPES = {
    "start",
    "done",
    "usage",
    "tool_call",
    "tool_result",
    "error",
    "complete",
    "budget_state",
}
TOKEN_METRIC_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "reasoning_tokens",
)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            secret_key = normalized not in TOKEN_METRIC_KEYS and any(
                marker in normalized
                for marker in (
                    "api_key", "apikey", "token", "secret", "password",
                    "authorization", "credential",
                )
            )
            if secret_key:
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive(value)
    return value


def _parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _preview(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return redact_sensitive(text)[:PREVIEW_LIMIT]


class SubagentTraceRelay:
    """Normalize subagent events and forward them through a parent emitter."""

    def __init__(
        self,
        parent_emit: Callable[[dict], None],
        node_id: str,
        agent_type: str | None,
    ) -> None:
        self._parent_emit = parent_emit
        self._node_id = node_id
        self._agent_type = agent_type
        self._sequence = 0
        self._pending_tools: dict[str, float] = {}
        self._pending_usage: dict[str, int] | None = None
        self._metrics: dict[str, Any] = {
            "llm_calls": 0,
            "tool_calls": 0,
            "search_calls": 0,
            "fetch_calls": 0,
            "findings_submitted": 0,
            "sources_submitted": 0,
            **{key: 0 for key in TOKEN_METRIC_KEYS},
        }

    def __call__(self, event: dict) -> None:
        event_type = str(event.get("type") or "")
        if event_type not in FORWARDED_EVENT_TYPES:
            return
        if event_type == "usage":
            self._pending_usage = self._normalize_usage(event.get("data") or {})
            return
        if event_type == "start":
            self._pending_usage = None
        elif event_type in {"done", "error", "complete"}:
            self._commit_pending_usage()

        self._sequence += 1
        payload = self._normalize(event_type, event)
        payload.update({
            "node_id": self._node_id,
            "agent_type": self._agent_type,
            "sequence": self._sequence,
            "timestamp": time.time(),
            "event_type": event_type,
            "metrics": self.snapshot_metrics(),
        })
        self._parent_emit({"type": "subagent_event", "data": payload})

    def snapshot_metrics(self) -> dict[str, Any]:
        return dict(self._metrics)

    def record_submission(self, submission: dict[str, Any]) -> None:
        """Update metrics after Tool_CreatePlan receives structured output."""
        self._metrics["findings_submitted"] = len(submission.get("findings") or [])
        self._metrics["sources_submitted"] = len(submission.get("sources") or [])

    def _normalize(self, event_type: str, event: dict) -> dict[str, Any]:
        if event_type == "start":
            self._metrics["llm_calls"] += 1
            return {"status": "running", "summary": {}, "detail": {}}
        if event_type == "tool_call":
            return self._normalize_tool_call(event)
        if event_type == "tool_result":
            return self._normalize_tool_result(event)
        if event_type == "error":
            return {
                "status": "error",
                "summary": {"message": _preview(event.get("data") or event.get("error") or "")},
                "detail": {},
            }
        if event_type == "budget_state":
            data = _redact_value(event.get("data") or {})
            return {"status": str(data.get("state") or "running"), "summary": data, "detail": {}}
        return {"status": "success", "summary": {}, "detail": {}}

    def _normalize_usage(self, data: Any) -> dict[str, int]:
        if not isinstance(data, dict):
            return {key: 0 for key in TOKEN_METRIC_KEYS}
        usage: dict[str, int] = {}
        for key in TOKEN_METRIC_KEYS:
            try:
                usage[key] = max(0, int(data.get(key) or 0))
            except (TypeError, ValueError):
                usage[key] = 0
        return usage

    def _commit_pending_usage(self) -> None:
        if self._pending_usage is None:
            return
        for key in TOKEN_METRIC_KEYS:
            self._metrics[key] += self._pending_usage[key]
        self._pending_usage = None

    def _normalize_tool_call(self, event: dict) -> dict[str, Any]:
        name = str(event.get("name") or "")
        tool_id = str(event.get("id") or "")
        arguments = _redact_value(_parse_json(event.get("arguments") or {}))
        self._metrics["tool_calls"] += 1
        if name == "web_search":
            self._metrics["search_calls"] += 1
        elif name == "web_fetch":
            self._metrics["fetch_calls"] += 1
        if tool_id:
            self._pending_tools[tool_id] = time.perf_counter()
        return {
            "tool_name": name,
            "tool_call_id": tool_id,
            "status": "running",
            "summary": {"arguments": arguments},
            "detail": {"arguments": arguments},
        }

    def _normalize_tool_result(self, event: dict) -> dict[str, Any]:
        name = str(event.get("name") or "")
        tool_id = str(event.get("id") or "")
        raw_result = event.get("raw_result", event.get("result"))
        result = _redact_value(_parse_json(raw_result))
        started = self._pending_tools.pop(tool_id, None)
        duration_ms = round((time.perf_counter() - started) * 1000) if started else None
        summary = self._tool_summary(name, result)
        detail: dict[str, Any] = {"preview": _preview(result)}
        if isinstance(result, dict) and result.get("content_file"):
            detail["content_file"] = result["content_file"]
        return {
            "tool_name": name,
            "tool_call_id": tool_id,
            "status": "error" if isinstance(result, dict) and result.get("error") else "success",
            "duration_ms": duration_ms,
            "summary": summary,
            "detail": detail,
        }

    def _tool_summary(self, name: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"preview": _preview(result)}
        if name == "web_search":
            results = result.get("results") or []
            return {
                "query": result.get("query", ""),
                "backend": result.get("backend", ""),
                "result_count": result.get("total", len(results)),
            }
        if name == "web_fetch":
            return {
                key: result.get(key)
                for key in ("url", "status_code", "content_length", "content_file", "truncated")
                if key in result
            }
        if name == "submit_output":
            findings = result.get("findings") or []
            sources = result.get("sources") or []
            self._metrics["findings_submitted"] = len(findings)
            self._metrics["sources_submitted"] = len(sources)
            return {
                "status": result.get("status"),
                "findings": len(findings),
                "sources": len(sources),
                "unresolved": len(result.get("unresolved") or []),
                "artifacts": len(result.get("artifacts") or result.get("assets") or []),
            }
        return {"preview": _preview(result)}
