import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_openai_stub = sys.modules.setdefault("openai", SimpleNamespace())
if not hasattr(_openai_stub, "AsyncOpenAI"):
    _openai_stub.AsyncOpenAI = lambda *args, **kwargs: SimpleNamespace()
if not hasattr(_openai_stub, "OpenAI"):
    _openai_stub.OpenAI = lambda *args, **kwargs: SimpleNamespace()

from api.session_manager import SessionManager


class _FakePermissions:
    def __init__(self):
        self.mode = "safe"
        self.switched = []

    def switch_mode(self, mode: str) -> None:
        self.mode = mode
        self.switched.append(mode)


class _FakeAgent:
    def __init__(self):
        self.permissions = _FakePermissions()

    def interrupt(self):
        pass


class _FakeSession:
    def __init__(self, session_id: int):
        self.session_id = session_id
        self.agent = _FakeAgent()
        self.resolved = []

    def resolve_permission(self, action: str) -> None:
        self.resolved.append(action)

    def stop(self):
        pass


def test_broadcast_session_event_attaches_session_id():
    events = []
    session = _FakeSession(7)
    SessionManager._emit_session_event(events.append, session, {"type": "tool_call"})

    assert events == [{"type": "tool_call", "session_id": 7}]


def test_permission_response_routes_to_requested_session():
    sm = SessionManager()
    sm._sessions = {1: _FakeSession(1), 2: _FakeSession(2)}

    assert sm.resolve_permission_for_session(2, "allow_once") is True

    assert sm._sessions[1].resolved == []
    assert sm._sessions[2].resolved == ["allow_once"]


def test_permission_mode_is_global_and_applied_to_sessions():
    sm = SessionManager()
    first = _FakeSession(1)
    second = _FakeSession(2)
    sm._sessions = {1: first}

    sm.switch_permission_mode("auto")

    assert first.agent.permissions.mode == "auto"
    sm._sessions[2] = second
    sm.apply_permission_mode(second)
    assert second.agent.permissions.mode == "auto"


def test_subagent_factory_defaults_to_auto_permission_mode(monkeypatch):
    import agent as agent_module
    import agent_factory

    cfg = {
        "llm": {"api_key": "", "base_url": "", "model": "fake"},
        "chat_history": {},
        "permissions": {"default": "ask"},
        "permission_modes": {"active": "safe", "modes": {"safe": {"default": "ask"}}},
        "tools": {"enabled_sets": []},
    }
    monkeypatch.setattr(agent_factory, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_module, "load_config", lambda: cfg)
    monkeypatch.setattr(
        agent_factory,
        "ToolRegistry",
        lambda enabled_sets=None: SimpleNamespace(get_tools=lambda: {}),
    )

    sub_agent = agent_factory.create_agent()

    assert sub_agent.permissions.mode == "auto"
