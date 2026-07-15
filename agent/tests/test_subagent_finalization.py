import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from subagent import load_subagent
from agent import Agent
from tool.basic_tools.tool_plan import SubmitOutputTool, Tool_CreatePlan


def _tool(agent_type=None):
    tool = SubmitOutputTool(agent_type=agent_type)
    tool.agent_ref = SimpleNamespace()
    return tool


def test_submit_output_requires_generic_status_and_summary():
    tool = _tool()

    properties = tool.tool_schema["parameters"]["properties"]
    assert {"status", "summary", "unresolved", "artifacts", "error"} <= set(properties)

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
    tool = _tool("web_researcher")
    asset = {"file": "chart.mmd", "type": "diagram", "description": "Trend"}

    tool.execute(
        status="partial",
        summary="Found one supported claim.",
        unresolved=["A primary source is still missing."],
        findings=[{"text": "Claim", "source": "https://example.com"}],
        assets=[asset],
    )

    submission = tool.agent_ref._submission
    assert submission["status"] == "partial"
    assert submission["assets"] == [asset]
    assert submission["artifacts"] == [asset]
    assert len(submission["findings"]) == 1


def test_submit_output_schema_is_minimal_for_each_research_role():
    common = {"status", "summary", "unresolved", "artifacts", "error"}

    researcher = set(_tool("web_researcher").tool_schema["parameters"]["properties"])
    analyst = set(_tool("analyst").tool_schema["parameters"]["properties"])
    critic = set(_tool("critic").tool_schema["parameters"]["properties"])
    generic = set(_tool().tool_schema["parameters"]["properties"])

    assert researcher == common | {"findings", "gaps"}
    assert analyst == common | {
        "contradictions", "critical_gaps", "coverage_score",
        "next_wave_suggestions", "key_evidence_ids", "remove_evidence_ids",
    }
    assert critic == common | {
        "verdicts", "critical_gaps", "overall_assessment", "remove_evidence_ids",
    }
    assert generic == common


def test_submit_output_discards_fields_outside_active_role_contract():
    tool = _tool("web_researcher")

    tool.execute(
        status="completed",
        summary="Selected evidence.",
        findings=[{"text": "Claim", "source": "https://example.com"}],
        next_wave_suggestions=[{"direction": "irrelevant"}],
        verdicts=[{"finding": "irrelevant"}],
    )

    assert "next_wave_suggestions" not in tool.agent_ref._submission
    assert "verdicts" not in tool.agent_ref._submission


def test_installed_research_templates_use_generic_handoff_contract():
    for name in ("web_researcher", "analyst", "critic"):
        definition = load_subagent(name)
        assert definition is not None
        assert definition["finalization_hint"]
        prompt = definition["system_prompt"]
        assert "status" in prompt
        assert "summary" in prompt
        assert "get_date" not in definition["allowed_tools"]
        assert "get_time" not in definition["allowed_tools"]


def test_research_templates_describe_selection_and_progressive_state_access():
    researcher = load_subagent("web_researcher")
    analyst = load_subagent("analyst")
    critic = load_subagent("critic")

    assert "12" in researcher["system_prompt"]
    assert "3" in researcher["system_prompt"]
    assert "search history" in researcher["system_prompt"].lower()
    assert "read_research_state" in analyst["allowed_tools"]
    assert "overview" in analyst["system_prompt"]
    assert "new_evidence" in analyst["system_prompt"]
    assert "read `research_state.json`" not in analyst["system_prompt"]
    assert "read_research_state" in critic["allowed_tools"]
    assert "evidence_by_id" in critic["system_prompt"]
    assert "read `research_state.json`" not in critic["system_prompt"]


def test_deep_research_skill_uses_compact_state_views():
    skill_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "skills", "deep-research", "SKILL.md",
    )
    text = open(skill_path, encoding="utf-8").read()

    assert "synthesis" in text
    assert "key_evidence_ids" in text
    assert "Read `research_state.json` for all findings" not in text


def test_deep_research_skill_preserves_user_intent_with_definition_of_done():
    skill_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "skills", "deep-research", "SKILL.md",
    )
    text = open(skill_path, encoding="utf-8").read()

    assert "Definition of Done" in text
    assert "explicit quantities" in text
    assert "named entities" in text
    assert "adds depth" in text
    assert "check the report against every item" in text


def test_predecessor_context_preserves_generic_handoff_before_large_extensions():
    result = '{"status":"partial","summary":"usable","unresolved":["gap"],"artifacts":[{"path":"out.md"}],"findings":[' + ('{"text":"x"},' * 1000).rstrip(',') + ']}'

    context = Tool_CreatePlan._format_predecessor_context(result)

    parsed = __import__("json").loads(context)
    assert parsed["status"] == "partial"
    assert parsed["summary"] == "usable"
    assert parsed["unresolved"] == ["gap"]
    assert parsed["artifacts"] == [{"path": "out.md"}]
    assert "findings" not in parsed


def test_checkpoint_preserves_bounded_agent_output_and_written_artifacts():
    fake = SimpleNamespace(chat_history=[
        {"role": "agent", "content": "useful partial analysis"},
        {"role": "tool", "name": "write_file", "arguments": '{"file_path":"report.md"}', "result": "ok"},
    ])

    checkpoint = Tool_CreatePlan._build_checkpoint(fake, "node-a")

    assert checkpoint["last_agent_output"] == "useful partial analysis"
    assert checkpoint["artifacts"] == [{"path": "report.md", "type": "file"}]


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


class _MalformedArgumentsLLM:
    model = "fake"
    provider = "fake"
    system_prompt = ""
    tools = {}

    def __init__(self):
        self.calls = 0

    async def _stream(self):
        self.calls += 1
        if self.calls == 1:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=None,
                    reasoning_content=None,
                    tool_calls=[SimpleNamespace(
                        index=0,
                        id="bad-date",
                        function=SimpleNamespace(
                            name="noop",
                            arguments='{"date": 2025-04-03T00:00:00.000Z}',
                        ),
                    )],
                ))]
            )
        else:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="recovered", reasoning_content=None, tool_calls=None,
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


def test_malformed_tool_arguments_are_returned_to_model_without_crashing(monkeypatch):
    monkeypatch.setattr("agent.load_config", _agent_config)
    agent = Agent(tools={"noop": _NoopTool()}, memory_enabled=False)
    agent.llm = _MalformedArgumentsLLM()
    agent.emit = lambda _event: None

    asyncio.run(agent.process_with_llm())

    tool_messages = [m for m in agent.chat_history if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "invalid JSON" in tool_messages[0]["result"]
    assert agent.llm.calls == 2
