import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_factory
import subagent
from agent import Agent


def _write_agent_type(tmp_path, frontmatter: str) -> None:
    (tmp_path / "demo.md").write_text(
        f"---\n{frontmatter}\n---\nDemo prompt",
        encoding="utf-8",
    )


def test_subagent_definition_rejects_provider_field(tmp_path, monkeypatch):
    _write_agent_type(tmp_path, "name: demo\nprovider: deepseek")
    monkeypatch.setattr(subagent, "_resolve_agents_dir", lambda: str(tmp_path))

    with pytest.raises(ValueError, match=r"demo\.md.*provider"):
        subagent.load_subagent("demo")


def test_subagent_definition_keeps_optional_model_override(tmp_path, monkeypatch):
    _write_agent_type(tmp_path, "name: demo\nmodel: deepseek-v4-pro")
    monkeypatch.setattr(subagent, "_resolve_agents_dir", lambda: str(tmp_path))

    definition = subagent.load_subagent("demo")

    assert definition["model"] == "deepseek-v4-pro"
    assert "provider" not in definition


class _FakeRuntimeAgent:
    def __init__(self, tools=None):
        self.tools = tools or {}
        self.llm = SimpleNamespace(
            model="main-model",
            provider="stepfun",
            client="main-client",
            tools=self.tools,
        )
        self.permissions = SimpleNamespace(switch_mode=lambda _mode: None)
        self.stop_event = SimpleNamespace()
        self.hooks = None
        self.session_id = None
        self.max_llm_calls = None
        self.emit = None
        self._confirm_callback = None
        self._workspace_root = None


class _FakeRegistry:
    def __init__(self, enabled_sets=None):
        self.enabled_sets = enabled_sets

    def get_tools(self):
        return {}


def _factory_config(aux):
    return {
        "providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "test-key",
            },
        },
        "tools": {"enabled_sets": []},
        "sub_agent_max_llm_calls": 25,
        "aux": aux,
    }


def test_predefined_subagent_inherits_aux_provider_and_model(monkeypatch):
    cfg = _factory_config({
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "test-key",
    })
    monkeypatch.setattr(agent_factory, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_factory, "ToolRegistry", _FakeRegistry)
    monkeypatch.setattr(agent_factory, "Agent", _FakeRuntimeAgent)
    monkeypatch.setattr(agent_factory, "AsyncOpenAI", lambda **kwargs: ("client", kwargs), raising=False)

    created = agent_factory.create_agent(use_aux=True)

    assert created.llm.provider == "deepseek"
    assert created.llm.model == "deepseek-v4-flash"
    assert created.llm.client[1]["base_url"] == "https://api.deepseek.com/v1"
    assert created.llm.client[1]["max_retries"] == 0


def test_predefined_subagent_model_overrides_aux_model_only(monkeypatch):
    cfg = _factory_config({
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "test-key",
    })
    monkeypatch.setattr(agent_factory, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_factory, "ToolRegistry", _FakeRegistry)
    monkeypatch.setattr(agent_factory, "Agent", _FakeRuntimeAgent)
    monkeypatch.setattr(agent_factory, "AsyncOpenAI", lambda **kwargs: ("client", kwargs), raising=False)

    created = agent_factory.create_agent(use_aux=True, model="deepseek-v4-pro")

    assert created.llm.provider == "deepseek"
    assert created.llm.model == "deepseek-v4-pro"


def test_create_agent_uses_injected_tool_factory(monkeypatch):
    cfg = _factory_config({})
    requested = []
    injected_tools = {"web_search": SimpleNamespace()}

    def tool_factory(enabled_sets):
        requested.append(enabled_sets)
        return injected_tools

    monkeypatch.setattr(agent_factory, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_factory, "Agent", _FakeRuntimeAgent)

    created = agent_factory.create_agent(
        agent_hint="research",
        tool_factory=tool_factory,
        permission_mode=None,
    )

    assert requested == [["time", "web", "file", "vision"]]
    assert created.tools is injected_tools


@pytest.mark.parametrize(
    ("aux", "message"),
    [
        ({"provider": "", "model": "model", "base_url": "url", "api_key": "key"}, "aux.provider"),
        ({"provider": "deepseek", "model": "", "base_url": "url", "api_key": "key"}, "aux.model"),
        ({"provider": "deepseek", "model": "model", "base_url": "url", "api_key": ""}, "aux.*api_key"),
    ],
)
def test_predefined_subagent_rejects_incomplete_aux_runtime(monkeypatch, aux, message):
    monkeypatch.setattr(agent_factory, "load_config", lambda: _factory_config(aux))
    monkeypatch.setattr(agent_factory, "ToolRegistry", _FakeRegistry)
    monkeypatch.setattr(agent_factory, "Agent", _FakeRuntimeAgent)

    with pytest.raises(ValueError, match=message):
        agent_factory.create_agent(use_aux=True)


def test_predefined_subagent_rejects_unknown_aux_provider(monkeypatch):
    cfg = _factory_config({
        "provider": "unregistered",
        "model": "some-model",
        "base_url": "https://example.invalid/v1",
        "api_key": "test-key",
    })
    monkeypatch.setattr(agent_factory, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_factory, "ToolRegistry", _FakeRegistry)
    monkeypatch.setattr(agent_factory, "Agent", _FakeRuntimeAgent)

    with pytest.raises(ValueError, match="unregistered.*not configured"):
        agent_factory.create_agent(use_aux=True)


def test_message_serialization_uses_actual_llm_provider(monkeypatch):
    runtime = Agent.__new__(Agent)
    runtime.cfg = {"llm": {"provider": "stepfun"}}
    runtime.llm = SimpleNamespace(provider="deepseek")
    runtime.chat_history = [{
        "role": "agent",
        "content": "",
        "reasoning": "must round-trip",
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": "{}"},
        }],
    }]
    runtime._resolved_since_last_build = set()
    runtime._promises = {}
    runtime._is_multimodal = False
    monkeypatch.setattr("skill.all_skills", lambda: [])

    messages = runtime._build_llm_messages()

    assert messages[0]["reasoning_content"] == "must round-trip"
