from .tool import Tool

class Tool_Remember(Tool):
    name: str = "remember"
    description: str = "Store a piece of information in memory for later retrieval."
    tool_schema: dict = {
        "name": "remember",
        "description": "Stores a piece of information in memory in further conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "description": "The type of memory to store: normal:Not archived memories; archived:Memories that are too long and cannot be further compressed; event:Some important conversation turns."
                },
                "value": {
                    "type": "string",
                    "description": "The memory to store."
                }
            },
            "required": ["memory_type", "value"]
        }
    }

    def execute(self, memory_type: str, value: str):
        # Here you would implement the logic to store the key-value pair in memory.
        # For demonstration purposes, we'll just return a success message.
        return f"Information stored under memory type '{memory_type}': {value}"