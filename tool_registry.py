from basic_tools.tool_time import Tool_GetTime, Tool_GetDate

tools = {
          "get_date": Tool_GetDate(),
          "get_time": Tool_GetTime()
        }

toolsets = {
          "time": [
            "get_date",
            "get_time"
          ]
        }

if __name__ == "__main__":
  # print(tools)
  print(tools["get_date"].tool_schema)
  print((tools[tool_name]) for tool_name in tools)