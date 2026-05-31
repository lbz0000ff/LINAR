from .tool import Tool
from datetime import datetime

class Tool_GetDate(Tool):
    name: str = "get_date"
    description: str = "Get the current date."
    tool_schema: dict = {
        "name": "get_date",
        "description": "Returns the current date in YYYY-MM-DD format.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }

    def execute(self, *args, **kwargs):
        return datetime.now().strftime("%Y-%m-%d")

class Tool_GetTime(Tool):
    name: str = "get_time"
    description: str = "Get the current time."
    tool_schema: dict = {
        "name": "get_time",
        "description": "Returns the current time in HH:MM:SS format.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }

    def execute(self, *args, **kwargs):
        return datetime.now().strftime("%H:%M:%S")