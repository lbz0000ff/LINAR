import asyncio
import os
import sys
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
