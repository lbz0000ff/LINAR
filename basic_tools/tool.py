# Base class for tools, gets the toolset and search tools from the toolset
from pydantic import BaseModel

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

    def execute(self, *args, **kwargs):
        raise NotImplementedError("Tool must implement the execute method.")
      
