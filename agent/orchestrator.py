"""Agent orchestrator — explicit state machine around the LLM loop.

The multi-stage flow::

    IDLE → INGEST → ROUTE → [PLAN →] PROCESS → COMPLETE → IDLE

``PLAN`` is conditional: ``_route()`` decides whether the input needs
decomposition into sub-tasks.  Future states can be added by extending
``Stage`` and adding a branch in ``_route()``.
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

        Blocks until the skill produces a final answer (or errors out).
        """
        self._transition(Stage.SKILL_LOAD)
        skill.on_load(self.agent)
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
            "然后", "接着", "步骤",
            "第一步", "第二步", "首先", "其次",
        ]
        kw_matches = sum(1 for kw in multi_step_keywords if kw in user_input.lower())
        self.needs_plan = kw_matches >= (3 if len(user_input) <= 20 else 2)

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
