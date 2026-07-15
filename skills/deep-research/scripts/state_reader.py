"""Bounded, read-only access to the active workspace's research state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_state() -> dict[str, Any]:
    path = Path.cwd() / "research_state.json"
    if not path.is_file():
        raise FileNotFoundError(f"research_state.json not found in {Path.cwd()}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("research_state.json must contain a JSON object")
    return state


def execute(command: str, args: list[str]) -> str:
    """Return a compact overview or only explicitly requested evidence IDs."""
    state = _load_state()
    evidence = state.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    if command == "overview":
        result = {
            "synthesis": state.get("synthesis", {}),
            "assets": state.get("assets", []),
            "meta": state.get("meta", {}),
            "evidence_count": len(evidence),
        }
    elif command == "evidence":
        requested_ids = list(dict.fromkeys(args))[:20]
        result = {
            "evidence": {
                evidence_id: evidence[evidence_id]
                for evidence_id in requested_ids
                if evidence_id in evidence
            },
            "missing_ids": [
                evidence_id for evidence_id in requested_ids
                if evidence_id not in evidence
            ],
        }
    else:
        raise ValueError("command must be 'overview' or 'evidence'")

    return json.dumps(result, ensure_ascii=False, indent=2)
