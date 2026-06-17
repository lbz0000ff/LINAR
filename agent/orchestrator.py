"""Agent orchestrator — explicit state machine around the LLM loop (async).

    IDLE → INGEST → ROUTE → [PLAN →] [PROCESS | DAG_EXECUTE] → COMPLETE → IDLE
"""

from __future__ import annotations

import asyncio
import json
import os
import re as _re
import time

from enum import Enum, auto
from openai import AsyncOpenAI

from hooks import HookContext, HookEvent
from logger import get_logger as _get_logger

log = _get_logger(__name__)


class Stage(Enum):
    IDLE = auto()
    INGEST = auto()
    ROUTE = auto()
    PLAN = auto()
    PROCESS = auto()
    DAG_EXECUTE = auto()
    SKILL_LOAD = auto()
    SKILL_EXEC = auto()
    SKILL_UNLOAD = auto()
    COMPLETE = auto()
    ERROR = auto()


_STAGE_LABELS = {s: s.name.lower() for s in Stage}


def stage_label(stage: Stage) -> str:
    return _STAGE_LABELS.get(stage, stage.name.lower())


class Orchestrator:
    """Async state machine wrapping ``agent.process_with_llm()``."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.stage: Stage = Stage.IDLE
        self.previous_stage: Stage | None = None
        self.current_plan = None
        self.needs_plan: bool = False
        self.dag_executor_enabled: bool = True

    # ── public API ────────────────────────────────────────

    async def start(self, user_input: str) -> None:
        await self._transition(Stage.INGEST)
        btw_notes = getattr(self.agent, 'consume_btw', lambda: [])()
        if btw_notes:
            user_input += "\n\n" + "\n".join(f"[BTW: {note}]" for note in btw_notes)
        await self.agent.add_user_message(user_input)

        await self._transition(Stage.ROUTE)
        self._route()

        if self.needs_plan:
            await self._transition(Stage.PLAN)
            await self._generate_plan()

        if self._should_execute_dag():
            await self._transition(Stage.DAG_EXECUTE)
            await self._execute_dag_plan()
            await self._transition(Stage.PROCESS)
            try:
                await self.agent.process_with_llm()
            except Exception as e:
                # Dispatch LLM_ERROR hook
                await self.agent.hooks.dispatch_fire_and_forget(
                    HookContext(
                        event=HookEvent.LLM_ERROR,
                        agent=self.agent,
                        timestamp=time.time(),
                        tool_error=str(e),
                        metadata={"error_type": type(e).__name__},
                    )
                )
                await self._transition(Stage.ERROR)
                raise
        else:
            await self._transition(Stage.PROCESS)
            try:
                await self.agent.process_with_llm()
            except Exception as e:
                # Dispatch LLM_ERROR hook
                await self.agent.hooks.dispatch_fire_and_forget(
                    HookContext(
                        event=HookEvent.LLM_ERROR,
                        agent=self.agent,
                        timestamp=time.time(),
                        tool_error=str(e),
                        metadata={"error_type": type(e).__name__},
                    )
                )
                await self._transition(Stage.ERROR)
                raise

        # ── Memory extraction (after each conversation round) ──
        await self._try_memory_extraction()

        self._post_process_cleanup()
        await self._transition(Stage.COMPLETE)
        await self._transition(Stage.IDLE)

    async def run_skill(self, skill, user_input: str) -> None:
        if getattr(skill, "context", "") == "fork":
            await self._run_skill_forked(skill, user_input)
            return

        await self._transition(Stage.SKILL_LOAD)
        skill.on_load(self.agent)

        # Dispatch SKILL_LOAD hook
        await self.agent.hooks.dispatch_fire_and_forget(
            HookContext(
                event=HookEvent.SKILL_LOAD,
                agent=self.agent,
                timestamp=time.time(),
                skill_name=skill.name,
                metadata={"description": getattr(skill, "description", "")},
            )
        )

        self.agent.chat_history.append({
            "role": "meta",
            "content": (
                f"[SYSTEM] Skill /{skill.name} is now active. "
                f"Follow the skill's instructions directly. "
                f"Do NOT call skill_view — you are already in the skill context."
            ),
        })

        if user_input.strip():
            await self.agent.add_user_message(user_input)
            await self._transition(Stage.SKILL_EXEC)
            try:
                await self.agent.process_with_llm()
            except Exception:
                await self._transition(Stage.ERROR)
                skill.on_unload(self.agent)
                raise
        else:
            self.agent.emit({"type": "skill_loaded", "data": {"name": skill.name, "desc": skill.description}})

        await self._transition(Stage.SKILL_UNLOAD)

        # Dispatch SKILL_UNLOAD hook
        await self.agent.hooks.dispatch_fire_and_forget(
            HookContext(
                event=HookEvent.SKILL_UNLOAD,
                agent=self.agent,
                timestamp=time.time(),
                skill_name=skill.name,
            )
        )

        skill.on_unload(self.agent)
        await self._transition(Stage.COMPLETE)
        await self._transition(Stage.IDLE)

    async def _run_skill_forked(self, skill, user_input: str) -> None:
        from agent_factory import create_agent
        from agent import Agent

        await self._transition(Stage.SKILL_LOAD)
        self.agent.emit({"type": "skill_fork", "data": skill.name})

        try:
            from tool_registry import get_tools
            sub_cfg = self.agent.cfg
            enabled = sub_cfg.get("tools", {}).get("enabled_sets", None)
            sub_tools = get_tools(enabled)
            _saved_refs = {}
            for t in sub_tools.values():
                if hasattr(t, 'agent_ref'):
                    _saved_refs[id(t)] = t.agent_ref
            sub_agent = Agent(tools=sub_tools)
        except Exception as exc:
            self.agent.emit({"type": "error", "data": f"Failed to fork agent: {exc}"})
            await self._transition(Stage.COMPLETE)
            await self._transition(Stage.IDLE)
            return

        sub_agent.emit = self.agent.emit
        sub_agent.stop_event = self.agent.stop_event
        for t in sub_agent.tools.values():
            if hasattr(t, 'stop_event'):
                t.stop_event = sub_agent.stop_event

        try:
            skill.on_load(sub_agent)

            # Dispatch SKILL_LOAD hook for forked skill
            await self.agent.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.SKILL_LOAD,
                    agent=self.agent,
                    timestamp=time.time(),
                    skill_name=skill.name,
                    metadata={"forked": True, "description": getattr(skill, "description", "")},
                )
            )

            await sub_agent.add_user_message(user_input)
            await self._transition(Stage.SKILL_EXEC)
            try:
                await sub_agent.process_with_llm()
            except Exception:
                await self._transition(Stage.ERROR)
                skill.on_unload(sub_agent)
                raise
            await self._transition(Stage.SKILL_UNLOAD)

            # Dispatch SKILL_UNLOAD hook for forked skill
            await self.agent.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.SKILL_UNLOAD,
                    agent=self.agent,
                    timestamp=time.time(),
                    skill_name=skill.name,
                    metadata={"forked": True},
                )
            )

            skill.on_unload(sub_agent)
        finally:
            for t in sub_tools.values():
                if hasattr(t, 'agent_ref') and id(t) in _saved_refs:
                    t.agent_ref = _saved_refs[id(t)]
                if hasattr(t, 'stop_event'):
                    t.stop_event = self.agent.stop_event

        await self._transition(Stage.COMPLETE)
        await self._transition(Stage.IDLE)

    # ── routing ───────────────────────────────────────────

    def _route(self) -> None:
        """Classify input and decide if planning is needed.

        Uses lightweight heuristics.  Replacable with LLM-based
        classification for more accurate detection.
        """
        # Reset state
        self.current_plan = None
        self.needs_plan = False

        if not self.agent.chat_history:
            return

        user_input = self.agent.chat_history[-1].get("content", "")
        if not user_input:
            return

        # Multi-step indicators — conjunctions that join multiple actions.
        # Avoid single digits / common substrings that trigger on version
        # numbers ("SD1.5") or casual sentences.
        multi_step_keywords = [
            " and then ", " first ", " finally ",
            "secondly,", "thirdly,",
            # Chinese
            "然后", "接着", "首先", "其次",
            "第一步", "第二步", "步骤如下",
        ]
        kw_matches = sum(user_input.lower().count(kw) for kw in multi_step_keywords if kw)
        self.needs_plan = kw_matches >= 1

    def _should_execute_dag(self) -> bool:
        """Return True if the current plan should be executed via DAGExecutor.

        Uses DAGExecutor when:
        - Enabled via ``dag_executor_enabled`` flag
        - A DAGPlan was generated (not None)
        - It has at least 2 nodes
        - At least one wave has parallel-ready nodes (real parallelism)
        """
        if not self.dag_executor_enabled:
            return False
        plan = self.current_plan
        if plan is None:
            return False
        nodes = list(plan.nodes.values())
        if len(nodes) < 2:
            return False
        # Check if there's at least one wave with multiple ready nodes
        ready = plan.get_ready()
        if len(ready) > 1:
            return True
        # Even if wave 0 has 1 node, check whether later waves exist
        return len(nodes) > 2

    async def _execute_dag_plan(self) -> None:
        from executor import DAGExecutor
        from agent_factory import create_agent, run_task as run_agent_task

        plan = self.current_plan
        if plan is None:
            return

        self.agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})
        agent_results: dict[str, str] = {}

        async def _node_runner(node_id: str, description: str) -> str:
            node = plan.nodes.get(node_id)
            hint = node.agent_hint if node else "any"
            deps = {d: agent_results[d] for d in (node.depends_on if node else [])
                    if d in agent_results}
            agent = create_agent(agent_hint=hint, predecessor_results=deps,
                                 stop_event=self.agent.stop_event)

            # Dispatch PLAN_NODE_START hook
            await self.agent.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.PLAN_NODE_START,
                    agent=self.agent,
                    timestamp=time.time(),
                    node_id=node_id,
                    metadata={"hint": hint, "description": description},
                )
            )

            self.agent.emit({
                "type": "dag_node_start",
                "data": {"id": node_id, "hint": hint, "description": description},
            })
            result = await run_agent_task(agent, description, hint, deps)

            # Dispatch PLAN_NODE_COMPLETE hook
            await self.agent.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.PLAN_NODE_COMPLETE,
                    agent=self.agent,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_result=result[:200],
                    metadata={"hint": hint, "description": description},
                )
            )

            self.agent.emit({
                "type": "dag_node_complete",
                "data": {"id": node_id, "result": result[:200]},
            })
            agent_results[node_id] = result
            return result

        executor = DAGExecutor(plan, runner=None,
                               interrupt_check=lambda: self.agent.stop_event.is_set())
        try:
            all_results = await executor.execute_all_async(_node_runner)
        except Exception as exc:
            self.agent.emit({"type": "plan_error", "data": str(exc)})
            return

        summary_parts = []
        try:
            order = plan.topological_sort()
        except Exception:
            order = list(plan.nodes.keys())
        for nid in order:
            node = plan.nodes[nid]
            result = all_results.get(nid, "[no result]")
            status = node.status.value
            summary_parts.append(f"[{status}] {nid}: {node.description}\n{result[:300]}")
        summary = "\n\n".join(summary_parts)

        plan_block = (
            f"\n## DAG Execution Complete\n"
            f"All sub-tasks have been executed. Here are the results:\n\n{summary}"
        )
        self.agent.chat_history.append({"role": "meta", "content": plan_block})
        self.agent.emit({"type": "plan_complete", "data": summary})

    async def _generate_plan(self) -> None:
        cfg = self.agent.cfg
        user_input = self.agent.chat_history[-1]["content"]
        aux_cfg = cfg.get("aux") or {}
        planner_provider = aux_cfg.get("base_url") or cfg["llm"]["base_url"]
        planner_key = aux_cfg.get("api_key") or cfg["llm"]["api_key"]
        planner_model = aux_cfg.get("model") or cfg["llm"]["model"]
        planner_temp = aux_cfg.get("temperature") or 0.3

        prompt_dir = os.path.join(os.path.dirname(__file__), "prompt")
        prompt_path = os.path.join(prompt_dir, "plan_system_prompt.md")
        try:
            with open(prompt_path, encoding="utf-8") as f:
                planner_system = f.read().strip()
        except FileNotFoundError:
            self.agent.emit({"type": "plan_error", "data": "Planner prompt not found"})
            self.needs_plan = False
            return

        self.agent.emit({"type": "plan_start"})
        try:
            client = AsyncOpenAI(base_url=planner_provider, api_key=planner_key)
            response = await client.chat.completions.create(
                model=planner_model,
                messages=[
                    {"role": "system", "content": planner_system},
                    {"role": "user", "content": user_input},
                ],
                temperature=planner_temp,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            json_match = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            raw_json = json_match.group(1) if json_match else raw
            data = json.loads(raw_json)
        except Exception as exc:
            self.agent.emit({"type": "plan_error", "data": str(exc)})
            self.needs_plan = False
            return

        from plan import DAGPlan, DAGNode
        try:
            sub_tasks_raw = data.get("sub_tasks", [])
            if not sub_tasks_raw or len(sub_tasks_raw) <= 1:
                self.needs_plan = False
                return
            plan = DAGPlan(goal=data.get("goal", user_input))
            for st in sub_tasks_raw:
                plan.add_node(DAGNode(
                    id=st["id"], description=st["description"],
                    agent_hint=st.get("agent_hint", "any"),
                    depends_on=st.get("depends_on", []),
                ))
            self.current_plan = plan
            self.agent.current_plan = plan
            plan_block = (
                f"\n## Active Plan\n"
                f"You created a DAG-based plan. Work through sub-tasks respecting "
                f"dependencies. After each sub-task, call plan_advance with its "
                f"task_id and a summary of what you did.\n\n{plan.format_for_prompt()}"
            )
            self.agent.chat_history.append({"role": "meta", "content": plan_block})
            plan_advance = self.agent.tools.get("plan_advance")
            plan_status = self.agent.tools.get("plan_status")
            if plan_advance:
                plan_advance.agent_ref = self.agent
            if plan_status:
                plan_status.agent_ref = self.agent
            self.agent.emit({"type": "plan", "data": plan.format_for_prompt()})

            # Dispatch PLAN_CREATED hook
            await self.agent.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.PLAN_CREATED,
                    agent=self.agent,
                    timestamp=time.time(),
                    plan_data={"goal": data.get("goal", user_input), "tasks": sub_tasks_raw},
                )
            )
        except Exception as exc:
            self.agent.emit({"type": "plan_error", "data": str(exc)})
            self.needs_plan = False
            self.current_plan = None
            if hasattr(self.agent, 'current_plan'):
                self.agent.current_plan = None

    def _post_process_cleanup(self) -> None:
        """Clean up plan state after PROCESS completes."""
        if self.current_plan is not None:
            self.agent.emit({
                "type": "plan_complete",
                "data": self.current_plan.format_for_prompt(),
            })
            # Clear agent refs from plan tools
            plan_advance = self.agent.tools.get("plan_advance")
            plan_status = self.agent.tools.get("plan_status")
            if plan_advance:
                plan_advance.agent_ref = None
            if plan_status:
                plan_status.agent_ref = None
            self.agent.current_plan = None
            self.current_plan = None

    # ── memory ──────────────────────────────────────────────

    async def _try_memory_extraction(self) -> None:
        """Try to extract memory facts after a conversation round.

        Non‑fatal: failures are logged, never raised.
        """
        cfg = getattr(self.agent, "cfg", {})
        if not cfg.get("memory", {}).get("enabled", True):
            return

        try:
            from memory.fact import FactStore
            from memory.topic import TopicRegistry
            from memory.extractor import try_extract as _try_extract

            session_id = self.agent.session_id
            if not session_id:
                return

            import database as db
            messages = db.get_session_messages(session_id)
            current_round = self.agent._conversation_round

            store = FactStore()
            tr = TopicRegistry()
            # Use aux model if configured, otherwise main model
            llm_cfg = cfg.get("aux") or cfg.get("llm", {})

            await asyncio.to_thread(
                _try_extract,
                store, tr, messages,
                session_id, current_round, llm_cfg,
            )
        except Exception as e:
            from logger import get_logger as _gl
            _gl(__name__).warning("Memory extraction skipped: %s", e)

    # ── helpers ───────────────────────────────────────────

    async def _transition(self, stage: Stage) -> None:
        """Record a state change and dispatch hooks."""
        prev = self.stage
        self.previous_stage = prev
        self.stage = stage

        # Fire-and-forget: state transitions should not block
        await self.agent.hooks.dispatch_fire_and_forget(
            HookContext(
                event=HookEvent.STATE_ENTER,
                agent=self.agent,
                timestamp=time.time(),
                stage=stage.name.lower(),
                previous_stage=prev.name.lower(),
            )
        )
