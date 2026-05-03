import sys
import json
from deepseek_llm import LLM


class Agent:
    def __init__(self, tools: dict = None):
        with open("api_key.txt", "r") as f:
            api_key = f.read().strip()
        with open("system_prompt.txt", "r") as f:
            system_prompt = f.read().strip()
        self.llm = LLM(api_key, system_prompt, tools)
        self.tools = tools
        self.chat_history = "Chat history:"

    def emit(self, event: dict):
        """Write a JSON event to stdout."""
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def process_with_llm(self):
        """Run the LLM (streaming), handle tool calls, emit events."""
        max_turns = 5

        for _ in range(max_turns):
            prompt = self.chat_history + "Agent:"

            self.emit({"type": "start"})

            stream = self.llm.stream_response(prompt)

            text_parts = []
            tool_call_deltas = {}

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    text_parts.append(delta.content)
                    self.emit({"type": "token", "data": delta.content})

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_deltas:
                            tool_call_deltas[idx] = {
                                "id": "", "name": "", "arguments": ""
                            }
                        if tc.id:
                            tool_call_deltas[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_call_deltas[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_call_deltas[idx]["arguments"] += tc.function.arguments

            self.emit({"type": "done"})

            text = "".join(text_parts)
            if text:
                self.chat_history += f"Agent: {text}\n"

            # Collect complete tool calls from deltas
            tool_calls = []
            for idx in sorted(tool_call_deltas.keys()):
                tc = tool_call_deltas[idx]
                if tc["name"]:
                    tool_calls.append(tc)
                    self.emit({
                        "type": "tool_call",
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    })

            # No tool calls → this turn is the final answer
            if not tool_calls:
                break

            # Execute each tool and add results to history
            for tc in tool_calls:
                try:
                    result = self.tools[tc["name"]].execute(tc["arguments"])
                    result_str = str(result)
                except Exception as e:
                    result_str = f"Error: {e}"

                self.chat_history += (
                    f"Tool call: {tc['name']} with parameters {tc['arguments']}\n"
                )
                self.chat_history += f"Tool result: {result_str}\n"
                self.emit({
                    "type": "tool_result",
                    "name": tc["name"],
                    "result": result_str,
                })

        self.emit({"type": "ready"})

    def run(self):
        self.emit({"type": "ready"})
        for line in sys.stdin:
            user_input = line.strip()
            if not user_input:
                continue
            self.chat_history += f"User: {user_input}\n"
            self.emit({"type": "user_echo", "data": user_input})
            self.process_with_llm()


if __name__ == "__main__":

    from tool_registry import tools

    agent = Agent(tools=tools)
    agent.run()
