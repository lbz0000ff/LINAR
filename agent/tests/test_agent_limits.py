import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault(
    "openai",
    SimpleNamespace(
        AsyncOpenAI=lambda *args, **kwargs: SimpleNamespace(),
        OpenAI=lambda *args, **kwargs: SimpleNamespace(),
    ),
)

from agent import Agent


class _NoopTool:
    name = "noop"

    def execute(self):
        return "ok"


class _FakeLLM:
    model = "fake"

    def __init__(self):
        self.system_prompt = ""

    async def _stream(self):
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(name="noop", arguments="{}"),
                            )
                        ],
                    )
                )
            ]
        )

    def stream_response_messages(self, _messages):
        return self._stream()


class _UsageStreamingLLM:
    model = "step-3.7-flash"
    provider = "stepfun"

    def __init__(self):
        self.system_prompt = ""

    async def _stream(self):
        for completion_tokens in (1, 2, 3):
            yield SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=completion_tokens,
                    total_tokens=100 + completion_tokens,
                    model_extra={
                        "prompt_cache_hit_tokens": 80,
                        "prompt_cache_miss_tokens": 20,
                    },
                ),
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="x",
                    reasoning_content=None,
                    tool_calls=[],
                ))],
            )

    def stream_response_messages(self, _messages):
        return self._stream()


def test_agent_uses_max_turns_config(monkeypatch):
    monkeypatch.setattr(
        "agent.load_config",
        lambda: {
            "llm": {"api_key": "test", "base_url": "http://test.invalid/v1", "model": "fake"},
            "max_turns": 80,
            "chat_history": {},
            "permissions": {"default": "allow"},
            "permission_modes": {},
        },
    )

    agent = Agent(tools={}, memory_enabled=False)

    assert agent.max_llm_calls == 80


def test_agent_keeps_legacy_max_llm_calls_config(monkeypatch):
    monkeypatch.setattr(
        "agent.load_config",
        lambda: {
            "llm": {"api_key": "test", "base_url": "http://test.invalid/v1", "model": "fake"},
            "max_llm_calls": 12,
            "chat_history": {},
            "permissions": {"default": "allow"},
            "permission_modes": {},
        },
    )

    agent = Agent(tools={}, memory_enabled=False)

    assert agent.max_llm_calls == 12


def test_llm_limit_adds_explicit_meta_message(monkeypatch):
    monkeypatch.setattr(
        "agent.load_config",
        lambda: {
            "llm": {"api_key": "test", "base_url": "http://test.invalid/v1", "model": "fake"},
            "max_turns": 1,
            "chat_history": {},
            "permissions": {"default": "allow"},
            "permission_modes": {},
        },
    )
    agent = Agent(tools={"noop": _NoopTool()}, memory_enabled=False)
    agent.llm = _FakeLLM()
    agent.emit = lambda _event: None

    asyncio.run(agent.process_with_llm())

    assert any(
        msg.get("role") == "meta"
        and "LLM call limit reached" in msg.get("content", "")
        for msg in agent.chat_history
    )


def test_streaming_usage_is_emitted_once_with_the_final_snapshot(monkeypatch):
    monkeypatch.setattr(
        "agent.load_config",
        lambda: {
            "llm": {"api_key": "test", "base_url": "http://test.invalid/v1", "model": "fake"},
            "max_turns": 1,
            "chat_history": {},
            "permissions": {"default": "allow"},
            "permission_modes": {},
        },
    )
    agent = Agent(tools={}, memory_enabled=False)
    agent.llm = _UsageStreamingLLM()
    emitted = []
    agent.emit = emitted.append

    asyncio.run(agent.process_with_llm())

    usage_events = [event for event in emitted if event.get("type") == "usage"]
    assert usage_events == [{
        "type": "usage",
        "data": {
            "prompt_tokens": 100,
            "completion_tokens": 3,
            "total_tokens": 103,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
            "reasoning_tokens": 0,
        },
    }]
