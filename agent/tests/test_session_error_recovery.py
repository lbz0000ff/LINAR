import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace

from api import session_manager
from api.session_manager import Session
from orchestrator.state_machine import Stage


class _Agent:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


def test_error_recovery_replaces_terminal_orchestrator(monkeypatch):
    session = Session.__new__(Session)
    session.session_id = 7
    session.agent = _Agent()
    session.orchestrator = SimpleNamespace(stage=Stage.ERROR)
    session.status = "error"

    class _FreshOrchestrator:
        def __init__(self, agent) -> None:
            assert agent is session.agent
            self.stage = Stage.IDLE

    monkeypatch.setattr(session_manager, "Orchestrator", _FreshOrchestrator)

    failed = session.orchestrator
    session._recover_from_error(RuntimeError("failed"))

    assert session.orchestrator is not failed
    assert session.orchestrator.stage is Stage.IDLE
    assert session.status == "idle"
    assert session.agent.events == [
        {"type": "error", "data": "failed"},
        {"type": "complete"},
    ]
