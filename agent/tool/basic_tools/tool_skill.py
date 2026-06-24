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
        from skill import get_skill
        skill_obj = get_skill(name)
        if skill_obj is None:
            return f"Skill '{skill}' not found. Use `skill_view` (if available) to see the list."
        # Inject skill content as a user message so the LLM sees it next turn
        content = skill_obj.system_prompt
        if not content:
            return f"Skill '{skill}' loaded but has no instructions."
        header = f"[SYSTEM] Skill /{skill_obj.name} is now active."
        if args:
            header += f" Args: {args}"
        agent.chat_history.append({"role": "meta", "content": header})
        agent.chat_history.append({"role": "user", "content": content})
        # Persist to DB so injected messages survive restart/session switch
        try:
            import database as db
            db.save_message(
                session_id=agent.session_id,
                role="meta",
                content=header,
                conversation_round=agent._conversation_round,
            )
            db.save_message(
                session_id=agent.session_id,
                role="user",
                content=content,
                conversation_round=agent._conversation_round,
            )
        except Exception:
            pass
        return (f"Skill '/{skill_obj.name}' loaded. "
                f"Its instructions have been injected above. "
                f"Follow them to complete the task.")
