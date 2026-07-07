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

    async def add_user_message(self, text):
        self.chat_history.append({"role": "user", "content": text})

    async def process_with_llm(self):
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
