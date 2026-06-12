"""Tool that lets the LLM ask the user a question interactively.

The LLM calls this tool when it needs information only the user can provide,
such as passwords, file paths, or confirmation before proceeding.
"""
import asyncio
from .tool import Tool


class Tool_AskUser(Tool):
    name: str = "ask_user"
    description: str = (
        "Ask the user a question when you need clarification, input, or a decision.\n\n"
        "Use when:\n"
        "- The task is ambiguous and you need the user to choose a direction\n"
        "- You need information only the user can provide (passwords, paths, preferences)\n"
        "- A decision has meaningful trade-offs the user should weigh in on\n"
        "- You want post-task feedback\n\n"
        "Do NOT use for:\n"
        "- Things you can already determine from available tool results\n"
        "- Hypothetical or casual questions unrelated to the current task\n\n"
        "DO use when:\n"
        "- A tool keeps failing and you've tried 2+ approaches — ask for guidance\n"
        "- The path or approach is unclear and the user has preferences"
    )
    tool_schema: dict = {
        "name": "ask_user",
        "description": (
            "Ask the user a question when you need clarification, input, or a decision.\n\n"
            "Use when:\n"
            "- The task is ambiguous and you need the user to choose a direction\n"
            "- You need information only the user can provide (passwords, paths, preferences)\n"
            "- A decision has meaningful trade-offs the user should weigh in on\n"
            "- You want post-task feedback\n\n"
            "Do NOT use for:\n"
            "- Things you can already determine from available tool results\n"
            "- Hypothetical or casual questions unrelated to the current task\n\n"
            "DO use when:\n"
            "- A tool keeps failing and you've tried 2+ approaches — ask for guidance\n"
            "- The path or approach is unclear and the user has preferences"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question to show the user",
                },
                "password": {
                    "type": "boolean",
                    "description": "Mask input (e.g. for passwords)",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                    "description": "Optional multiple-choice options (up to 4). User picks one or types a custom answer.",
                },
            }
        },
        "required": ["prompt"],
    }

    async def execute(self, prompt: str, password: bool = False, choices: list | None = None) -> str:
        if self.interactive_input:
            if asyncio.iscoroutinefunction(self.interactive_input):
                return await self.interactive_input(prompt, password=password, choices=choices)
            return self.interactive_input(prompt, password=password, choices=choices)
        return ""
