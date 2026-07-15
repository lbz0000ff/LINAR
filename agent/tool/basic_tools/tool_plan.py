"""Plan tools — track progress through decomposed sub-tasks."""

import asyncio
import copy
import json
import os
import time
from datetime import date
from typing import Any

from plan import DAGNodeStatus

from .tool import Tool


class Tool_PlanAdvance(Tool):
    """[DISCARDED]Mark a sub-task as complete and check what's now ready."""

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
    """[DISCARDED]Show the current state of the task plan."""

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
                "status": {
                    "type": "string",
                    "enum": ["completed", "partial", "blocked"],
                    "description": "Completion state for the subtask handoff",
                },
                "summary": {
                    "type": "string",
                    "description": "Concise result for downstream nodes",
                },
                "unresolved": {
                    "type": "array",
                    "description": "Incomplete or unverified items",
                    "items": {"type": "string"},
                },
                "artifacts": {
                    "type": "array",
                    "description": "Files or other deliverables created by the subtask",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
                "error": {
                    "type": "string",
                    "description": "Blocking error when status is blocked",
                },
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
            "required": ["status", "summary"],
        },
    }
    agent_type: str | None = None
    agent_ref: Any = None

    _COMMON_FIELDS = {"status", "summary", "unresolved", "artifacts", "error"}
    _ROLE_FIELDS = {
        "web_researcher": {"findings", "gaps"},
        "analyst": {
            "contradictions", "critical_gaps", "coverage_score",
            "next_wave_suggestions", "key_evidence_ids", "remove_evidence_ids",
        },
        "critic": {
            "verdicts", "critical_gaps", "overall_assessment",
            "remove_evidence_ids",
        },
    }
    _EXTRA_FIELD_SCHEMAS = {
        "critical_gaps": {
            "type": "array",
            "description": "Only evidence gaps that materially affect the final answer",
            "items": {"type": "string"},
        },
        "key_evidence_ids": {
            "type": "array",
            "description": "Evidence IDs selected as the compact working set",
            "items": {"type": "string"},
        },
        "remove_evidence_ids": {
            "type": "array",
            "description": "Obsolete or superseded evidence IDs to remove from the working set",
            "items": {"type": "string"},
        },
    }

    def model_post_init(self, __context: Any) -> None:
        """Expose only the handoff fields relevant to this subagent role."""
        schema = copy.deepcopy(type(self).model_fields["tool_schema"].default)
        properties = schema["parameters"]["properties"]
        properties.update(copy.deepcopy(self._EXTRA_FIELD_SCHEMAS))
        allowed = self._COMMON_FIELDS | self._ROLE_FIELDS.get(self.agent_type, set())
        schema["parameters"]["properties"] = {
            key: value for key, value in properties.items() if key in allowed
        }
        self.tool_schema = schema

    def execute(self, **kwargs) -> str | dict:
        status = kwargs.get("status")
        summary = kwargs.get("summary")
        if status not in {"completed", "partial", "blocked"}:
            return {"error": "status must be completed, partial, or blocked."}
        if not isinstance(summary, str) or not summary.strip():
            return {"error": "summary is required and must be a non-empty string."}

        legacy_assets = kwargs.get("assets") or []
        artifacts = list(kwargs.get("artifacts") or [])
        for asset in legacy_assets:
            if asset not in artifacts:
                artifacts.append(asset)
        submission = {
            "status": status,
            "summary": summary.strip(),
            "unresolved": kwargs.get("unresolved") or [],
            "artifacts": artifacts,
            "error": kwargs.get("error"),
        }
        allowed = self._ROLE_FIELDS.get(self.agent_type, set())
        for key in allowed:
            if key in kwargs:
                submission[key] = kwargs[key]
        # Keep accepting the old assets alias without advertising it to models.
        if legacy_assets:
            submission["assets"] = artifacts
        self.agent_ref._submission = submission
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
                            "description": {
                                "type": "string",
                                "description": (
                                    "Optional short DAG/GUI label. Defaults to "
                                    "params.task_description for predefined agents."
                                ),
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "IDs of tasks that must complete first",
                            },
                            "dependency_policy": {
                                "type": "string",
                                "enum": ["all_completed", "all_terminal"],
                                "description": "Whether dependencies must succeed or only reach a terminal state",
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
                        "required": ["id"],
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
            params = st.get("params") or {}
            description = st.get("description") or params.get("task_description")
            if not isinstance(description, str) or not description.strip():
                return (
                    f"Error: sub-task '{st.get('id', '<unknown>')}' requires "
                    "description or params.task_description."
                )
            description = description.strip()
            plan.add_node(DAGNode(
                id=st["id"], description=description,
                agent_hint=st.get("agent_hint", "any"),
                depends_on=st.get("depends_on", []),
                dependency_policy=st.get("dependency_policy") or (
                    "all_terminal"
                    if st.get("agent") in {"analyst", "critic"}
                    else "all_completed"
                ),
            ))
            # Stash agent/params for _run_node
            _sub_meta[st["id"]] = {
                "agent": st.get("agent"),
                "params": params,
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
            deps: dict[str, str] = {}
            for dependency_id in (node.depends_on if node else []):
                if dependency_id in agent_results:
                    deps[dependency_id] = agent_results[dependency_id]
                    continue
                dependency = plan.nodes.get(dependency_id)
                if dependency and dependency.status in {
                    DAGNodeStatus.FAILED, DAGNodeStatus.BLOCKED,
                }:
                    deps[dependency_id] = json.dumps({
                        "status": dependency.status.value,
                        "node": dependency_id,
                        "error": dependency.result or "Dependency did not complete.",
                    }, ensure_ascii=False)
            meta = _sub_meta.get(node_id, {})
            agent_type = meta.get("agent")
            params = meta.get("params") or {}
            defn = None

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
                rendered = f"{rendered}\n\nCurrent date: {date.today().isoformat()}"
                sub_model = defn.get("model")

                # Build user message with predecessor context
                user_msg = (
                    f"## Task\n{description}\n\n"
                    f"Follow the system prompt. "
                    f"Call submit_output() when you have completed the task."
                )
                if deps:
                    user_msg += "\n\n## Predecessor Results\n" + "\n".join(
                        f"  [{d}] {self._format_predecessor_context(deps[d])}" for d in deps
                    )
            else:
                # ── Legacy path: free-form description ──
                rendered = None
                user_msg = description
                if hint and hint != "any":
                    user_msg = f"Your role: {hint}\n{description}"
                if deps:
                    user_msg += "\n\nPredecessor results:\n" + "\n".join(
                        f"  [{d}] {self._format_predecessor_context(deps[d])}" for d in deps
                    )
                user_msg += (
                    "\n\nCall submit_output once when the subtask is done. Include "
                    "status, a concise summary, unresolved items, and any artifacts."
                )

            sub_agent = create_agent(
                agent_hint=hint, predecessor_results=deps,
                stop_event=agent.stop_event,
                workspace_root=workspace_root,
                model=sub_model,
                system_prompt=rendered,
                use_aux=bool(agent_type),
                tool_factory=getattr(agent, "_subagent_tool_factory", None),
            )

            # ── Inject submit_output tool (all DAG sub-tasks) ──
            submit_tool = SubmitOutputTool(agent_type=agent_type)
            submit_tool.agent_ref = sub_agent
            sub_agent.tools["submit_output"] = submit_tool
            sub_agent.llm.tools["submit_output"] = submit_tool
            if agent_type in {"analyst", "critic"}:
                from orchestrator.research_state_access import (
                    ResearchStateFileGuard,
                    ResearchStateReader,
                )

                state_reader = ResearchStateReader(
                    workspace_root=workspace_root or os.getcwd(),
                    agent_type=agent_type,
                )
                sub_agent.tools[state_reader.name] = state_reader
                if "read_file" in sub_agent.tools:
                    sub_agent.tools["read_file"] = ResearchStateFileGuard(
                        sub_agent.tools["read_file"],
                    )
            sub_agent.trace_raw_tool_results = True
            sub_agent.submission_reserve = 2
            sub_agent.wrap_up_calls = 2
            sub_agent.finalization_hint = (
                str(defn.get("finalization_hint") or "") if defn else ""
            )

            # ── Apply allowed-tools filter if subagent defines one ──
            # submit_output is injected BEFORE the filter, so it survives
            # only when explicitly listed in the agent_type's allowed-tools.
            if agent_type:
                at = defn.get("allowed_tools")
                if at is not None:
                    filtered = {}
                    for k, v in sub_agent.tools.items():
                        if (k.startswith("mcp_") and agent_type != "analyst") or k in at:
                            filtered[k] = v
                    sub_agent.tools = filtered
                    sub_agent.llm.tools = filtered

            cfg = getattr(agent, "cfg", {}) or {}
            if agent_type == "web_researcher":
                from orchestrator.research_tool_budget import (
                    ResearchToolBudget,
                    ResearchToolBudgetCounter,
                )

                research_limits = {
                    "web_search": cfg.get("research_sub_agent_max_web_search_calls", 10),
                    "web_fetch": cfg.get("research_sub_agent_max_web_fetch_calls", 15),
                }
                for tool_name, limit in research_limits.items():
                    counter = ResearchToolBudgetCounter(limit)
                    mcp_suffix = "search" if tool_name == "web_search" else "fetch"
                    equivalent_tools = [
                        name for name in sub_agent.tools
                        if name == tool_name
                        or (
                            name.startswith("mcp_")
                            and name.endswith(mcp_suffix)
                        )
                    ]
                    for equivalent_name in equivalent_tools:
                        sub_agent.tools[equivalent_name] = ResearchToolBudget(
                            sub_agent.tools[equivalent_name], limit, counter,
                        )
                sub_agent.llm.tools = sub_agent.tools
                user_msg += (
                    "\n\n## Retrieval Budget\n"
                    f"- web_search: {research_limits['web_search']} calls maximum\n"
                    f"- web_fetch: {research_limits['web_fetch']} calls maximum\n"
                    "These are hard limits. Stop expanding retrieval before they are exhausted "
                    "and reserve time to synthesize and call submit_output."
                )

            sub_agent.submission_required = "submit_output" in sub_agent.tools

            from orchestrator.subagent_trace import SubagentTraceRelay

            trace_relay = SubagentTraceRelay(agent.emit, node_id, agent_type)
            sub_agent.emit = trace_relay
            node_started = time.perf_counter()

            # Research-style predefined agents usually need more rounds.
            default_limit = cfg.get("sub_agent_max_llm_calls", 25)
            sub_agent.max_llm_calls = default_limit

            deps_list = node.depends_on if node else []
            agent.emit({"type": "dag_node_start", "data": {
                "id": node_id, "hint": hint, "description": description,
                "depends_on": deps_list,
                "agent": agent_type,
                "metrics": trace_relay.snapshot_metrics(),
                "max_llm_calls": default_limit,
                "submission_reserve": sub_agent.submission_reserve,
                "wrap_up_calls": sub_agent.wrap_up_calls,
                "started_at": time.time(),
            }})
            await sub_agent.add_user_message(user_msg)
            try:
                await sub_agent.process_with_llm()
            except Exception as exc:
                from logger import redact_sensitive
                error = redact_sensitive(exc)
                agent.emit({"type": "dag_node_complete", "data": {
                    "id": node_id,
                    "result": error[:200],
                    "status": "FAILED",
                    "stop_reason": "exception",
                    "duration_ms": round((time.perf_counter() - node_started) * 1000),
                    "metrics": trace_relay.snapshot_metrics(),
                }})
                raise RuntimeError(error) from exc

            # ── Collect results (three-tier fallback) ──
            #   1. submit_output tool → _submission
            #   2. (agent_type) fallback: _collect_agent_output + _try_parse_json
            #   3. (legacy) fallback: _collect_agent_output
            parsed: dict | None = None
            result: str | None = None
            submission = getattr(sub_agent, "_submission", None)
            interrupted = bool(getattr(sub_agent, "_interrupted", False))
            if isinstance(submission, dict):
                trace_relay.record_submission(submission)

            if submission is None:
                checkpoint = self._build_checkpoint(sub_agent, node_id)
                result = json.dumps(checkpoint, ensure_ascii=False)
            elif agent_type:
                # Structured submission (via submit_output tool)
                if isinstance(submission, dict):
                    result = json.dumps(submission, ensure_ascii=False)
                    if workspace_root:
                        self._write_research_state(
                            workspace_root, node_id, submission, agent_type=agent_type,
                        )
                else:
                    # String fallback (e.g. legacy subagent used submit_output with string)
                    result = str(submission)
                    parsed = self._try_parse_json(result) if result else None
                    if parsed and workspace_root:
                        self._write_research_state(
                            workspace_root, node_id, parsed, agent_type=agent_type,
                        )
            else:
                result = json.dumps(submission, ensure_ascii=False) if isinstance(submission, dict) else str(submission)

            if result is None:
                result = "[no output]"

            if submission is not None:
                terminal_status = "SUBMITTED"
                stop_reason = "completed"
            elif interrupted:
                terminal_status = "STOPPED"
                stop_reason = "interrupted"
            else:
                terminal_status = "CHECKPOINTED"
                stop_reason = "submission_missing"
            agent.emit({"type": "dag_node_complete", "data": {
                "id": node_id,
                "result": result[:200],
                "status": terminal_status,
                "stop_reason": stop_reason,
                "duration_ms": round((time.perf_counter() - node_started) * 1000),
                "metrics": trace_relay.snapshot_metrics(),
            }})
            if submission is None:
                raise RuntimeError(result)
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
            if meta.get("agent"):
                _node_provider[nid] = (
                    (agent.cfg.get("aux") or {}).get("provider") or None
                )

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
    def _format_predecessor_context(result: str) -> str:
        """Preserve the generic handoff envelope without large role extensions."""
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return str(result)[:4000]
        if not isinstance(parsed, dict) or "status" not in parsed:
            return str(result)[:4000]
        generic_keys = ("status", "summary", "unresolved", "artifacts", "error")
        generic = {key: parsed.get(key) for key in generic_keys if key in parsed}
        return json.dumps(generic, ensure_ascii=False)

    @staticmethod
    def _build_checkpoint(sub_agent: Any, node_id: str) -> dict[str, Any]:
        """Build a bounded, non-authoritative handoff after submission failure."""
        from logger import redact_sensitive

        recent_results: list[dict[str, str]] = []
        artifacts: list[dict[str, str]] = []
        last_agent_output = ""
        for message in getattr(sub_agent, "chat_history", [])[-20:]:
            if message.get("role") == "agent" and message.get("content"):
                last_agent_output = redact_sensitive(message.get("content"))[:2000]
            if message.get("role") != "tool":
                continue
            try:
                arguments = json.loads(message.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            path = arguments.get("file_path") or arguments.get("path")
            if path:
                artifact = {"path": redact_sensitive(path), "type": "file"}
                if artifact not in artifacts:
                    artifacts.append(artifact)
            recent_results.append({
                "tool": str(message.get("name") or ""),
                "preview": redact_sensitive(message.get("result") or "")[:500],
            })
        return {
            "status": "checkpointed",
            "node_id": node_id,
            "summary": "Subagent ended without a structured submission.",
            "unresolved": ["Structured submission was not produced."],
            "artifacts": artifacts,
            "last_agent_output": last_agent_output,
            "stop_reason": "submission_missing",
            "recent_tool_results": recent_results[-8:],
        }

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
    def _write_research_state(
        workspace_root: str,
        node_id: str,
        parsed: dict,
        agent_type: str | None = None,
    ) -> None:
        """Update the compact, mutable Deep Research working set."""
        state_path = os.path.join(workspace_root, "research_state.json")
        state: dict = {
            "evidence": {},
            "synthesis": {
                "summary": "",
                "key_evidence_ids": [],
                "contradictions": [],
                "critical_gaps": [],
                "candidate_gaps": [],
                "next_wave_suggestions": [],
            },
            "assets": [],
            "meta": {"revision": 0, "last_analyzed_revision": 0},
        }

        if os.path.isfile(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if "evidence" in existing:
                    state.update(existing)
                    state["synthesis"] = {
                        **state["synthesis"], **existing.get("synthesis", {}),
                    }
                    state["meta"] = {**state["meta"], **existing.get("meta", {})}
                else:
                    # One-time migration from the former append-only layout.
                    for index, finding in enumerate(existing.get("findings", []), 1):
                        if not isinstance(finding, dict):
                            continue
                        legacy_node = finding.get("node") or "legacy"
                        evidence_id = f"{legacy_node}:e{index:02d}"
                        state["evidence"][evidence_id] = {
                            **finding, "id": evidence_id, "revision": 0,
                        }
                    state["synthesis"].update({
                        "contradictions": existing.get("contradictions", []),
                        "candidate_gaps": existing.get("gaps", []),
                    })
                    legacy_meta = existing.get("meta", {})
                    for key in (
                        "coverage_score", "next_wave_suggestions",
                        "overall_assessment", "critical_gaps", "verdicts",
                    ):
                        if key in legacy_meta:
                            state["synthesis"][key] = legacy_meta[key]
                    state["assets"] = existing.get("assets", [])
            except (OSError, json.JSONDecodeError):
                pass

        evidence = state.setdefault("evidence", {})
        synthesis = state.setdefault("synthesis", {})
        meta = state.setdefault("meta", {})
        revision = int(meta.get("revision", 0))

        if agent_type == "web_researcher":
            revision += 1
            prefix = f"{node_id}:e"
            for evidence_id in [key for key in evidence if key.startswith(prefix)]:
                del evidence[evidence_id]
            for index, finding in enumerate(parsed.get("findings", [])[:12], 1):
                if not isinstance(finding, dict):
                    continue
                evidence_id = f"{node_id}:e{index:02d}"
                evidence[evidence_id] = {
                    **finding,
                    "id": evidence_id,
                    "node": node_id,
                    "revision": revision,
                }
            candidate_gaps = synthesis.setdefault("candidate_gaps", [])
            for gap in parsed.get("gaps", [])[:3]:
                text = gap if isinstance(gap, str) else gap.get("description", "")
                if text and text not in candidate_gaps:
                    candidate_gaps.append(text)

        elif agent_type in {"analyst", "critic"}:
            removed = False
            for evidence_id in parsed.get("remove_evidence_ids", []):
                if evidence.pop(evidence_id, None) is not None:
                    removed = True
            if removed:
                revision += 1

            synthesis["summary"] = parsed.get("summary", synthesis.get("summary", ""))
            role_fields = {
                "analyst": (
                    "contradictions", "critical_gaps", "coverage_score",
                    "next_wave_suggestions", "key_evidence_ids",
                ),
                "critic": (
                    "verdicts", "critical_gaps", "overall_assessment",
                ),
            }
            for key in role_fields[agent_type]:
                if key in parsed:
                    synthesis[key] = parsed[key]
            if agent_type == "analyst":
                synthesis["candidate_gaps"] = []
                meta["last_analyzed_revision"] = revision

        # Evidence is the canonical store. Keep synthesis as a compact index and
        # repair stale references left by removals or older state-file versions.
        synthesis["key_evidence_ids"] = [
            evidence_id
            for evidence_id in synthesis.get("key_evidence_ids", [])
            if evidence_id in evidence
        ]
        synthesis.pop("key_evidence", None)

        meta["revision"] = revision

        for artifact in parsed.get("artifacts", []):
            if isinstance(artifact, dict) and artifact not in state["assets"]:
                state["assets"].append({**artifact, "node": node_id})

        # Keep the compact downstream view first for bounded line-based reads.
        state = {
            "synthesis": synthesis,
            "evidence": evidence,
            "assets": state.get("assets", []),
            "meta": meta,
        }

        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
