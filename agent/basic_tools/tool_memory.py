from .tool import Tool

class Tool_Remember(Tool):
    name: str = "remember"
    description: str = "Store a piece of information in memory for later retrieval."
    tool_schema: dict = {
        "name": "remember",
        "description": "Stores a piece of information in memory for later retrieval.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "The memory to store."
                }
            },
            "required": ["key", "value"]
        }
    }

    def execute(self, key: str, value: str):
        # Here you would implement the logic to store the key-value pair in memory.
        # For demonstration purposes, we'll just return a success message.
        return f"Information stored under key '{key}'."