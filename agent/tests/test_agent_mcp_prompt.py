import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import Agent
import tool_registry


def _agent_config() -> dict:
    return {
        "llm": {
            "api_key": "test",
            "base_url": "http://test.invalid/v1",
            "model": "fake",
        },
        "chat_history": {},
        "memory": {"enabled": False},
        "permissions": {"default": "allow"},
        "permission_modes": {},
        "prompt": {"files": []},
    }


def test_prompt_build_does_not_initialize_unregistered_mcp_servers(monkeypatch) -> None:
    monkeypatch.setattr("agent.load_config", _agent_config)
    monkeypatch.setattr(
        tool_registry,
        "_init_mcp_servers",
        lambda: (_ for _ in ()).throw(AssertionError("MCP startup leaked into prompt build")),
    )

    runtime = Agent(tools={"read_file": SimpleNamespace()}, memory_enabled=False)

    assert "## MCP tools" not in runtime.llm.system_prompt


def test_prompt_lists_only_mcp_tools_registered_on_current_agent(monkeypatch) -> None:
    monkeypatch.setattr("agent.load_config", _agent_config)
    registered = SimpleNamespace(description="Registered search tool. More detail")
    runtime = Agent(
        tools={
            "mcp_registered_search": registered,
            "read_file": SimpleNamespace(),
        },
        memory_enabled=False,
    )

    assert "`mcp_registered_search` — Registered search tool" in runtime.llm.system_prompt
    assert "mcp_unregistered" not in runtime.llm.system_prompt
