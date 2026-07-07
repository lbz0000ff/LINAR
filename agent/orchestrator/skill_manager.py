"""Skill lifecycle — load, execute, unload, and fork sub-agents."""

from __future__ import annotations

import logging

from .state_machine import Stage, StateMachine

log = logging.getLogger(__name__)


class SkillManager:
    """Manages skill lifecycle: load, exec, unload, and fork.

    Flow::

        normal  SKILL_LOAD → SKILL_EXEC → SKILL_UNLOAD → COMPLETE → IDLE
        fork    SKILL_LOAD → (sub-agent) → SKILL_EXEC → SKILL_UNLOAD → ...
        error   SKILL_EXEC → ERROR  (on_unload still called before raise)
    """

    def __init__(
        self,
        agent,
        state_machine: StateMachine,
        hook_factory,
        plan_executor=None,
    ) -> None:
        self._agent = agent
        self._sm = state_machine
        self._hooks = hook_factory
        self._plan_exec = plan_executor

    async def run(self, skill, user_input: str) -> None:
        """Run *skill* through its complete lifecycle."""
        if getattr(skill, "context", "") == "fork":
            await self._run_forked(skill, user_input)
        else:
            await self._run_normal(skill, user_input)

    # ── Normal skill ──────────────────────────────────────────

    async def _run_normal(self, skill, user_input: str) -> None:
        await self._sm.transition(Stage.SKILL_LOAD)
        from skill import activate_skill_for_agent
        activate_skill_for_agent(self._agent, skill, args=user_input, emit=True)
        await self._hooks.skill_load(
            skill.name,
            description=getattr(skill, "description", ""),
        )

        if user_input.strip():
            await self._agent.add_user_message(user_input)
            await self._sm.transition(Stage.SKILL_EXEC)
            try:
                await self._agent.process_with_llm()
            except Exception:
                log.exception("Skill /%s failed", skill.name)
                await self._sm.transition(Stage.ERROR)
                raise
            await self._sm.transition(Stage.SKILL_UNLOAD)
            await self._hooks.skill_unload(skill.name)

        await self._sm.transition(Stage.COMPLETE)
        await self._sm.transition(Stage.IDLE)

    # ── Forked skill (sub-agent) ──────────────────────────────

    async def _run_forked(self, skill, user_input: str) -> None:
        from agent_factory import create_agent
        from agent import Agent
        from tool_registry import get_tools

        await self._sm.transition(Stage.SKILL_LOAD)
        self._agent.emit({"type": "skill_fork", "data": skill.name})

        try:
            sub_cfg = self._agent.cfg
            enabled = sub_cfg.get("tools", {}).get("enabled_sets", None)
            sub_tools = get_tools(enabled)
            _saved_refs = {}
            for t in sub_tools.values():
                if hasattr(t, "agent_ref"):
                    _saved_refs[id(t)] = t.agent_ref
            sub_agent = Agent(tools=sub_tools)
        except Exception as exc:
            self._agent.emit({"type": "error", "data": f"Failed to fork agent: {exc}"})
            await self._sm.transition(Stage.COMPLETE)
            await self._sm.transition(Stage.IDLE)
            return

        sub_agent.emit = self._agent.emit
        sub_agent.stop_event = self._agent.stop_event
        for t in sub_agent.tools.values():
            if hasattr(t, "stop_event"):
                t.stop_event = sub_agent.stop_event

        try:
            skill.on_load(sub_agent)
            await self._hooks.skill_load(
                skill.name,
                description=getattr(skill, "description", ""),
                forked=True,
            )

            await sub_agent.add_user_message(user_input)
            await self._sm.transition(Stage.SKILL_EXEC)
            try:
                await sub_agent.process_with_llm()
            except Exception:
                await self._sm.transition(Stage.ERROR)
                skill.on_unload(sub_agent)
                raise

            await self._sm.transition(Stage.SKILL_UNLOAD)
            await self._hooks.skill_unload(skill.name, forked=True)
            skill.on_unload(sub_agent)
        finally:
            for t in sub_tools.values():
                if hasattr(t, "agent_ref") and id(t) in _saved_refs:
                    t.agent_ref = _saved_refs[id(t)]
                if hasattr(t, "stop_event"):
                    t.stop_event = self._agent.stop_event

        await self._sm.transition(Stage.COMPLETE)
        await self._sm.transition(Stage.IDLE)
