"""Plan tools — track progress through decomposed sub-tasks."""

import asyncio
import json
import os
from typing import Any

from plan import DAGNodeStatus

from .tool import Tool


class Tool_PlanAdvance(Tool):
    """Mark a sub-task as complete and check what's now ready."""

    name: str = "plan_advance"
    description: str = (
        "Mark a sub-task as completed. Provide the task_id of the sub-task "
        "you just finished and a brief summary of what was accomplished. "
        "The system will respond with which sub-tasks are now ready to work on."
    )
    tool_schema: dict = {
        "name": "plan_advance",
        "description": (
            "Mark a sub-task as completed and advance the plan. "
            "Provide the task_id of the finished sub-task and a summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the sub-task that was just completed",
                },
                "result_summary": {
                    "type": "string",
                    "description": "Brief summary of what was accomplished",
                },
            },
            "required": ["task_id", "result_summary"],
        },
    }

    # Set by orchestrator when a plan is active
    agent_ref: Any = None

    def execute(self, task_id: str = "", result_summary: str = "") -> str:
        agent = self.agent_ref
        if agent is None or agent.current_plan is None:
            return "No active plan."

        plan = agent.current_plan

        # Check DAGPlan interface
        if not hasattr(plan, "nodes"):
            return "Current plan does not support task_id-based advancement."
        if task_id not in plan.nodes:
            return f"Unknown task_id: {task_id}"

        node = plan.nodes[task_id]
        if node.status != DAGNodeStatus.PENDING:
            return f"Task '{task_id}' cannot be advanced (status: {node.status.name})"

        node.status = DAGNodeStatus.COMPLETED
        node.result = result_summary

        ready = plan.get_ready()

        # Inject updated plan into chat_history for next LLM turn
        if plan.is_complete:
            plan_block = (
                f"\n[PLAN UPDATE]\n"
                f"Completed: {task_id} — {result_summary}\n"
                f"\nAll sub-tasks complete!"
            )
        else:
            ready_desc = ", ".join(
                f"{r.id} ({r.description})" for r in ready
            )
            plan_block = (
                f"\n[PLAN UPDATE]\n"
                f"Completed: {task_id} — {result_summary}\n"
                f"Ready: {ready_desc}\n"
                f"{plan.format_for_prompt()}"
            )

        agent.chat_history.append({
            "role": "meta",
            "content": plan_block,
        })

        if plan.is_complete:
            return (
                f"Completed: {node.description}\n"
                f"Result: {result_summary}\n"
                f"All sub-tasks complete! The plan is finished."
            )
        else:
            ready_names = ", ".join(r.id for r in ready)
            return (
                f"Completed: {node.description}\n"
                f"Result: {result_summary}\n"
                f"Now ready: {ready_names}"
            )


class Tool_PlanStatus(Tool):
    """Show the current state of the task plan."""

    name: str = "plan_status"
    description: str = (
        "Show the current task plan and progress on sub-tasks. "
        "Use this to remind yourself what still needs to be done."
    )
    tool_schema: dict = {
        "name": "plan_status",
        "description": "Display the current task plan with progress on each sub-task.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    }

    # Set by orchestrator when a plan is active
    agent_ref: Any = None

    def execute(self) -> str:
        agent = self.agent_ref
        if agent is None or agent.current_plan is None:
            return "No active plan."
        return agent.current_plan.format_for_prompt()


class SubmitOutputTool(Tool):
    """DAG sub-task result submission tool.

    Injected into every subagent created by ``_run_node``.  The subagent
    calls this ONCE when done, and ``_run_node`` reads ``_submission``
    afterward — no more fragile text-JSON parsing.

    The schema covers output from all subagent types (web_researcher,
    analyst, critic).  Each type fills the fields relevant to its role;
    the tool schema itself serves as the output contract — no separate
    "Output Format" docs needed in agent_type files.
    """

    name: str = "submit_output"
    description: str = (
        "Submit your completed work. Call this ONCE when your task is finished. "
        "Fill in the fields relevant to your role — others can be left out."
    )
    tool_schema: dict = {
        "name": "submit_output",
        "description": "Submit your completed work. Call ONCE when done.",
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "description": "Research findings (for web_researcher)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "angle": {"type": "string", "description": "Which search angle"},
                            "text": {"type": "string", "description": "Specific finding with data and facts"},
                            "source": {"type": "string", "description": "Full source URL"},
                            "source_title": {"type": "string", "description": "Page title"},
                            "confidence": {
                                "type": "string", "enum": ["high", "medium", "low"],
                            },
                        },
                    },
                },
                "gaps": {
                    "type": "array",
                    "description": "Knowledge gaps or questions not covered",
                    "items": {"type": "string"},
                },
                "sources": {
                    "type": "array",
                    "description": "All source URLs referenced",
                    "items": {"type": "string"},
                },
                "contradictions": {
                    "type": "array",
                    "description": "Contradictions detected between sources (for analyst)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_a": {"type": "string"},
                            "source_a": {"type": "string"},
                            "claim_b": {"type": "string"},
                            "source_b": {"type": "string"},
                            "resolution": {"type": "string"},
                        },
                    },
                },
                "verdicts": {
                    "type": "array",
                    "description": "Quality verdicts per finding (for critic)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding": {"type": "string", "description": "Original finding text"},
                            "verdict": {
                                "type": "string",
                                "enum": ["verified", "refuted", "uncertain"],
                            },
                            "evidence": {"type": "string"},
                            "source": {"type": "string"},
                            "confidence_after_review": {
                                "type": "string", "enum": ["high", "medium", "low"],
                            },
                            "note": {"type": "string"},
                        },
                    },
                },
                "coverage_score": {
                    "type": "number",
                    "description": "Coverage estimate 0.0-1.0 (for analyst)",
                },
                "next_wave_suggestions": {
                    "type": "array",
                    "description": "Recommended next directions (for analyst)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "direction": {"type": "string"},
                            "rationale": {"type": "string"},
                            "suggested_angles": {
                                "type": "array", "items": {"type": "string"},
                            },
                        },
                    },
                },
                "overall_assessment": {
                    "type": "string",
                    "description": "Overall quality assessment (for critic)",
                },
                "assets": {
                    "type": "array",
                    "description": "Auxiliary files created (diagrams, screenshots)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
    agent_ref: Any = None

    def execute(self, **kwargs) -> str:
        self.agent_ref._submission = {
            "findings": kwargs.get("findings") or [],
            "gaps": kwargs.get("gaps") or [],
            "sources": kwargs.get("sources") or [],
            "contradictions": kwargs.get("contradictions") or [],
            "verdicts": kwargs.get("verdicts") or [],
            "coverage_score": kwargs.get("coverage_score"),
            "next_wave_suggestions": kwargs.get("next_wave_suggestions") or [],
            "overall_assessment": kwargs.get("overall_assessment"),
            "assets": kwargs.get("assets") or [],
        }
        return "SUBMITTED: Result recorded."


class Tool_CreatePlan(Tool):
    """Signal the orchestrator to enter PLAN → DAG_EXECUTE flow."""

    name: str = "create_plan"
    description: str = (
        "Submit a multi-step task plan for parallel execution. "
        "The orchestrator will schedule sub-tasks as a DAG, run them, "
        "and return results. Use this when the task has clear sub-steps "
        "that can benefit from parallel execution."
    )
    tool_schema: dict = {
        "name": "create_plan",
        "description": "Submit a plan for parallel DAG execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Overall goal of the plan.",
                },
                "sub_tasks": {
                    "type": "array",
                    "description": "List of sub-tasks to execute.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique task ID"},
                            "description": {"type": "string", "description": "What this sub-task does"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "IDs of tasks that must complete first",
                            },
                            "agent_hint": {
                                "type": "string",
                                "description": "Toolset hint: any/code/shell/analysis/research",
                            },
                            "agent": {
                                "type": "string",
                                "description": "Predefined subagent type to use (web_researcher/analyst/critic). When set, loads agent_types/{agent}.md for prompt + model. Mutually optional with agent_hint — if both given, agent wins.",
                            },
                            "params": {
                                "type": "object",
                                "description": "Task parameters filled into the subagent's prompt template (e.g. task_description, angles). Only used when agent is set.",
                            },
                        },
                        "required": ["id", "description"],
                    },
                },
            },
            "required": ["goal", "sub_tasks"],
        },
    }

    agent_ref: Any = None

    async def execute(self, goal: str = "", sub_tasks: list | None = None) -> str:
        """Execute plan: build DAG, run sub-agents, return results."""
        agent = self.agent_ref
        if agent is None:
            return "Error: no agent reference."
        if not sub_tasks:
            return "Error: no sub-tasks provided."

        from plan import DAGPlan, DAGNode
        from executor import DAGExecutor
        from agent_factory import create_agent, run_task as run_agent_task

        # Build DAGPlan
        plan = DAGPlan(goal=goal)
        _sub_meta: dict[str, dict] = {}   # node_id → extra fields
        for st in sub_tasks:
            plan.add_node(DAGNode(
                id=st["id"], description=st["description"],
                agent_hint=st.get("agent_hint", "any"),
                depends_on=st.get("depends_on", []),
            ))
            # Stash agent/params for _run_node
            _sub_meta[st["id"]] = {
                "agent": st.get("agent"),
                "params": st.get("params"),
            }

        agent.emit({"type": "plan_start"})
        agent.emit({"type": "plan", "data": plan.format_for_prompt()})
        agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})

        # Execute DAG
        agent_results: dict[str, str] = {}
        workspace_root = getattr(agent, "_workspace_root", None)

        async def _run_node(node_id: str, description: str) -> str:
            node = plan.nodes.get(node_id)
            hint = node.agent_hint if node else "any"
            deps = {
                d: agent_results[d]
                for d in (node.depends_on if node else [])
                if d in agent_results
            }
            meta = _sub_meta.get(node_id, {})
            agent_type = meta.get("agent")
            params = meta.get("params") or {}

            # ── Resolve model: params.model > subagent definition > inherit ──
            sub_model = None

            if agent_type:
                # ── Load predefined subagent ──
                from subagent import load_subagent, render_prompt

                defn = load_subagent(agent_type)
                if defn is None:
                    return f"Error: subagent type '{agent_type}' not found."

                # Override hint from definition
                if defn.get("hint"):
                    hint = defn["hint"]

                # Build system prompt from template
                rendered = render_prompt(defn, params)
                sub_model = defn.get("model")
                sub_provider = defn.get("provider")

                # Build user message with predecessor context
                user_msg = (
                    f"## Task\n{description}\n\n"
                    f"Follow the system prompt. "
                    f"Call submit_output() when you have completed the task."
                )
                if deps:
                    user_msg += "\n\n## Predecessor Results\n" + "\n".join(
                        f"  [{d}] {deps[d][:300]}" for d in deps
                    )
            else:
                # ── Legacy path: free-form description ──
                rendered = None
                sub_provider = None
                user_msg = description
                if hint and hint != "any":
                    user_msg = f"Your role: {hint}\n{description}"
                if deps:
                    user_msg += "\n\nPredecessor results:\n" + "\n".join(
                        f"  [{d}] {deps[d][:200]}" for d in deps
                    )

            sub_agent = create_agent(
                agent_hint=hint, predecessor_results=deps,
                stop_event=agent.stop_event,
                workspace_root=workspace_root,
                model=sub_model,
                system_prompt=rendered,
                provider=sub_provider if agent_type else None,
            )

            # ── Inject submit_output tool (all DAG sub-tasks) ──
            submit_tool = SubmitOutputTool()
            submit_tool.agent_ref = sub_agent
            sub_agent.tools["submit_output"] = submit_tool
            sub_agent.llm.tools["submit_output"] = submit_tool

            # ── Apply allowed-tools filter if subagent defines one ──
            # submit_output is injected BEFORE the filter, so it survives
            # only when explicitly listed in the agent_type's allowed-tools.
            if agent_type:
                at = defn.get("allowed_tools")
                if at is not None:
                    filtered = {}
                    for k, v in sub_agent.tools.items():
                        if k.startswith("mcp_") or k in at:
                            filtered[k] = v
                    sub_agent.tools = filtered
                    sub_agent.llm.tools = filtered

            deps_list = node.depends_on if node else []
            agent.emit({"type": "dag_node_start", "data": {
                "id": node_id, "hint": hint, "description": description,
                "depends_on": deps_list,
                "agent": agent_type,
            }})

            # Run the sub-agent. Research-style predefined agents usually
            # need more tool/result/follow-up turns than generic subtasks.
            cfg = getattr(agent, "cfg", {}) or {}
            default_limit = cfg.get("sub_agent_max_llm_calls", 20)
            if agent_type:
                default_limit = cfg.get(
                    "research_sub_agent_max_llm_calls",
                    max(default_limit, 40),
                )
            sub_agent.max_llm_calls = default_limit
            await sub_agent.add_user_message(user_msg)
            await sub_agent.process_with_llm()

            # ── Collect results (three-tier fallback) ──
            #   1. submit_output tool → _submission
            #   2. (agent_type) fallback: _collect_agent_output + _try_parse_json
            #   3. (legacy) fallback: _collect_agent_output
            parsed: dict | None = None
            result: str | None = None
            submission = getattr(sub_agent, "_submission", None)

            if agent_type and submission is not None:
                # Structured submission (via submit_output tool)
                if isinstance(submission, dict):
                    result = json.dumps(submission, ensure_ascii=False)
                    if workspace_root:
                        self._write_research_state(workspace_root, node_id, submission)
                else:
                    # String fallback (e.g. legacy subagent used submit_output with string)
                    result = str(submission)
                    parsed = self._try_parse_json(result) if result else None
                    if parsed and workspace_root:
                        self._write_research_state(workspace_root, node_id, parsed)
            elif agent_type:
                result = self._collect_agent_output(sub_agent, agent_type)
                parsed = self._try_parse_json(result) if result else None
                if parsed and workspace_root:
                    self._write_research_state(workspace_root, node_id, parsed)
            else:
                # legacy path — no agent_type
                if submission is not None:
                    result = json.dumps(submission, ensure_ascii=False) if isinstance(submission, dict) else str(submission)
                else:
                    result = self._collect_agent_output(sub_agent, None)

            if result is None:
                result = "[no output]"

            agent.emit({"type": "dag_node_complete", "data": {
                "id": node_id, "result": result[:200],
            }})
            agent_results[node_id] = result
            return result

        executor = DAGExecutor(
            plan, runner=None,
            interrupt_check=lambda: agent.stop_event.is_set(),
        )

        # ── Per-provider concurrency gate ──
        # Pre-resolve each node's provider so we can limit parallel
        # requests to rate-limited providers (e.g. StepFun V0: 5 concurrent).
        _node_provider: dict[str, str | None] = {}
        for nid, meta in _sub_meta.items():
            atype = meta.get("agent")
            if atype:
                from subagent import load_subagent
                defn = load_subagent(atype)
                _node_provider[nid] = defn.get("provider") if defn else None

        # Max concurrent sub-agents per provider (tune per your API tier)
        _PROVIDER_MAX_CONCURRENT = {"stepfun": 3}
        _provider_sems: dict[str, asyncio.Semaphore] = {}

        async def _gated_run(node_id: str, description: str) -> str:
            provider = _node_provider.get(node_id)
            max_conc = _PROVIDER_MAX_CONCURRENT.get(provider, 0) if provider else 0
            if max_conc:
                sem = _provider_sems.setdefault(
                    provider, asyncio.Semaphore(max_conc))
                async with sem:
                    return await _run_node(node_id, description)
            return await _run_node(node_id, description)

        try:
            all_results = await executor.execute_all_async(_gated_run)
        except Exception as exc:
            return f"Error during plan execution: {exc}"

        # Build summary — include research_state.json status if present
        try:
            order = plan.topological_sort()
        except Exception:
            order = list(plan.nodes.keys())
        parts = []
        for nid in order:
            node = plan.nodes[nid]
            result = all_results.get(nid, "[no result]")
            status = node.status.value
            parts.append(f"[{status}] {nid}: {node.description}\n{result[:300]}")
        summary = "\n\n".join(parts)

        # If research_state.json exists, mention it
        if workspace_root:
            state_path = os.path.join(workspace_root, "research_state.json")
            if os.path.isfile(state_path):
                summary += (
                    f"\n\n📋 Structured research state saved to `research_state.json`. "
                    f"Read it for all findings."
                )

        agent.emit({"type": "plan_complete", "data": summary})
        return (
            f"## DAG Execution Complete\n"
            f"All sub-tasks have been executed. Here are the results:\n\n{summary}"
        )


# ── helpers on Tool_CreatePlan ─────────────────────────────

    @staticmethod
    def _collect_agent_output(sub_agent, agent_type: str | None) -> str:
        """Collect the best output from a finished sub-agent.

        Priority when ``agent_type`` is set (structured path):
          1. Last ``role == "agent"`` message (expected JSON)
          2. Fallback: last ``role == "tool"`` messages

        Legacy path (no ``agent_type``):
          Only tool messages (existing behaviour).
        """
        if agent_type:
            # Prefer the final agent text (contains structured output)
            for msg in reversed(sub_agent.chat_history):
                if msg.get("role") == "agent" and msg.get("content", "").strip():
                    return str(msg["content"]).strip()

        # Fallback / legacy: collect tool result messages
        lines = []
        for msg in sub_agent.chat_history:
            if msg.get("role") == "tool":
                r = msg.get("result", "")
                if isinstance(r, dict):
                    r = json.dumps(r, ensure_ascii=False)
                r = str(r)[:500]
                if r.strip():
                    lines.append(r)
        return "\n".join(lines[-8:]) or "[no output]"

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Try to extract a JSON object from *text*.

        Handles cases where the model wraps JSON in markdown fences or
        prepends a short preamble.
        """
        import re

        # Strip markdown code fences
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()

        # Find the first '{' ... last '}' span
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _write_research_state(workspace_root: str, node_id: str,
                              parsed: dict) -> None:
        """Append structured findings to ``research_state.json``."""
        import os

        state_path = os.path.join(workspace_root, "research_state.json")
        state: dict = {"findings": [], "contradictions": [], "gaps": [],
                        "sources": [], "assets": [], "meta": {}}

        if os.path.isfile(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                state.update(existing)
            except (OSError, json.JSONDecodeError):
                pass

        # Merge findings (dedup by text + source)
        existing = {(f.get("text", ""), f.get("source", ""))
                     for f in state["findings"]}
        for f in parsed.get("findings", []):
            if isinstance(f, dict):
                key = (f.get("text", ""), f.get("source", ""))
                if key not in existing:
                    existing.add(key)
                    f.setdefault("node", node_id)
                    state["findings"].append(f)

        # Merge contradictions
        for c in parsed.get("contradictions", []):
            if isinstance(c, dict):
                state["contradictions"].append(c)

        # Merge gaps
        for g in parsed.get("gaps", []):
            if isinstance(g, str):
                state["gaps"].append(g)
            elif isinstance(g, dict):
                state["gaps"].append(g.get("description", str(g)))

        # Merge sources
        for s in parsed.get("sources", []):
            if s not in state["sources"]:
                state["sources"].append(s)

        # Merge assets (auxiliary files: diagrams, screenshots, charts)
        state.setdefault("assets", [])
        for a in parsed.get("assets", []):
            if isinstance(a, dict) and a not in state["assets"]:
                a.setdefault("node", node_id)
                state["assets"].append(a)

        # Merge non-list top-level keys as meta
        for key in ("coverage_score", "next_wave_suggestions",
                     "overall_assessment", "critical_gaps", "verdicts",
                     "merged_findings"):
            if key in parsed and key not in ("findings", "contradictions",
                                               "gaps", "sources"):
                state["meta"][key] = parsed[key]

        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
