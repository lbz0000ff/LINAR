import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.research_state_access import ResearchStateFileGuard, ResearchStateReader


class _DelegateReader:
    name = "read_file"
    description = "Read a file"
    tool_schema = {"name": "read_file", "parameters": {"type": "object", "properties": {}}}

    def execute(self, **kwargs):
        return {"delegated": kwargs["file_path"]}


def _write_state(tmp_path):
    state = {
        "evidence": {
            "wave1:e01": {"id": "wave1:e01", "text": "Old", "revision": 1},
            "wave2:e01": {"id": "wave2:e01", "text": "New 1", "revision": 2},
            "wave2:e02": {"id": "wave2:e02", "text": "New 2", "revision": 2},
        },
        "synthesis": {
            "summary": "Current synthesis",
            "key_evidence_ids": ["wave1:e01"],
            "critical_gaps": ["Gap"],
        },
        "assets": [],
        "meta": {"revision": 2, "last_analyzed_revision": 1},
    }
    (tmp_path / "research_state.json").write_text(
        json.dumps(state), encoding="utf-8",
    )


def test_overview_discloses_synthesis_and_counts_without_evidence_text(tmp_path):
    _write_state(tmp_path)
    reader = ResearchStateReader(workspace_root=str(tmp_path), agent_type="analyst")

    result = reader.execute(view="overview")

    assert result["synthesis"]["summary"] == "Current synthesis"
    assert result["evidence_count"] == 3
    assert result["new_evidence_count"] == 2
    assert "evidence" not in result


def test_new_evidence_is_revision_filtered_and_paginated(tmp_path):
    _write_state(tmp_path)
    reader = ResearchStateReader(workspace_root=str(tmp_path), agent_type="analyst")

    first = reader.execute(view="new_evidence", cursor=0, limit=1)
    second = reader.execute(view="new_evidence", cursor=1, limit=1)

    assert [item["id"] for item in first["items"]] == ["wave2:e01"]
    assert first["next_cursor"] == 1
    assert [item["id"] for item in second["items"]] == ["wave2:e02"]
    assert second["next_cursor"] is None


def test_evidence_by_id_is_bounded_and_ignores_unknown_ids(tmp_path):
    _write_state(tmp_path)
    reader = ResearchStateReader(workspace_root=str(tmp_path), agent_type="critic")

    result = reader.execute(
        view="evidence_by_id",
        evidence_ids=["wave1:e01", "missing"] + ["wave2:e01"] * 30,
    )

    assert [item["id"] for item in result["items"]] == ["wave1:e01", "wave2:e01"]
    assert result["requested_limit"] == 20


def test_missing_or_malformed_state_returns_empty_overview(tmp_path):
    reader = ResearchStateReader(workspace_root=str(tmp_path), agent_type="analyst")
    assert reader.execute(view="overview")["evidence_count"] == 0

    (tmp_path / "research_state.json").write_text("{bad", encoding="utf-8")
    assert reader.execute(view="overview")["evidence_count"] == 0


def test_file_guard_blocks_bulk_state_read_but_delegates_other_files(tmp_path):
    guard = ResearchStateFileGuard(_DelegateReader())

    blocked = guard.execute(file_path=str(tmp_path / "research_state.json"))
    allowed = guard.execute(file_path=str(tmp_path / "notes.md"))

    assert blocked["progressive_disclosure_required"] is True
    assert allowed == {"delegated": str(tmp_path / "notes.md")}
