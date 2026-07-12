import asyncio
import json
import os
import sys
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool.basic_tools.tool_plan import Tool_CreatePlan


class _FakeParentAgent:
    def __init__(self):
        self.stop_event = SimpleNamespace(is_set=lambda: False)
        self._workspace_root = None
        self.cfg = {"sub_agent_max_llm_calls": 27}
        self.events = []

    def emit(self, event):
        self.events.append(event)


class _FakeSubAgent:
    def __init__(self):
        self.max_llm_calls = None
        self.tools = {}
        self.llm = SimpleNamespace(tools=self.tools)
        self.chat_history = []
        self.emit = lambda _event: None

    async def add_user_message(self, text):
        self.chat_history.append({"role": "user", "content": text})

    async def process_with_llm(self):
        self.emit({"type": "start"})
        self.emit({
            "type": "tool_call",
            "name": "web_search",
            "id": "search-1",
            "arguments": '{"query":"demo"}',
        })
        self.emit({
            "type": "tool_result",
            "name": "web_search",
            "id": "search-1",
            "result": {"query": "demo", "results": [], "total": 0},
        })
        self.chat_history.append({"role": "agent", "content": "done"})


class _FailingSubAgent(_FakeSubAgent):
    async def process_with_llm(self):
        raise RuntimeError("research node failed")


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"Fake {name} tool"
        self.calls = 0
        self.tool_schema = {"name": name, "parameters": {"type": "object", "properties": {}}}

    def execute(self, **_kwargs):
        self.calls += 1
        return {"message": f"{self.name} ok"}


def test_create_plan_uses_configured_sub_agent_llm_limit(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        sub_agent = _FakeSubAgent()
        created.append(sub_agent)
        return sub_agent

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)

    tool = Tool_CreatePlan()
    tool.agent_ref = _FakeParentAgent()

    result = asyncio.run(
        tool.execute(
            goal="demo",
            sub_tasks=[
                {
                    "id": "one",
                    "description": "Do one small task",
                    "depends_on": [],
                }
            ],
        )
    )

    assert "DAG Execution Complete" in result
    assert len(created) == 1
    assert created[0].max_llm_calls == 27
    assert created[0].submission_required is True
    assert created[0].submission_reserve == 2
    assert created[0].wrap_up_calls == 2


def test_create_plan_forwards_node_scoped_subagent_events(monkeypatch):
    def fake_create_agent(**_kwargs):
        return _FakeSubAgent()

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)

    tool = Tool_CreatePlan()
    parent = _FakeParentAgent()
    tool.agent_ref = parent

    asyncio.run(
        tool.execute(
            goal="parallel demo",
            sub_tasks=[
                {"id": "one", "description": "First", "depends_on": []},
                {"id": "two", "description": "Second", "depends_on": []},
            ],
        )
    )

    traces = [event["data"] for event in parent.events if event["type"] == "subagent_event"]
    assert {trace["node_id"] for trace in traces} == {"one", "two"}
    for node_id in ("one", "two"):
        sequences = [trace["sequence"] for trace in traces if trace["node_id"] == node_id]
        assert sequences == [1, 2, 3]

    completed = [event["data"] for event in parent.events if event["type"] == "dag_node_complete"]
    assert {event["status"] for event in completed} == {"CHECKPOINTED"}
    assert all(event["metrics"]["search_calls"] == 1 for event in completed)
    assert all(event["stop_reason"] == "submission_missing" for event in completed)
    assert all('"status": "checkpointed"' in event["result"] for event in completed)


def test_checkpointed_node_blocks_dependents(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        agent = _FakeSubAgent()
        created.append(agent)
        return agent

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    tool.agent_ref = _FakeParentAgent()

    result = asyncio.run(tool.execute(
        goal="checkpoint demo",
        sub_tasks=[
            {"id": "first", "description": "First", "depends_on": []},
            {"id": "second", "description": "Second", "depends_on": ["first"]},
        ],
    ))

    assert len(created) == 1
    assert "[BLOCKED]" in result


def test_analyst_runs_after_research_dependency_failure(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        sub_agent = _FailingSubAgent() if not created else _FakeSubAgent()
        created.append(sub_agent)
        return sub_agent

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    parent = _FakeParentAgent()
    tool.agent_ref = parent

    result = asyncio.run(tool.execute(
        goal="partial research",
        sub_tasks=[
            {
                "id": "researcher",
                "description": "Gather evidence",
                "agent": "web_researcher",
                "params": {"task_description": "Gather evidence", "angles": ["one"]},
            },
            {
                "id": "review",
                "description": "Review available evidence",
                "agent": "analyst",
                "params": {"task_description": "Review available evidence", "context": ""},
                "depends_on": ["researcher"],
            },
        ],
    ))

    assert len(created) == 2
    assert "research node failed" in result
    started = [event["data"]["id"] for event in parent.events if event["type"] == "dag_node_start"]
    assert started == ["researcher", "review"]
    assert "research node failed" in created[1].chat_history[0]["content"]


def test_interrupted_subagent_emits_stopped_status(monkeypatch):
    class InterruptedSubAgent(_FakeSubAgent):
        async def process_with_llm(self):
            self._interrupted = True

    monkeypatch.setattr("agent_factory.create_agent", lambda **_kwargs: InterruptedSubAgent())
    tool = Tool_CreatePlan()
    parent = _FakeParentAgent()
    tool.agent_ref = parent

    asyncio.run(tool.execute(
        goal="stop demo",
        sub_tasks=[{"id": "one", "description": "First", "depends_on": []}],
    ))

    completed = [event["data"] for event in parent.events if event["type"] == "dag_node_complete"]
    assert completed[0]["status"] == "STOPPED"
    assert completed[0]["stop_reason"] == "interrupted"


def test_analyst_has_no_web_or_browser_tools(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        sub_agent = _FakeSubAgent()
        sub_agent.tools = {
            "read_file": _FakeTool("read_file"),
            "web_search": _FakeTool("web_search"),
            "web_fetch": _FakeTool("web_fetch"),
            "mcp_browser_navigate": _FakeTool("mcp_browser_navigate"),
        }
        sub_agent.llm.tools = sub_agent.tools
        created.append(sub_agent)
        return sub_agent

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    tool.agent_ref = _FakeParentAgent()

    asyncio.run(tool.execute(
        goal="analysis",
        sub_tasks=[{"id": "one", "description": "Analyze evidence", "agent": "analyst"}],
    ))

    assert set(created[0].tools) == {"read_file", "read_research_state", "submit_output"}
    properties = created[0].tools["submit_output"].tool_schema["parameters"]["properties"]
    assert "next_wave_suggestions" in properties
    assert "findings" not in properties
    blocked = created[0].tools["read_file"].execute(file_path="research_state.json")
    assert blocked["progressive_disclosure_required"] is True


def test_web_researcher_tools_enforce_independent_search_and_fetch_budgets(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        sub_agent = _FakeSubAgent()
        sub_agent.tools = {
            "web_search": _FakeTool("web_search"),
            "web_fetch": _FakeTool("web_fetch"),
        }
        sub_agent.llm.tools = sub_agent.tools
        created.append(sub_agent)
        return sub_agent

    parent = _FakeParentAgent()
    parent.cfg.update({
        "research_sub_agent_max_web_search_calls": 1,
        "research_sub_agent_max_web_fetch_calls": 2,
    })
    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    tool.agent_ref = parent

    asyncio.run(tool.execute(
        goal="research",
        sub_tasks=[{"id": "one", "description": "Research", "agent": "web_researcher"}],
    ))

    search = created[0].tools["web_search"]
    fetch = created[0].tools["web_fetch"]
    assert search.execute(query="one")["message"] == "web_search ok"
    assert search.execute(query="two")["budget_exhausted"] is True
    assert fetch.execute(url="https://one.example")["message"] == "web_fetch ok"
    assert fetch.execute(url="https://two.example")["message"] == "web_fetch ok"
    assert fetch.execute(url="https://three.example")["budget_exhausted"] is True
    assert created[0].tools["submit_output"] is not None


def test_predefined_subagent_prompt_includes_current_date(monkeypatch):
    created_kwargs = []

    def fake_create_agent(**kwargs):
        created_kwargs.append(kwargs)
        return _FakeSubAgent()

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    tool.agent_ref = _FakeParentAgent()

    asyncio.run(tool.execute(
        goal="dated task",
        sub_tasks=[{"id": "one", "description": "Research", "agent": "web_researcher"}],
    ))

    assert f"Current date: {date.today().isoformat()}" in created_kwargs[0]["system_prompt"]


def test_create_plan_derives_predefined_node_description_from_task_params(monkeypatch):
    created = []

    def fake_create_agent(**_kwargs):
        sub_agent = _FakeSubAgent()
        created.append(sub_agent)
        return sub_agent

    monkeypatch.setattr("agent_factory.create_agent", fake_create_agent)
    tool = Tool_CreatePlan()
    parent = _FakeParentAgent()
    tool.agent_ref = parent

    result = asyncio.run(tool.execute(
        goal="research",
        sub_tasks=[{
            "id": "angle_one",
            "agent": "web_researcher",
            "params": {
                "task_description": "Research the first angle",
                "angles": ["first"],
            },
            "depends_on": [],
        }],
    ))

    assert "DAG Execution Complete" in result
    started = [event["data"] for event in parent.events if event["type"] == "dag_node_start"]
    assert started[0]["description"] == "Research the first angle"
    assert "Research the first angle" in created[0].chat_history[0]["content"]


def test_create_plan_returns_clear_error_when_node_has_no_description():
    tool = Tool_CreatePlan()
    tool.agent_ref = _FakeParentAgent()

    result = asyncio.run(tool.execute(
        goal="invalid",
        sub_tasks=[{"id": "missing_text", "depends_on": []}],
    ))

    assert result == (
        "Error: sub-task 'missing_text' requires description or "
        "params.task_description."
    )


def test_create_plan_schema_does_not_require_duplicate_description():
    required = Tool_CreatePlan().tool_schema["parameters"]["properties"][
        "sub_tasks"
    ]["items"]["required"]

    assert required == ["id"]


def test_research_state_caps_researcher_submission_and_assigns_stable_ids(tmp_path):
    findings = [
        {"text": f"Claim {index}", "source": f"https://example.com/{index}"}
        for index in range(15)
    ]

    Tool_CreatePlan._write_research_state(
        str(tmp_path), "wave1_angle_1",
        {"findings": findings, "gaps": [f"Gap {i}" for i in range(5)]},
        agent_type="web_researcher",
    )

    state = json.loads((tmp_path / "research_state.json").read_text(encoding="utf-8"))
    assert list(state["evidence"]) == [f"wave1_angle_1:e{i:02d}" for i in range(1, 13)]
    assert len(state["synthesis"]["candidate_gaps"]) == 3
    assert state["meta"]["revision"] == 1
    assert all(item["revision"] == 1 for item in state["evidence"].values())


def test_research_state_replaces_node_evidence_without_growing(tmp_path):
    first = {"findings": [{"text": "Old", "source": "https://old.example"}]}
    replacement = {"findings": [{"text": "New", "source": "https://new.example"}]}

    Tool_CreatePlan._write_research_state(
        str(tmp_path), "wave1_angle_1", first, agent_type="web_researcher",
    )
    Tool_CreatePlan._write_research_state(
        str(tmp_path), "wave1_angle_1", replacement, agent_type="web_researcher",
    )

    state = json.loads((tmp_path / "research_state.json").read_text(encoding="utf-8"))
    assert list(state["evidence"]) == ["wave1_angle_1:e01"]
    assert state["evidence"]["wave1_angle_1:e01"]["text"] == "New"
    assert state["meta"]["revision"] == 2


def test_analyst_updates_synthesis_and_removes_superseded_evidence(tmp_path):
    Tool_CreatePlan._write_research_state(
        str(tmp_path), "wave1_angle_1",
        {"findings": [
            {"text": "Keep", "source": "https://keep.example"},
            {"text": "Drop", "source": "https://drop.example"},
        ]},
        agent_type="web_researcher",
    )

    Tool_CreatePlan._write_research_state(
        str(tmp_path), "wave1_review",
        {
            "summary": "Compact synthesis",
            "coverage_score": 0.8,
            "critical_gaps": ["Missing panel data"],
            "next_wave_suggestions": [{"direction": "Panel data"}],
            "key_evidence_ids": ["wave1_angle_1:e01"],
            "remove_evidence_ids": ["wave1_angle_1:e02"],
            "contradictions": [],
        },
        agent_type="analyst",
    )

    state = json.loads((tmp_path / "research_state.json").read_text(encoding="utf-8"))
    assert next(iter(state)) == "synthesis"
    assert set(state["evidence"]) == {"wave1_angle_1:e01"}
    assert state["synthesis"]["summary"] == "Compact synthesis"
    assert state["synthesis"]["key_evidence_ids"] == ["wave1_angle_1:e01"]
    assert [item["id"] for item in state["synthesis"]["key_evidence"]] == [
        "wave1_angle_1:e01"
    ]
    assert state["synthesis"]["critical_gaps"] == ["Missing panel data"]
    assert state["meta"]["last_analyzed_revision"] == state["meta"]["revision"]
