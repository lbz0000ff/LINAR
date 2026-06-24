"""Composition root — wires components and expresses the execution flow."""

from __future__ import annotations

from .state_machine import Stage, stage_label, StateMachine
from .hook_factory import HookFactory
from .plan_executor import PlanExecutor
from .skill_manager import SkillManager
from .memory_extractor import MemoryExtractor


class Orchestrator:
    """Async state machine wrapping ``agent.process_with_llm()``.

    All domain logic lives in components under ``agent/orchestrator/``.
    This class composes them and preserves the public API.
    """

    def __init__(self, agent) -> None:
        self.agent = agent

        # ── Components ──
        self._sm = StateMachine(on_transition=self._on_state_transition)
        self._hooks = HookFactory(agent)
        self._plan_exec = PlanExecutor(agent, self._hooks)
        self._skill_mgr = SkillManager(agent, self._sm, self._hooks, plan_executor=self._plan_exec)
        self._memory = MemoryExtractor(agent)

        # ── Public state (backward compat) ──
        self.needs_plan: bool = False
        self.dag_executor_enabled: bool = True

    # ── Properties ───────────────────────────────────────────

    @property
    def stage(self) -> Stage:
        return self._sm.current

    @property
    def previous_stage(self) -> Stage | None:
        return self._sm.previous

    @property
    def current_plan(self):
        return self._plan_exec.current_plan

    @current_plan.setter
    def current_plan(self, value):
        self._plan_exec.current_plan = value

    # ── Public API ───────────────────────────────────────────

    async def start(self, user_input: str, blocks: list[dict] | None = None) -> None:
        """Main entry: process user input through the FSM.

        ``create_plan`` is a blocking tool call — DAG execution happens
        inside the tool, results return to the agent in the same LLM turn.
        No PROCESS loop needed.
        """
        # ── INGEST ──
        await self._sm.transition(Stage.INGEST)

        btw_notes = getattr(self.agent, "consume_btw", lambda: [])()
        if btw_notes:
            user_input_parts = [user_input]
            user_input_parts.extend(f"[BTW: {note}]" for note in btw_notes)
            user_input = "\n\n".join(user_input_parts)

        if blocks:
            await self.agent.add_user_message(user_input, blocks)
        else:
            await self.agent.add_user_message(user_input)

        # ── PROCESS (single LLM cycle — create_plan is blocking) ──
        await self._sm.transition(Stage.PROCESS)
        try:
            await self.agent.process_with_llm()
        except Exception as e:
            await self._hooks.llm_error(e)
            await self._sm.transition(Stage.ERROR)
            raise

        # ── Post-process ──
        await self._memory.try_extract()
        self._plan_exec.cleanup()

        await self._sm.transition(Stage.COMPLETE)
        await self._sm.transition(Stage.IDLE)

    async def run_skill(self, skill, user_input: str) -> None:
        """Skill entry — delegates to SkillManager."""
        await self._skill_mgr.run(skill, user_input)

    # ── Internal ─────────────────────────────────────────────

    async def _on_state_transition(self, from_: Stage, to: Stage) -> None:
        await self._hooks.state_enter(to.name.lower(), from_.name.lower())

    @staticmethod
    def _last_user_text(user_input: str, blocks: list[dict] | None) -> str:
        """Extract plain text from the input (handles content blocks)."""
        if blocks is None:
            return user_input
        from content_block import extract_text

        raw = {"role": "user", "content": blocks}
        return extract_text(raw)
