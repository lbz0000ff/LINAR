"""Plan generation, DAG execution, and cleanup.

The single owner of ``current_plan`` — synchronises with ``agent.current_plan``.
"""
from __future__ import annotations

import json
import os
import re as _re
from typing import Any

from logger import get_logger as _get_logger
from plan import DAGNode, DAGPlan

log = _get_logger(__name__)


class PlanExecutor:
    """Plan generation, DAG execution, and cleanup.

    Usage from Orchestrator::

        plan_exec = PlanExecutor(agent, hook_factory)
        ok = await plan_exec.generate(user_input)
        if plan_exec.should_execute_dag(enabled=True):
            await plan_exec.execute_dag()
        plan_exec.cleanup()
    """

    def __init__(self, agent, hook_factory) -> None:
        self._agent = agent
        self._hooks = hook_factory
        self.current_plan: DAGPlan | None = None

    # ── Plan generation ──────────────────────────────────────

    async def generate(self, user_input: str) -> bool:
        """Build a DAGPlan from the agent's ``_pending_plan`` data.

        The ``create_plan`` tool sets ``agent._pending_plan = (goal, sub_tasks)``.
        This method reads that data, constructs a ``DAGPlan``, and clears
        the flag.  No separate planner LLM is called.

        Returns ``True`` if a plan with ≥2 nodes was created.
        """
        pending = getattr(self._agent, "_pending_plan", None)
        if pending is None:
            return False
        goal, sub_tasks_raw = pending
        self._agent._pending_plan = None

        if not sub_tasks_raw or len(sub_tasks_raw) <= 1:
            return False

        try:
            plan = DAGPlan(goal=goal or user_input)
            for st in sub_tasks_raw:
                plan.add_node(DAGNode(
                    id=st["id"],
                    description=st["description"],
                    agent_hint=st.get("agent_hint", "any"),
                    depends_on=st.get("depends_on", []),
                ))
            self._set_plan(plan)
            self._inject_plan_into_history(plan)
            self._bind_plan_tools()
            await self._hooks.plan_created(
                goal=goal or user_input,
                tasks=sub_tasks_raw,
            )
            return True
        except Exception as exc:
            self._agent.emit({"type": "plan_error", "data": str(exc)})
            self._clear_plan()
            return False

    # ── DAG execution ────────────────────────────────────────

    def should_execute_dag(self, *, enabled: bool) -> bool:
        """Return ``True`` if the current plan should run via DAGExecutor."""
        if not enabled:
            return False
        plan = self.current_plan
        if plan is None:
            return False
        nodes = list(plan.nodes.values())
        if len(nodes) < 2:
            return False
        ready = plan.get_ready()
        if len(ready) > 1:
            return True
        return len(nodes) > 2

    async def execute_dag(self) -> None:
        """Execute ``self.current_plan`` via DAGExecutor.

        Injects the execution summary into ``chat_history`` and
        emits a ``plan_complete`` event.
        """
        plan = self.current_plan
        if plan is None:
            return

        from executor import DAGExecutor
        from agent_factory import create_agent, run_task as run_agent_task

        self._agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})
        agent_results: dict[str, str] = {}

        async def _node_runner(node_id: str, description: str) -> str:
            node = plan.nodes.get(node_id)
            hint = node.agent_hint if node else "any"
            deps = {
                d: agent_results[d]
                for d in (node.depends_on if node else [])
                if d in agent_results
            }
            sub_agent = create_agent(
                agent_hint=hint,
                predecessor_results=deps,
                stop_event=self._agent.stop_event,
                workspace_root=getattr(self._agent, "_workspace_root", None),
            )

            await self._hooks.plan_node_start(node_id, hint, description)
            node_deps = node.depends_on if (node := plan.nodes.get(node_id)) else []
            self._agent.emit({
                "type": "dag_node_start",
                "data": {
                    "id": node_id, "hint": hint, "description": description,
                    "depends_on": node_deps,
                },
            })

            result = await run_agent_task(sub_agent, description, hint, deps)

            await self._hooks.plan_node_complete(node_id, result[:200], hint, description)
            self._agent.emit({
                "type": "dag_node_complete",
                "data": {"id": node_id, "result": result[:200]},
            })
            agent_results[node_id] = result
            return result

        executor = DAGExecutor(
            plan,
            runner=None,
            interrupt_check=lambda: self._agent.stop_event.is_set(),
        )
        try:
            all_results = await executor.execute_all_async(_node_runner)
        except Exception as exc:
            self._agent.emit({"type": "plan_error", "data": str(exc)})
            return

        summary = self._build_summary(plan, all_results)
        plan_block = (
            f"\n## DAG Execution Complete\n"
            f"All sub-tasks have been executed. Here are the results:\n\n{summary}"
        )
        self._agent.chat_history.append({"role": "meta", "content": plan_block})
        # Persist to DB so the results survive restart/session switch
        try:
            import database as db
            db.save_message(
                session_id=self._agent.session_id,
                role="meta",
                content=plan_block,
                conversation_round=self._agent._conversation_round,
            )
        except Exception:
            pass  # non-fatal; in-memory chat_history is sufficient at runtime
        self._agent.emit({"type": "plan_complete", "data": summary})

    # ── Cleanup ──────────────────────────────────────────────

    def cleanup(self) -> None:
        """Emit ``plan_complete``, unbind plan tool refs, clear state."""
        if self.current_plan is not None:
            self._agent.emit({
                "type": "plan_complete",
                "data": self.current_plan.format_for_prompt(),
            })
            self._unbind_plan_tools()
            self._clear_plan()

    # ── Internal helpers ─────────────────────────────────────

    def _prompt_path(self) -> str:
        """Resolve path to ``agent/prompt/plan_system_prompt.md``."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "prompt", "plan_system_prompt.md")

    def _set_plan(self, plan: DAGPlan) -> None:
        self.current_plan = plan
        self._agent.current_plan = plan
        self._agent.emit({"type": "plan", "data": plan.format_for_prompt()})
        # Emit structured node data with dependencies for GUI hierarchy
        nodes_data = [
            {
                "id": n.id,
                "description": n.description,
                "depends_on": n.depends_on,
                "hint": n.agent_hint,
                "status": n.status.value,
            }
            for n in plan.nodes.values()
        ]
        self._agent.emit({"type": "plan_nodes", "data": nodes_data})

    def _clear_plan(self) -> None:
        self.current_plan = None
        if hasattr(self._agent, "current_plan"):
            self._agent.current_plan = None

    def _inject_plan_into_history(self, plan: DAGPlan) -> None:
        block = (
            f"\n## Active Plan\n"
            f"You created a DAG-based plan. Work through sub-tasks respecting "
            f"dependencies. After each sub-task, call plan_advance with its "
            f"task_id and a summary of what you did.\n\n{plan.format_for_prompt()}"
        )
        self._agent.chat_history.append({"role": "meta", "content": block})
        try:
            import database as db
            db.save_message(
                session_id=self._agent.session_id,
                role="meta",
                content=block,
                conversation_round=self._agent._conversation_round,
            )
        except Exception:
            pass

    def _bind_plan_tools(self) -> None:
        pa = self._agent.tools.get("plan_advance")
        ps = self._agent.tools.get("plan_status")
        if pa:
            pa.agent_ref = self._agent
        if ps:
            ps.agent_ref = self._agent

    def _unbind_plan_tools(self) -> None:
        pa = self._agent.tools.get("plan_advance")
        ps = self._agent.tools.get("plan_status")
        if pa:
            pa.agent_ref = None
        if ps:
            ps.agent_ref = None

    @staticmethod
    def _build_summary(plan: DAGPlan, results: dict[str, str]) -> str:
        try:
            order = plan.topological_sort()
        except Exception:
            order = list(plan.nodes.keys())
        parts = []
        for nid in order:
            node = plan.nodes[nid]
            result = results.get(nid, "[no result]")
            status = node.status.value
            parts.append(f"[{status}] {nid}: {node.description}\n{result[:300]}")
        return "\n\n".join(parts)
