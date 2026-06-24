"""Factory methods for HookContext — eliminates 9× repeated construction."""

from __future__ import annotations

import time
from typing import Any

from hooks import HookContext, HookEvent


class HookFactory:
    """Type-safe builders for HookContext, each dispatching fire-and-forget.

    Usage::

        factory = HookFactory(agent)
        await factory.state_enter("plan", "process")
        await factory.llm_error(RuntimeError("boom"))
    """

    def __init__(self, agent) -> None:
        self._agent = agent
        self._hooks = agent.hooks

    # ── State ──

    async def state_enter(self, stage: str, previous_stage: str) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.STATE_ENTER,
            agent=self._agent,
            timestamp=time.time(),
            stage=stage,
            previous_stage=previous_stage,
        ))

    # ── LLM ──

    async def llm_error(self, error: Exception) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.LLM_ERROR,
            agent=self._agent,
            timestamp=time.time(),
            tool_error=str(error),
            metadata={"error_type": type(error).__name__},
        ))

    # ── Skill ──

    async def skill_load(self, skill_name: str, **metadata: Any) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.SKILL_LOAD,
            agent=self._agent,
            timestamp=time.time(),
            skill_name=skill_name,
            metadata=metadata,
        ))

    async def skill_unload(self, skill_name: str, **metadata: Any) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.SKILL_UNLOAD,
            agent=self._agent,
            timestamp=time.time(),
            skill_name=skill_name,
            metadata=metadata,
        ))

    # ── Plan / DAG ──

    async def plan_created(self, goal: str, tasks: list[dict]) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.PLAN_CREATED,
            agent=self._agent,
            timestamp=time.time(),
            plan_data={"goal": goal, "tasks": tasks},
        ))

    async def plan_node_start(
        self, node_id: str, hint: str, description: str
    ) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.PLAN_NODE_START,
            agent=self._agent,
            timestamp=time.time(),
            node_id=node_id,
            metadata={"hint": hint, "description": description},
        ))

    async def plan_node_complete(
        self, node_id: str, result: str, hint: str, description: str
    ) -> None:
        await self._dispatch(HookContext(
            event=HookEvent.PLAN_NODE_COMPLETE,
            agent=self._agent,
            timestamp=time.time(),
            node_id=node_id,
            node_result=result[:200],
            metadata={"hint": hint, "description": description},
        ))

    # ── Internal ──

    async def _dispatch(self, ctx: HookContext) -> None:
        await self._hooks.dispatch_fire_and_forget(ctx)
