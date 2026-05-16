"""Plan tools — track progress through decomposed sub-tasks."""

from typing import Any

from .tool import Tool


class Tool_PlanAdvance(Tool):
    """Mark the current sub-task as complete and advance to the next."""

    name: str = "plan_advance"
    description: str = (
        "Mark the current sub-task as completed and advance to the next one. "
        "Call this after finishing each sub-task described in the Current Task Plan. "
        "Provide a brief summary of what was accomplished."
    )
    tool_schema: dict = {
        "name": "plan_advance",
        "description": (
            "Advance the task plan to the next sub-task. Call this when you finish "
            "the current step. Provide a short summary of what you accomplished."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "result_summary": {
                    "type": "string",
                    "description": "Brief summary of what was accomplished in the current sub-task",
                }
            },
            "required": ["result_summary"],
        },
    }

    # Set by orchestrator when a plan is active
    agent_ref: Any = None

    def execute(self, result_summary: str = "") -> str:
        agent = self.agent_ref
        if agent is None or agent.current_plan is None:
            return "No active plan."

        plan = agent.current_plan
        current = plan.current_subtask
        if current is None:
            return "All sub-tasks already completed."

        # Record result and advance
        current.result = result_summary
        next_st = plan.advance()

        # Inject updated plan into chat_history for next LLM turn
        if plan.is_complete:
            plan_block = (
                f"\n[PLAN UPDATE]\n"
                f"Completed: {current.id} — {result_summary}\n"
                f"\nAll sub-tasks complete!"
            )
        else:
            plan_block = (
                f"\n[PLAN UPDATE]\n"
                f"Completed: {current.id} — {result_summary}\n"
                f"Now working on: {next_st.description if next_st else '(done)'}\n"
                f"{plan.format_for_prompt()}"
            )

        agent.chat_history.append({
            "role": "meta",
            "content": plan_block,
        })

        if plan.is_complete:
            return (
                f"Completed: {current.description}\n"
                f"Result: {result_summary}\n"
                f"All sub-tasks complete! The plan is finished."
            )
        else:
            # Update the next sub-task description from next_st
            next_desc = next_st.description if next_st else "(no more sub-tasks)"
            return (
                f"Completed: {current.description}\n"
                f"Result: {result_summary}\n"
                f"Now working on: {next_desc}"
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
