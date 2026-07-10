import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from subagent import load_subagent
from tool.basic_tools.tool_plan import SubmitOutputTool


def _tool():
    tool = SubmitOutputTool()
    tool.agent_ref = SimpleNamespace()
    return tool


def test_submit_output_requires_generic_status_and_summary():
    tool = _tool()

    result = tool.execute(findings=[])

    assert isinstance(result, dict)
    assert "error" in result
    assert not hasattr(tool.agent_ref, "_submission")


def test_submit_output_records_generic_completed_result():
    tool = _tool()

    result = tool.execute(status="completed", summary="Processed the input files.")

    assert result == "SUBMITTED: Result recorded."
    assert tool.agent_ref._submission["status"] == "completed"
    assert tool.agent_ref._submission["summary"] == "Processed the input files."
    assert tool.agent_ref._submission["unresolved"] == []


def test_submit_output_preserves_research_fields_and_legacy_assets():
    tool = _tool()
    asset = {"file": "chart.mmd", "type": "diagram", "description": "Trend"}

    tool.execute(
        status="partial",
        summary="Found one supported claim.",
        unresolved=["A primary source is still missing."],
        findings=[{"text": "Claim", "source": "https://example.com"}],
        sources=["https://example.com"],
        assets=[asset],
    )

    submission = tool.agent_ref._submission
    assert submission["status"] == "partial"
    assert submission["assets"] == [asset]
    assert submission["artifacts"] == [asset]
    assert len(submission["findings"]) == 1


def test_installed_research_templates_use_generic_handoff_contract():
    for name in ("web_researcher", "analyst", "critic"):
        definition = load_subagent(name)
        assert definition is not None
        assert definition["finalization_hint"]
        prompt = definition["system_prompt"]
        assert "status" in prompt
        assert "summary" in prompt
