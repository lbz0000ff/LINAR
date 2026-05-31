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
