import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    import openai  # noqa: F401
except ImportError:
    sys.modules["openai"] = SimpleNamespace(
        APIError=Exception,
        AsyncOpenAI=lambda *args, **kwargs: SimpleNamespace(),
        OpenAI=lambda *args, **kwargs: SimpleNamespace(),
    )

from agent import Agent


def _agent_config():
    return {
        "llm": {
            "api_key": "test",
            "base_url": "http://test.invalid/v1",
            "model": "fake",
        },
        "max_turns": 30,
        "chat_history": {},
        "permissions": {"default": "allow"},
        "permission_modes": {},
    }


class _SequenceTool:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def execute(self):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


class _ScriptedLLM:
    model = "fake"

    def __init__(self, batches):
        self.system_prompt = ""
        self.batches = list(batches)
        self.calls = 0

    async def _stream(self):
        batch = self.batches[self.calls] if self.calls < len(self.batches) else []
        self.calls += 1
        if not batch:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="done",
                    reasoning_content=None,
                    tool_calls=None,
                ))]
            )
            return
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None,
                reasoning_content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=index,
                        id=tool_call_id,
                        function=SimpleNamespace(name=name, arguments="{}"),
                    )
                    for index, (tool_call_id, name) in enumerate(batch)
                ],
            ))]
        )

    def stream_response_messages(self, _messages):
        return self._stream()


def _make_agent(monkeypatch, tools, batches):
    monkeypatch.setattr("agent.load_config", _agent_config)
    agent = Agent(tools=tools, memory_enabled=False)
    agent.llm = _ScriptedLLM(batches)
    agent.emit = lambda _event: None
    return agent


def _single_calls(name, count, start=1):
    return [[(f"{name}-{index}", name)] for index in range(start, start + count)]


def _tool_messages(agent, name=None):
    return [
        message
        for message in agent.chat_history
        if message.get("role") == "tool"
        and (name is None or message.get("name") == name)
    ]


def test_fourth_consecutive_failure_is_rejected_before_execute(monkeypatch):
    failing = _SequenceTool(["Error: unavailable"])
    agent = _make_agent(
        monkeypatch,
        {"failing": failing},
        _single_calls("failing", 4) + [[]],
    )
    permission_checks = []
    original_check_permission = agent._check_permission

    async def track_permission_check(tool_name, arguments):
        permission_checks.append((tool_name, arguments))
        return await original_check_permission(tool_name, arguments)

    agent._check_permission = track_permission_check

    asyncio.run(agent.process_with_llm())

    messages = _tool_messages(agent, "failing")
    assert failing.calls == 3
    assert permission_checks == [("failing", "{}")] * 3
    assert [message["tool_call_id"] for message in messages] == [
        "failing-1",
        "failing-2",
        "failing-3",
        "failing-4",
    ]
    assert messages[-1]["result"].startswith("[TOOL_CIRCUIT_OPEN]")


def test_success_resets_consecutive_failure_count(monkeypatch):
    tool = _SequenceTool([
        "Error: first",
        "Error: second",
        "ok",
        "Error: third",
        "Error: fourth",
        "Error: fifth",
    ])
    agent = _make_agent(
        monkeypatch,
        {"flaky": tool},
        _single_calls("flaky", 7) + [[]],
    )

    asyncio.run(agent.process_with_llm())

    assert tool.calls == 6
    assert _tool_messages(agent, "flaky")[-1]["result"].startswith(
        "[TOOL_CIRCUIT_OPEN]"
    )


def test_open_circuit_does_not_block_other_tool_in_same_batch(monkeypatch):
    failing = _SequenceTool(["Error: unavailable"])
    healthy = _SequenceTool(["healthy result"])
    batches = _single_calls("failing", 3)
    batches.append([("failing-4", "failing"), ("healthy-1", "healthy")])
    batches.append([])
    agent = _make_agent(
        monkeypatch,
        {"failing": failing, "healthy": healthy},
        batches,
    )

    asyncio.run(agent.process_with_llm())

    assert failing.calls == 3
    assert healthy.calls == 1
    assert _tool_messages(agent, "healthy")[0]["result"] == "healthy result"


def test_circuit_recovers_on_next_agent_execution(monkeypatch):
    failing = _SequenceTool([
        "Error: first",
        "Error: second",
        "Error: third",
        "recovered",
    ])
    agent = _make_agent(
        monkeypatch,
        {"failing": failing},
        _single_calls("failing", 4) + [[]],
    )
    baseline_permission = agent.permissions.check("failing")

    async def run_two_agent_executions():
        await agent.process_with_llm()
        assert failing.calls == 3

        agent.llm = _ScriptedLLM([[("next-round", "failing")], []])
        await agent.process_with_llm()

    asyncio.run(run_two_agent_executions())

    assert failing.calls == 4
    assert agent.permissions.check("failing") == baseline_permission
    assert _tool_messages(agent, "failing")[-1] == {
        "role": "tool",
        "tool_call_id": "next-round",
        "name": "failing",
        "arguments": "{}",
        "result": "recovered",
        "round": 0,
    }


def test_threshold_keeps_existing_do_not_retry_meta_hint(monkeypatch):
    failing = _SequenceTool(["Error: unavailable"])
    agent = _make_agent(
        monkeypatch,
        {"failing": failing},
        _single_calls("failing", 4) + [[]],
    )

    asyncio.run(agent.process_with_llm())

    hints = [
        message["content"]
        for message in agent.chat_history
        if message.get("role") == "meta"
        and "Tool 'failing' has failed 3 times in a row" in message.get("content", "")
    ]
    assert len(hints) == 1
    assert "Do NOT retry" in hints[0]


def test_bracket_prefixed_success_does_not_trip_circuit(monkeypatch):
    successful = _SequenceTool(["[executed] completed"])
    agent = _make_agent(
        monkeypatch,
        {"successful": successful},
        _single_calls("successful", 4) + [[]],
    )

    asyncio.run(agent.process_with_llm())

    assert successful.calls == 4
    assert all(
        message["result"] == "[executed] completed"
        for message in _tool_messages(agent, "successful")
    )
    assert not any(
        message.get("role") == "meta"
        and "has failed" in message.get("content", "")
        for message in agent.chat_history
    )
