"""MCPTool — wraps a remote MCP tool as a Lily Tool."""
from .tool import Tool


class MCPTool(Tool):
    """Delegates execute() to an MCPServer instance."""

    def __init__(self, server, name: str, original_name: str, description: str, input_schema: dict):
        # Convert the JSON Schema into Lily's OpenAI-compatible schema
        schema = {
            "name": name,
            "description": description,
            "parameters": input_schema or {"type": "object", "properties": {}},
        }
        super().__init__(name=name, description=description, tool_schema=schema)
        self._server = server
        self._original_name = original_name

    def execute(self, **kwargs):
        return self._server.call_tool(self._original_name, kwargs)
