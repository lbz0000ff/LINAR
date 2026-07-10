import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from subagent import load_subagent
from agent import Agent
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


class _NoopTool:
    name = "noop"

    def execute(self):
        return "ok"


class _FinalizingLLM:
    model = "fake"
    provider = "fake"

    def __init__(self):
        self.system_prompt = ""
        self.tools = {}
        self.calls = 0
        self.visible_tools = []

    async def _stream(self):
        self.calls += 1
        self.visible_tools.append(set(self.tools))
        if set(self.tools) == {"submit_output"}:
            name = "submit_output"
            arguments = '{"status":"partial","summary":"Preserved useful work.","unresolved":["One item"]}'
        else:
            name = "noop"
            arguments = "{}"
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None,
                reasoning_content=None,
                tool_calls=[SimpleNamespace(
                    index=0,
                    id=f"call-{self.calls}",
                    function=SimpleNamespace(name=name, arguments=arguments),
                )],
            ))]
        )

    def stream_response_messages(self, _messages):
        return self._stream()


class _TextLLM:
    model = "fake"
    provider = "fake"
    system_prompt = ""
    tools = {}

    async def _stream(self):
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content="done", reasoning_content=None, tool_calls=None,
            ))]
        )

    def stream_response_messages(self, _messages):
        return self._stream()


def _agent_config():
    return {
        "llm": {"api_key": "test", "base_url": "http://test.invalid/v1", "model": "fake"},
        "max_turns": 80,
        "chat_history": {},
        "permissions": {"default": "allow"},
        "permission_modes": {},
    }


def test_submission_dependent_agent_wraps_up_and_reserves_submit_call(monkeypatch):
    monkeypatch.setattr("agent.load_config", _agent_config)
    agent = Agent(tools={"noop": _NoopTool()}, memory_enabled=False)
    submit = SubmitOutputTool()
    submit.agent_ref = agent
    agent.tools["submit_output"] = submit
    agent.submission_required = True
    agent.submission_reserve = 1
    agent.wrap_up_calls = 1
    agent.max_llm_calls = 3
    agent.finalization_hint = "Preserve validated outputs."
    fake_llm = _FinalizingLLM()
    fake_llm.tools = dict(agent.tools)
    agent.llm = fake_llm
    events = []
    agent.emit = events.append

    asyncio.run(agent.process_with_llm())

    assert agent._submission["status"] == "partial"
    assert fake_llm.visible_tools[-1] == {"submit_output"}
    states = [event["data"]["state"] for event in events if event["type"] == "budget_state"]
    assert states == ["WRAP_UP", "SUBMIT_ONLY"]
    assert not any("LLM call limit reached" in msg.get("content", "") for msg in agent.chat_history)


def test_process_with_llm_preserves_injected_stop_event(monkeypatch):
    monkeypatch.setattr("agent.load_config", _agent_config)
    agent = Agent(tools={}, memory_enabled=False)
    agent.llm = _TextLLM()
    shared_event = asyncio.Event()
    agent.stop_event = shared_event

    asyncio.run(agent.process_with_llm())

    assert agent.stop_event is shared_event
