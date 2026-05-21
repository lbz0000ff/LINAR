"""Agent orchestrator — explicit state machine around the LLM loop.

The multi-stage flow::

    IDLE → INGEST → ROUTE → [PLAN →] [PROCESS | DAG_EXECUTE] → COMPLETE → IDLE

``PLAN`` is conditional: ``_route()`` decides whether the input needs
decomposition into sub-tasks.  When a DAG plan exists with parallelizable
nodes, ``DAG_EXECUTE`` dispatches sub-tasks to independent agent instances.
"""

from __future__ import annotations

import json
import os
import re as _re

from enum import Enum, auto


class Stage(Enum):
    """All valid states the orchestrator can be in."""

    IDLE = auto()          # waiting for user input
    INGEST = auto()        # received input, storing
    ROUTE = auto()         # classify → decide which path
    PLAN = auto()          # decompose goal into sub-tasks (conditional)
    PROCESS = auto()       # LLM tool-calling loop
    DAG_EXECUTE = auto()   # DAG-driven parallel sub-agent execution
    SKILL_LOAD = auto()    # save state + swap prompt/tools
    SKILL_EXEC = auto()    # LLM tool-calling loop (skill mode)
    SKILL_UNLOAD = auto()  # restore pre-skill state
    COMPLETE = auto()      # finalizing turn
    ERROR = auto()         # unrecoverable error


# ── edge labels (used for logging / display) ────────────────

_STAGE_LABELS = {
    Stage.IDLE: "idle",
    Stage.INGEST: "ingest",
    Stage.ROUTE: "route",
    Stage.PLAN: "plan",
    Stage.PROCESS: "process",
    Stage.DAG_EXECUTE: "dag_execute",
    Stage.SKILL_LOAD: "skill_load",
    Stage.SKILL_EXEC: "skill_exec",
    Stage.SKILL_UNLOAD: "skill_unload",
    Stage.COMPLETE: "complete",
    Stage.ERROR: "error",
}


def stage_label(stage: Stage) -> str:
    return _STAGE_LABELS.get(stage, stage.name.lower())


# ── orchestrator ───────────────────────────────────────────

class Orchestrator:
    """State machine that wraps ``agent.process_with_llm()``.

    Usage in the terminal REPL::

        orch = Orchestrator(agent)
        orch.start(user_text)           # run the full state machine
        print(orch.stage)               # → Stage.IDLE
    """

    def __init__(self, agent) -> None:
        self.agent = agent
        self.stage: Stage = Stage.IDLE
        self.previous_stage: Stage | None = None
        self.current_plan = None  # DAGPlan instance, set during PLAN stage
        self.needs_plan: bool = False
        self.dag_executor_enabled: bool = True  # set False in tests to force single-agent mode

    # ── public API ────────────────────────────────────────

    def start(self, user_input: str) -> None:
        """Run a full turn through the state machine.

        Blocks until the agent produces a final answer (or errors out).
        Events are emitted through ``agent.emit()`` as before.
        """
        self._transition(Stage.INGEST)
        # Append queued BTW notes to the user input
        btw_notes = getattr(self.agent, 'consume_btw', lambda: [])()
        if btw_notes:
            user_input += "\n\n" + "\n".join(f"[BTW: {note}]" for note in btw_notes)
        self.agent.add_user_message(user_input)

        self._transition(Stage.ROUTE)
        self._route()

        if self.needs_plan:
            self._transition(Stage.PLAN)
            self._generate_plan()

        # ── DAG plan with parallel nodes → use DAGExecutor ──
        if self._should_execute_dag():
            self._transition(Stage.DAG_EXECUTE)
            self._execute_dag_plan()
            # DAG results were injected into chat_history as meta;
            # now let the LLM synthesize a final response for the user.
            self._transition(Stage.PROCESS)
            try:
                self.agent.process_with_llm()
            except Exception:
                self._transition(Stage.ERROR)
                raise
        else:
            self._transition(Stage.PROCESS)
            try:
                self.agent.process_with_llm()
            except Exception:
                self._transition(Stage.ERROR)
                raise

        self._post_process_cleanup()

        self._transition(Stage.COMPLETE)
        self._transition(Stage.IDLE)

    def run_skill(self, skill, user_input: str) -> None:
        """Run a skill: save state → swap prompt/tools → LLM loop → restore.

        When ``skill.context == "fork"``, the skill runs in an isolated
        subagent so the main agent's chat history and tool state are not
        affected.

        Blocks until the skill produces a final answer (or errors out).
        """
        if getattr(skill, "context", "") == "fork":
            self._run_skill_forked(skill, user_input)
            return

        self._transition(Stage.SKILL_LOAD)
        skill.on_load(self.agent)
        # Remind the model that the skill is already active, so it
        # doesn't try to call skill_view again on its own.
        self.agent.chat_history.append({
            "role": "meta",
            "content": (
                f"[SYSTEM] Skill /{skill.name} is now active. "
                f"Follow the skill's instructions directly. "
                f"Do NOT call skill_view — you are already in the skill context."
            ),
        })
        self.agent.add_user_message(user_input)

        self._transition(Stage.SKILL_EXEC)
        try:
            self.agent.process_with_llm()
        except Exception:
            self._transition(Stage.ERROR)
            skill.on_unload(self.agent)
            raise

        self._transition(Stage.SKILL_UNLOAD)
        skill.on_unload(self.agent)

        self._transition(Stage.COMPLETE)
        self._transition(Stage.IDLE)

    def _run_skill_forked(self, skill, user_input: str) -> None:
        """Run a skill in an isolated subagent (context: fork).

        Creates a fresh Agent, applies the skill's prompt/tools, runs
        the user input, and streams the result back to the main agent's
        output.
        """
        from agent_factory import create_agent
        from agent import Agent

        self._transition(Stage.SKILL_LOAD)
        self.agent.emit({"type": "skill_fork", "data": skill.name})

        # Create a subagent with all tools (on_load will filter)
        try:
            from tool_registry import get_tools
            sub_cfg = self.agent.cfg
            enabled = sub_cfg.get("tools", {}).get("enabled_sets", None)
            sub_tools = get_tools(enabled)
            sub_agent = Agent(tools=sub_tools)
        except Exception as exc:
            self.agent.emit({"type": "error", "data": f"Failed to fork agent: {exc}"})
            self._transition(Stage.COMPLETE)
            self._transition(Stage.IDLE)
            return

        # Wire up emit to the main agent so output appears in the TUI
        sub_agent.emit = self.agent.emit
        # Share stop_event so interrupt propagates
        sub_agent.stop_event = self.agent.stop_event
        for t in sub_agent.tools.values():
            if hasattr(t, 'stop_event'):
                t.stop_event = sub_agent.stop_event

        # Apply skill on_load to subagent
        skill.on_load(sub_agent)
        sub_agent.add_user_message(user_input)

        self._transition(Stage.SKILL_EXEC)
        try:
            sub_agent.process_with_llm()
        except Exception:
            self._transition(Stage.ERROR)
            skill.on_unload(sub_agent)
            raise

        self._transition(Stage.SKILL_UNLOAD)
        skill.on_unload(sub_agent)

        # Collect the subagent's final answer
        result_text = ""
        for msg in reversed(sub_agent.chat_history):
            if msg.get("role") == "agent":
                result_text = msg.get("content", "")
                break

        self._transition(Stage.COMPLETE)
        self._transition(Stage.IDLE)

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

        # Multi-step indicators — conjunctions that join multiple actions
        multi_step_keywords = [
            " and ", " then ", " first ", " finally ",
            "first,", "second,", "1.", "2.",
            # Chinese
            "然后", "接着", "步骤", "并",
            "第一步", "第二步", "首先", "其次",
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

    def _execute_dag_plan(self) -> None:
        """Execute the current DAGPlan via DAGExecutor with parallel sub-agents.

        Each sub-task is dispatched to a fresh Agent instance with its own
        tools and LLM.  Predecessor results are passed as context.
        """
        from executor import DAGExecutor
        from agent_factory import create_agent, run_task as run_agent_task

        plan = self.current_plan
        if plan is None:
            return

        self.agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})
        agent_results: dict[str, str] = {}

        def _node_runner(node_id: str, description: str) -> str:
            node = plan.nodes.get(node_id)
            hint = node.agent_hint if node else "any"
            deps = {d: agent_results[d] for d in (node.depends_on if node else [])
                    if d in agent_results}

            agent = create_agent(agent_hint=hint, predecessor_results=deps,
                                 stop_event=getattr(self.agent, 'stop_event', None))
            self.agent.emit({
                "type": "dag_node_start",
                "data": {"id": node_id, "hint": hint, "description": description},
            })
            result = run_agent_task(agent, description, hint, deps)
            self.agent.emit({
                "type": "dag_node_complete",
                "data": {"id": node_id, "result": result[:200]},
            })
            agent_results[node_id] = result
            return result

        executor = DAGExecutor(plan, runner=_node_runner,
                               interrupt_check=lambda: getattr(self.agent, 'stop_event', None) is not None
                               and self.agent.stop_event.is_set())
        try:
            all_results = executor.execute_all()
        except Exception as exc:
            self.agent.emit({"type": "plan_error", "data": str(exc)})
            return

        # ── build a summary of all results ──
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
            f"All sub-tasks have been executed. Here are the results:\n\n"
            f"{summary}"
        )
        self.agent.chat_history.append({
            "role": "meta",
            "content": plan_block,
        })
        self.agent.emit({"type": "plan_complete", "data": summary})

    def _generate_plan(self) -> None:
        """Call the LLM to decompose the user's goal into sub-tasks."""
        from openai import OpenAI

        cfg = self.agent.cfg
        user_input = self.agent.chat_history[-1]["content"]

        # Use aux model config if available, fall back to main llm
        aux_cfg = cfg.get("aux") or {}
        planner_provider = aux_cfg.get("base_url") or cfg["llm"]["base_url"]
        planner_key = aux_cfg.get("api_key") or cfg["llm"]["api_key"]
        planner_model = aux_cfg.get("model") or cfg["llm"]["model"]
        planner_temp = aux_cfg.get("temperature") or 0.3

        # Load planner system prompt
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
            client = OpenAI(
                base_url=planner_provider,
                api_key=planner_key,
            )
            response = client.chat.completions.create(
                model=planner_model,
                messages=[
                    {"role": "system", "content": planner_system},
                    {"role": "user", "content": user_input},
                ],
                temperature=planner_temp,
                max_tokens=2000,
            )

            raw = response.choices[0].message.content.strip()
            # Extract JSON from markdown code block or plain text
            json_match = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            if json_match:
                raw_json = json_match.group(1)
            else:
                raw_json = raw
            data = json.loads(raw_json)

        except Exception as exc:
            self.agent.emit({"type": "plan_error", "data": str(exc)})
            self.needs_plan = False
            return

        # Build DAG plan from LLM response
        from plan import DAGPlan, DAGNode, DAGNodeStatus

        try:
            sub_tasks_raw = data.get("sub_tasks", [])
            if not sub_tasks_raw or len(sub_tasks_raw) <= 1:
                # Single sub-task → no plan needed
                self.needs_plan = False
                return

            plan = DAGPlan(goal=data.get("goal", user_input))
            for st in sub_tasks_raw:
                plan.add_node(DAGNode(
                    id=st["id"],
                    description=st["description"],
                    agent_hint=st.get("agent_hint", "any"),
                    depends_on=st.get("depends_on", []),
                ))
            self.current_plan = plan
            self.agent.current_plan = plan

            # Inject plan into chat_history for LLM visibility
            plan_block = (
                f"\n## Active Plan\n"
                f"You created a DAG-based plan. Work through sub-tasks respecting "
                f"dependencies. After each sub-task, call plan_advance with its "
                f"task_id and a summary of what you did.\n\n"
                f"{plan.format_for_prompt()}"
            )
            self.agent.chat_history.append({
                "role": "meta",
                "content": plan_block,
            })

            # Wire up plan tools with agent reference
            plan_advance = self.agent.tools.get("plan_advance")
            plan_status = self.agent.tools.get("plan_status")
            if plan_advance:
                plan_advance.agent_ref = self.agent
            if plan_status:
                plan_status.agent_ref = self.agent

            self.agent.emit({"type": "plan", "data": plan.format_for_prompt()})
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

    # ── helpers ───────────────────────────────────────────

    def _transition(self, stage: Stage) -> None:
        """Record a state change."""
        self.previous_stage = self.stage
        self.stage = stage
