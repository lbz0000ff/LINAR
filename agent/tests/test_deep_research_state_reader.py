import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skill import SkillScriptTool


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "deep-research"
    / "scripts"
    / "state_reader.py"
)


def _tool() -> SkillScriptTool:
    return SkillScriptTool(
        name="deep-research_state_reader",
        description="Read selected deep research state",
        script_path=str(SCRIPT_PATH),
        skill_dir=str(SCRIPT_PATH.parent.parent),
    )


def test_overview_excludes_full_evidence_collection(tmp_path, monkeypatch):
    state = {
        "synthesis": {"summary": "Compact", "key_evidence_ids": ["node:e01"]},
        "evidence": {
            "node:e01": {"id": "node:e01", "text": "Selected"},
            "node:e02": {"id": "node:e02", "text": "Not selected"},
        },
        "assets": [],
        "meta": {"revision": 2},
    }
    (tmp_path / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = json.loads(_tool().execute(command="overview"))

    assert result["synthesis"] == state["synthesis"]
    assert result["evidence_count"] == 2
    assert "evidence" not in result


def test_evidence_returns_only_requested_ids(tmp_path, monkeypatch):
    state = {
        "synthesis": {},
        "evidence": {
            "node:e01": {"id": "node:e01", "text": "Selected"},
            "node:e02": {"id": "node:e02", "text": "Not selected"},
        },
        "assets": [],
        "meta": {},
    }
    (tmp_path / "research_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = json.loads(_tool().execute(command="evidence", args=["node:e01"]))

    assert list(result["evidence"]) == ["node:e01"]
