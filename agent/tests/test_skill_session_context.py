import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_openai_stub = sys.modules.setdefault("openai", SimpleNamespace())
if not hasattr(_openai_stub, "AsyncOpenAI"):
    _openai_stub.AsyncOpenAI = lambda *args, **kwargs: SimpleNamespace()
if not hasattr(_openai_stub, "OpenAI"):
    _openai_stub.OpenAI = lambda *args, **kwargs: SimpleNamespace()

from skill import Skill, activate_skill_for_agent
from tool.basic_tools.tool_skill import Tool_Skill


class _FakeAgent:
    def __init__(self):
        self.session_id = 42
        self._conversation_round = 3
        self.chat_history = []
        self.tools = {"read_file": object()}
        self.llm = SimpleNamespace(system_prompt="base prompt", tools=self.tools)
        self._active_skill = None
        self._skill_active = False
        self.events = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


def _make_skill(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text(
        "def execute(command='', args=None):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    skill = Skill()
    skill.name = "demo"
    skill.description = "Demo skill"
    skill.system_prompt = "Follow the demo skill."
    skill.skill_dir = str(tmp_path)
    skill.scripts_dir = str(scripts_dir)
    return skill


def test_activate_skill_injects_messages_persists_checkpoint_and_keeps_tools(monkeypatch, tmp_path):
    saved = []
    checkpoints = []
    monkeypatch.setattr(
        "database.save_message",
        lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(
        "database.update_session_active_skill",
        lambda session_id, name, args: checkpoints.append((session_id, name, args)),
    )
    agent = _FakeAgent()
    skill = _make_skill(tmp_path)

    activate_skill_for_agent(agent, skill, args="topic", emit=True)

    assert agent.llm.system_prompt == "base prompt"
    assert agent._active_skill is skill
    assert agent._skill_active is False
    assert "read_file" in agent.tools
    assert "demo_helper" in agent.tools
    assert agent.llm.tools is agent.tools
    assert agent.chat_history == [
        {"role": "meta", "content": "[SYSTEM] Skill /demo is now active. Args: topic"},
        {"role": "user", "content": "Follow the demo skill."},
    ]
    assert [m["role"] for m in saved] == ["meta", "user"]
    assert checkpoints == [(42, "demo", "topic")]
    assert agent.events == [
        {"type": "skill_loaded", "data": {"name": "demo", "desc": "Demo skill", "args": "topic"}}
    ]


def test_activate_skill_can_restore_runtime_without_reinjecting_messages(monkeypatch, tmp_path):
    monkeypatch.setattr("database.save_message", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected save")))
    monkeypatch.setattr(
        "database.update_session_active_skill",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected checkpoint")),
    )
    agent = _FakeAgent()
    skill = _make_skill(tmp_path)

    activate_skill_for_agent(
        agent,
        skill,
        args="topic",
        inject_instructions=False,
        persist=False,
        checkpoint=False,
        emit=False,
    )

    assert agent.chat_history == []
    assert agent._active_skill is skill
    assert "demo_helper" in agent.tools


def test_generic_skill_tool_uses_shared_activation_path(monkeypatch, tmp_path):
    saved = []
    checkpoints = []
    monkeypatch.setattr("database.save_message", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(
        "database.update_session_active_skill",
        lambda session_id, name, args: checkpoints.append((session_id, name, args)),
    )

    skill = _make_skill(tmp_path)
    monkeypatch.setattr("skill.get_skill", lambda name: skill if name == "demo" else None)
    agent = _FakeAgent()
    tool = Tool_Skill()
    tool.agent_ref = agent

    result = tool.execute(skill="demo", args="topic")

    assert "Skill '/demo' loaded" in result
    assert agent._active_skill is skill
    assert "demo_helper" in agent.tools
    assert checkpoints == [(42, "demo", "topic")]
    assert [m["role"] for m in saved] == ["meta", "user"]


def test_build_llm_messages_keeps_skill_listing_available_each_turn(monkeypatch):
    import agent as agent_module

    skill = Skill()
    skill.name = "demo"
    skill.description = "Demo skill"
    skill.when_to_use = "Use when the user asks for demo work"
    fake_agent = object.__new__(agent_module.Agent)
    fake_agent.chat_history = [{"role": "user", "content": "second turn"}]
    fake_agent._sent_skill_names = {skill.name}
    fake_agent._promises = {}
    fake_agent._resolved_since_last_build = set()
    fake_agent._is_multimodal = False
    fake_agent.observation_store = SimpleNamespace(has_images=lambda: False)
    fake_agent.cfg = {"llm": {"provider": "deepseek"}}

    monkeypatch.setattr("skill.all_skills", lambda: [skill])

    messages = agent_module.Agent._build_llm_messages(fake_agent)

    skill_messages = [
        msg["content"]
        for msg in messages
        if msg["role"] == "system"
        and "The following skills are available" in msg["content"]
    ]
    assert len(skill_messages) == 1
    assert "- demo: Demo skill" in skill_messages[0]
    assert "Use when the user asks for demo work" in skill_messages[0]


def test_agent_switch_session_restores_workspace_and_active_skill(monkeypatch, tmp_path):
    import agent as agent_module
    import database as db

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill = _make_skill(tmp_path)
    calls = []
    fake_agent = object.__new__(agent_module.Agent)
    fake_agent.chat_history = [{"role": "user", "content": "old"}]
    fake_agent._conversation_round = 0
    fake_agent._active_skill = None
    fake_agent._skill_active = False

    monkeypatch.setattr(
        db,
        "get_session_by_id",
        lambda session_id: {
            "id": session_id,
            "workspace_path": str(workspace),
            "active_skill": "demo",
            "active_skill_args": "topic",
        },
    )
    monkeypatch.setattr(db, "get_session_messages", lambda session_id: [])
    monkeypatch.setattr(agent_module, "get_skill", lambda name: skill if name == "demo" else None)

    def fake_activate(agent, skill_obj, **kwargs):
        calls.append((agent, skill_obj, kwargs))

    monkeypatch.setattr(agent_module, "activate_skill_for_agent", fake_activate)

    assert agent_module.Agent.switch_session(fake_agent, 99) is True

    assert fake_agent.session_id == 99
    assert fake_agent.chat_history == []
    assert fake_agent._workspace_root == str(workspace)
    assert calls == [
        (
            fake_agent,
            skill,
            {
                "args": "topic",
                "inject_instructions": False,
                "persist": False,
                "checkpoint": False,
                "emit": False,
            },
        )
    ]
