"""Plan tools — track progress through decomposed sub-tasks."""

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
        for st in sub_tasks:
            plan.add_node(DAGNode(
                id=st["id"], description=st["description"],
                agent_hint=st.get("agent_hint", "any"),
                depends_on=st.get("depends_on", []),
            ))

        agent.emit({"type": "plan_start"})
        agent.emit({"type": "plan", "data": plan.format_for_prompt()})
        agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})

        # Execute DAG
        agent_results: dict[str, str] = {}

        async def _run_node(node_id: str, description: str) -> str:
            node = plan.nodes.get(node_id)
            hint = node.agent_hint if node else "any"
            deps = {
                d: agent_results[d]
                for d in (node.depends_on if node else [])
                if d in agent_results
            }
            sub_agent = create_agent(
                agent_hint=hint, predecessor_results=deps,
                stop_event=agent.stop_event,
                workspace_root=getattr(agent, "_workspace_root", None),
            )
            deps_list = node.depends_on if node else []
            agent.emit({"type": "dag_node_start", "data": {
                "id": node_id, "hint": hint, "description": description,
                "depends_on": deps_list,
            }})
            result = await run_agent_task(sub_agent, description, hint, deps)
            agent.emit({"type": "dag_node_complete", "data": {
                "id": node_id, "result": result[:200],
            }})
            agent_results[node_id] = result
            return result

        executor = DAGExecutor(
            plan, runner=None,
            interrupt_check=lambda: agent.stop_event.is_set(),
        )
        try:
            all_results = await executor.execute_all_async(_run_node)
        except Exception as exc:
            return f"Error during plan execution: {exc}"

        # Build summary
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

        agent.emit({"type": "plan_complete", "data": summary})
        return (
            f"## DAG Execution Complete\n"
            f"All sub-tasks have been executed. Here are the results:\n\n{summary}"
        )
