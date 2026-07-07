"""Generic Skill tool — routes to any skill by name, injects content as message."""

from typing import Any
from .tool import Tool


class Tool_Skill(Tool):
    name: str = "skill"
    description: str = (
        "Execute a skill within the main conversation. "
        "When a skill matches the user's request, invoke this tool BEFORE "
        "generating any other response."
    )
    tool_schema: dict = {
        "name": "skill",
        "description": "Execute a skill by name. The skill's instructions will be injected as a message for you to follow.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name from the available skills list (e.g. 'deep-research', 'code-doc')",
                },
                "args": {
                    "type": "string",
                    "description": "Optional arguments for the skill",
                    "default": "",
                },
            },
            "required": ["skill"],
        },
    }

    agent_ref: Any = None

    def execute(self, skill: str = "", args: str = "") -> str:
        agent = self.agent_ref
        if agent is None:
            return "Error: no agent reference."

        name = skill.lstrip("/")
        from skill import get_skill, activate_skill_for_agent
        skill_obj = get_skill(name)
        if skill_obj is None:
            return f"Skill '{skill}' not found. Use the `skill` tool with a name from the available skills list."
        return activate_skill_for_agent(agent, skill_obj, args=args)
