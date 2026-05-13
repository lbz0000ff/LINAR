# Base class for tools, gets the toolset and search tools from the toolset
from pydantic import BaseModel
from typing import Optional, Callable

class Tool(BaseModel):
    name: str = "base_tool"
    description: str = "A base tool for implementing specific functionality."
    tool_schema: dict = {
        "name": "base_tool",
        "description": "A base tool for implementing specific functionality.",
        "parameters": [
          {
            "name": "",
            "type": "",
            "description": ""
          }
        ],
        "required": []
    }

    # Optional callback for interactive input (e.g., sudo password).
    # Signature: (prompt: str, password: bool = False, choices: list | None = None) -> str
    interactive_input: Optional[Callable] = None

    def execute(self, *args, **kwargs):
        raise NotImplementedError("Tool must implement the execute method.")
      
