"""Progressive access to the compact Deep Research working set."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from tool.basic_tools.tool import Tool


def _empty_state() -> dict[str, Any]:
    return {
        "evidence": {},
        "synthesis": {},
        "assets": [],
        "meta": {"revision": 0, "last_analyzed_revision": 0},
    }


class ResearchStateReader(Tool):
    """Expose small role-oriented views instead of the complete state file."""

    name: str = "read_research_state"
    description: str = (
        "Read a bounded view of the Deep Research working set. Start with overview, "
        "then request only new evidence or specific evidence IDs as needed."
    )
    tool_schema: dict = {
        "name": "read_research_state",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "view": {
                    "type": "string",
                    "enum": ["overview", "new_evidence", "evidence_by_id"],
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs to expand; at most 20 unique IDs are returned",
                },
                "cursor": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["view"],
        },
    }
    workspace_root: str
    agent_type: str

    def _load(self) -> dict[str, Any]:
        path = os.path.join(self.workspace_root, "research_state.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return _empty_state()
        if not isinstance(state, dict) or not isinstance(state.get("evidence"), dict):
            return _empty_state()
        return state

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        state = self._load()
        evidence = state.get("evidence", {})
        synthesis = state.get("synthesis", {})
        meta = state.get("meta", {})
        last_analyzed = int(meta.get("last_analyzed_revision", 0))
        new_items = [
            item for item in evidence.values()
            if isinstance(item, dict) and int(item.get("revision", 0)) > last_analyzed
        ]
        view = kwargs.get("view")

        if view == "overview":
            return {
                "synthesis": synthesis,
                "meta": meta,
                "evidence_count": len(evidence),
                "new_evidence_count": len(new_items),
                "asset_count": len(state.get("assets", [])),
            }

        if view == "new_evidence":
            cursor = max(0, int(kwargs.get("cursor") or 0))
            limit = min(20, max(1, int(kwargs.get("limit") or 10)))
            items = new_items[cursor:cursor + limit]
            next_cursor = cursor + limit if cursor + limit < len(new_items) else None
            return {"items": items, "next_cursor": next_cursor, "total": len(new_items)}

        if view == "evidence_by_id":
            requested: list[str] = []
            for evidence_id in kwargs.get("evidence_ids") or []:
                if evidence_id not in requested:
                    requested.append(evidence_id)
                if len(requested) == 20:
                    break
            return {
                "items": [evidence[eid] for eid in requested if eid in evidence],
                "requested_limit": 20,
            }

        return {"error": f"Unknown research-state view: {view}"}


class ResearchStateFileGuard:
    """Delegate ordinary file reads while blocking bulk research-state reads."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = tool.name
        self.description = tool.description
        self.tool_schema = copy.deepcopy(tool.tool_schema)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        file_path = str(kwargs.get("file_path") or "")
        if os.path.basename(file_path).lower() == "research_state.json":
            return {
                "progressive_disclosure_required": True,
                "error": (
                    "Bulk reads of research_state.json are disabled. "
                    "Use read_research_state with the overview view first."
                ),
            }
        return self._tool.execute(*args, **kwargs)
