"""Tool for LLM to inspect available skills."""

from .tool import Tool


class Tool_SkillView(Tool):
    name: str = "skill_view"
    description: str = (
        "Show the full content of an available skill so you can follow its "
        "instructions. Call this when the user's request matches a skill's "
        "description in the Available skills list."
    )
    tool_schema: dict = {
        "name": "skill_view",
        "description": (
            "View an available skill's system prompt and tool list. "
            "Use this when the user's question or task matches a skill's "
            "description — load the skill content and follow its instructions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name from the Available skills list (e.g. 'code-doc', 'review-code')",
                }
            },
            "required": ["name"],
        },
    }

    def execute(self, name: str) -> str:
        from skill import get_skill

        skill = get_skill(name)
        if skill is None:
            available = ", ".join(
                f"/{s.name}" for s in _all_skills()
            )
            return f"Skill '{name}' not found. Available skills: {available}"

        parts = [f"## Skill: /{skill.name}"]
        if skill.description:
            parts.append(f"Description: {skill.description}")
        if skill.allowed_tools is not None:
            parts.append(f"Allowed tools: {', '.join(skill.allowed_tools)}")
        else:
            parts.append("Allowed tools: (all)")
        if skill.system_prompt:
            parts.append(f"\nInstructions:\n{skill.system_prompt}")

        return "\n\n".join(parts)


# avoid circular import
def _all_skills():
    from skill import all_skills
    return all_skills()
