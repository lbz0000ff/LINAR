import sys
import io
import json
from deepseek_llm import LLM
from config import load_config
import database as db


class Agent:
    def __init__(self, tools: dict = None):
        cfg = load_config()

        # ── read config ──
        api_key = cfg["llm"]["api_key"]
        system_prompt = self._build_prompt(cfg)

        self.llm = LLM(api_key, system_prompt, tools)
        self.tools = tools
        self.chat_history = "Chat history:"

        # ── database (archive chat history) ──
        db.init_db()
        self.session_id = db.create_session()

        # ── config values ──
        self.max_turns = cfg.get("max_turns", 5)
        self.chat_cfg = cfg.get("chat_history", {})
        self.max_history_chars = self.chat_cfg.get("max_chars", 10000)
        self.trim_to_chars = self.chat_cfg.get("trim_to", 5000)
        self.protect_last_turns = self.chat_cfg.get("protect_last_turns", 3)
        self.strategy = self.chat_cfg.get("strategy", "compact")

    def _build_prompt(self, cfg):
        """Load and join prompt files listed in config."""
        prompt_dir = "prompt"
        parts = []
        for filename in cfg.get("prompt", {}).get("files", []):
            filepath = f"{prompt_dir}/{filename}"
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    parts.append(content)
            except FileNotFoundError:
                continue
        return "\n\n".join(parts) if parts else "You are a helpful assistant."

    def _compact_history(self):
        """Compact chat history: delete middle tool-call details,
        preserving user requests and recent turns."""
        if len(self.chat_history) <= self.max_history_chars:
            return

        lines = self.chat_history.split("\n")

        # Find user message indices
        user_indices = [i for i, l in enumerate(lines) if l.startswith("User: ")]
        # Find the last N user turns to protect
        protect_count = min(self.protect_last_turns, len(user_indices))
        protected_start = user_indices[-protect_count] if protect_count > 0 else 0

        # Preserve head (first user request + response) + tail (recent turns)
        head = lines[:protected_start]
        tail = lines[protected_start:]

        # Mark tool calls and results for removal in the head section
        compacted = []
        for line in head:
            is_tool_line = (
                line.startswith("Tool call: ") or line.startswith("Tool result: ")
            )
            if is_tool_line:
                continue
            compacted.append(line)

        # Rebuild
        compacted_text = "\n".join(compacted).strip()
        tail_text = "\n".join(tail).strip()
        self.chat_history = compacted_text + "\n\n...(history compacted)...\n\n" + tail_text

    def emit(self, event: dict):
        """Write a JSON event to stdout."""
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def process_with_llm(self):
        """Run the LLM (streaming), handle tool calls, emit events.

        Loops until the agent produces a final answer (no tool calls).
        max_turns=0 means unlimited; otherwise caps the number of LLM rounds.
        """
        turn = 0
        while True:
            turn += 1
            if self.max_turns > 0 and turn > self.max_turns:
                break
            prompt = self.chat_history + "Agent:"

            self.emit({"type": "start"})

            stream = self.llm.stream_response(prompt)

            text_parts = []
            tool_call_deltas = {}

            for chunk in stream:
                # ── usage info ──
                if hasattr(chunk, "usage") and chunk.usage:
                    self.emit({
                        "type": "usage",
                        "data": {
                            "prompt_tokens": chunk.usage.prompt_tokens or 0,
                            "completion_tokens": chunk.usage.completion_tokens or 0,
                            "total_tokens": chunk.usage.total_tokens or 0,
                        },
                    })

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    text_parts.append(delta.content)
                    self.emit({"type": "token", "data": delta.content})

                # ── reasoning / thinking content ──
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    self.emit({
                        "type": "reasoning_token",
                        "data": delta.reasoning_content,
                    })

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
                db.save_message(self.session_id, "agent", text)

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
                    raw_args = tc["arguments"]
                    args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    result = self.tools[tc["name"]].execute(**args_dict)
                    result_str = str(result)
                except json.JSONDecodeError as e:
                    result_str = f"Error: Failed to parse tool arguments: {e}"
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

            # ── compact history if needed ──
            self._compact_history()

        self.emit({"type": "complete"})
        self.emit({"type": "ready"})

    def run(self):
        # Force UTF-8 on stdin (Windows pipes often use the wrong code page)
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")

        self.emit({"type": "ready"})
        first_message = True
        for line in sys.stdin:
            user_input = line.strip()
            if not user_input:
                continue

            self.chat_history += f"User: {user_input}\n"
            self.emit({"type": "user_echo", "data": user_input})

            # ── archive ──
            db.save_message(self.session_id, "user", user_input)
            if first_message:
                db.update_session_title(self.session_id, user_input[:80])
                first_message = False

            self.process_with_llm()


if __name__ == "__main__":

    from tool_registry import get_tools

    # Load config and filter tools by enabled_sets
    from config import load_config
    _cfg = load_config()
    _enabled = _cfg.get("tools", {}).get("enabled_sets", None)
    tools = get_tools(_enabled)

    # Inject interactive input callback (stdin-based, for headless mode)
    def _stdin_input(prompt: str, password: bool = False) -> str:
        sys.stderr.write(prompt)
        sys.stderr.flush()
        try:
            return sys.stdin.readline().rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            return ""

    for t in tools.values():
        t.interactive_input = _stdin_input

    agent = Agent(tools=tools)
    agent.run()
