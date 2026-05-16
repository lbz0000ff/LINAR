import sys
import io
import json
from llm import LLM
from config import load_config
from logger import get_logger
from permissions import PermissionManager
import database as db

log = get_logger(__name__)


class Agent:
    def __init__(self, tools: dict = None):
        cfg = load_config()

        # ── read config ──
        self.cfg = cfg
        api_key = cfg["llm"]["api_key"]
        base_url = cfg["llm"].get("base_url", "https://api.deepseek.com/v1")
        model = cfg["llm"].get("model", "deepseek-v4-flash")
        system_prompt = self._build_prompt(cfg)

        self.llm = LLM(api_key, system_prompt, tools, base_url=base_url, model=model)
        self.tools = tools
        self._skill_active = False  # set by Skill.on_load()
        self.permissions = PermissionManager(cfg.get("permissions", {}))
        self._confirm_callback = None  # set by terminal to prompt user
        self.chat_history: list[dict] = []

        # ── database (archive chat history) ──
        db.init_db()
        self.session_id = None

        # ── conversation turn counter ──
        self._turn_counter = 0

        # ── consecutive tool failure tracker ──
        self._tool_failures: dict[str, int] = {}

        # ── active task plan (set by orchestrator) ──
        self.current_plan = None

        # ── config values ──
        self.max_turns = cfg.get("max_turns", 5)
        self.chat_cfg = cfg.get("chat_history", {})

        log.info("Agent initialized (model=%s, max_turns=%s)", self.llm.model, self.max_turns)
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

        # ── runtime context ──
        import os, platform, sys as _sys
        _cwd = os.getcwd()
        _platform = platform.system()
        # project root is fixed: parent of agent/
        _agent_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_agent_dir)
        parts.append(
            f"\n## Runtime context\n"
            f"Platform: {_platform}\n"
            f"Working directory: {_cwd}\n"
            f"Project root: {_project_root}\n"
            f"Shell: cmd /c (each command runs in a fresh shell, cd does NOT persist)\n"
            f"Use absolute paths or chain commands with && to keep the same session."
        )

        # dynamically append registered skills so the LLM knows about them
        try:
            from skill import all_skills
            skills = all_skills()
            if skills:
                lines = ["\n## Available skills\n"]
                for s in skills:
                    lines.append(f"- /{s.name} — {s.description}")
                lines.append(
                    "\n**Rule: if the user's request matches a skill description, "
                    "call `skill_view` to load its instructions and follow them.**"
                )
                parts.append("\n".join(lines))
        except ImportError:
            pass

        return "\n\n".join(parts) if parts else "You are a helpful assistant."

    def _format_chat_history(self) -> str:
        """Serialize internal JSON history to text for the LLM prompt."""
        parts = ["Chat history:"]
        for msg in self.chat_history:
            role = msg["role"]
            turn = msg.get("turn")
            if role == "user":
                parts.append(f"[turn {turn}]\nUser: {msg['content']}")
            elif role == "agent":
                parts.append(f"Agent: {msg['content']}")
            elif role == "tool":
                parts.append(f"Tool call: {msg['name']} with parameters {msg['arguments']}")
                if msg.get("result"):
                    parts.append(f"Tool result: {msg['result']}")
            elif role == "meta":
                parts.append(msg["content"])
        return "\n".join(parts)

    @staticmethod
    def _truncate_tool_result(text: str, max_len: int = 500, preview_len: int = 200) -> str:
        """Truncate large tool results to a preview + size note.

        Keeps the semantic signal (first *preview_len* chars) while discarding
        bulk output that would bloat the context window.
        """
        if len(text) <= max_len:
            return text
        lines = text.count("\n")
        return f"{text[:preview_len]}\n... (truncated, {len(text)} chars, {lines} lines)"

    def _check_permission(self, tool_name: str, arguments: str) -> str | None:
        """Check permission for a tool call.

        Returns ``None`` if allowed, or an error ``str`` if denied / rejected.
        """
        level = self.permissions.check(tool_name)

        if level == "deny":
            return (
                f"[PERMISSION_DENIED] Tool '{tool_name}' is restricted by "
                f"permission settings. Do NOT retry — it will fail again."
            )

        if level == "ask" and self._confirm_callback:
            result = self._confirm_callback(tool_name, arguments)
            if result is True:
                return None
            if result == "always":
                self.permissions.set_override(tool_name, "allow")
                return None
            if result == "never":
                self.permissions.set_override(tool_name, "deny")
                return (
                    f"[REJECTED_BY_USER] Tool '{tool_name}' was blocked — "
                    f"the user chose to never allow it. Do NOT retry."
                )
            # False / None / anything else → rejected
            return (
                f"[REJECTED_BY_USER] Tool '{tool_name}' was not approved by the "
                f"user. Try a different approach or ask the user."
            )

        # allow, or ask without a callback → just execute
        return None

    def _compact_history(self):
        """Compact chat history: remove tool noise from the middle region.

        Keeps intact:
        - Head: first 3 entries (first user turn usually establishes context)
        - Tail: last ``protect_last_turns`` user turns, plus any associated
          tool entries so that tool_call / tool_result pairs are never split.

        Only non-user, non-agent tool entries in the unprotected middle are
        removed.  Compared to the old approach, this is more conservative:
        it removes *less* data, but what it removes is purely bulk output
        that the LLM doesn't need to re-read.
        """
        total = len(self._format_chat_history())
        if total <= self.max_history_chars:
            return

        user_indices = [i for i, m in enumerate(self.chat_history) if m["role"] == "user"]
        protect_count = min(self.protect_last_turns, len(user_indices))

        # ── Head protection: keep first 3 entries ──
        head_end = min(3, len(self.chat_history))

        # ── Tail protection: start of the last N user turns ──
        tail_start = user_indices[-protect_count] if protect_count > 0 else len(self.chat_history)

        # ── Smart boundary: if the protected user turn follows tool
        #     entries (which belong to the previous turn), don't pull
        #     those tool entries into the middle — they're part of the
        #     previous turn's pair and belong in the tail if anything.
        #     We handle this by keeping the boundary at the user index
        #     which naturally separates turns. ──

        if head_end >= tail_start:
            return  # no compressible region

        head = self.chat_history[:head_end]
        tail = self.chat_history[tail_start:]
        middle = self.chat_history[head_end:tail_start]

        # Only remove tool entries from the middle
        compacted = [m for m in middle if m["role"] != "tool"]

        if len(compacted) == len(middle):
            return  # nothing to remove

        self.chat_history = head + compacted + tail

        log.debug(
            "Compact: %d → %d chars (saved %d, removed %d tool entries)",
            total, len(self._format_chat_history()),
            total - len(self._format_chat_history()),
            len(middle) - len(compacted),
        )

    def add_user_message(self, text: str):
        """Append a user message with a [turn N] marker and archive it."""
        if self.session_id is None:
            self.session_id = db.create_session()
            log.info("Created session #%s", self.session_id)
        log.info("[session=%s turn=%s] User: %.120s", self.session_id, self._turn_counter + 1, text)
        self._turn_counter += 1
        self.chat_history.append({
            "role": "user", "content": text, "turn": self._turn_counter,
        })
        db.save_message(self.session_id, "user", text, turn=self._turn_counter)
        if self._turn_counter == 1:
            db.update_session_title(self.session_id, text[:80])

    def switch_session(self, session_id: int) -> bool:
        """Switch to an existing session. Returns False if not found."""
        sess = db.get_session_by_id(session_id)
        if not sess:
            log.warning("Session #%s not found for switch", session_id)
            return False
        log.info("Switched to session #%s", session_id)

        messages = db.get_session_messages(session_id)
        self.chat_history = []
        max_turn = 0
        for msg in messages:
            turn = msg.get("turn", 0) or 0
            if turn > max_turn:
                max_turn = turn
            role = msg["role"]
            if role == "tool":
                # content stores JSON: {"args": ..., "result": ...}
                try:
                    payload = json.loads(msg["content"])
                    entry = {
                        "role": "tool",
                        "name": msg.get("tool_name", ""),
                        "arguments": payload.get("args", ""),
                        "result": payload.get("result", ""),
                        "turn": turn,
                    }
                except (json.JSONDecodeError, TypeError, KeyError):
                    entry = {
                        "role": "tool",
                        "name": msg.get("tool_name", ""),
                        "arguments": "",
                        "result": msg.get("content", ""),
                        "turn": turn,
                    }
            else:
                entry = {
                    "role": role,
                    "content": msg.get("content", ""),
                    "turn": turn,
                }
            self.chat_history.append(entry)

        self._turn_counter = max_turn
        self.session_id = session_id
        return True

    def get_current_session_info(self) -> dict:
        """Return info about the current session."""
        sess = db.get_session_by_id(self.session_id)
        if not sess:
            return {"session_id": self.session_id, "turn": self._turn_counter}
        return {
            "session_id": sess["id"],
            "title": sess.get("title", ""),
            "marker": sess.get("marker"),
            "created_at": sess.get("created_at", ""),
            "turn": self._turn_counter,
        }

    def reset_session(self):
        """Start a fresh conversation session"""
        self.chat_history = []
        self._turn_counter = 0
        self.session_id = None
        log.info("Session reset")

    def emit(self, event: dict):
        """Write a JSON event to stdout."""
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def process_with_llm(self):
        """Run the LLM (streaming), handle tool calls, emit events.

        Loops until the agent produces a final answer (no tool calls).
        max_turns=0 means unlimited; otherwise caps the number of LLM rounds.
        """
        # ── re-read prompt files so memory writes take effect immediately ──
        if not self._skill_active:
            self.llm.system_prompt = self._build_prompt(self.cfg)

        turn = 0
        while True:
            turn += 1
            if self.max_turns > 0 and turn > self.max_turns:
                break
            prompt = self._format_chat_history() + "\nAgent:"

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
                self.chat_history.append({
                    "role": "agent", "content": text, "turn": self._turn_counter,
                })
                db.save_message(self.session_id, "agent", text, turn=self._turn_counter)

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
                log.info(
                    "[session=%s turn=%s] Tool call: %s",
                    self.session_id, self._turn_counter, tc["name"],
                )

                # ── permission check ──
                result_str = self._check_permission(tc["name"], tc["arguments"])
                _tool_failed = False
                if result_str is None:
                    # permitted — execute normally
                    try:
                        raw_args = tc["arguments"]
                        args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        result = self.tools[tc["name"]].execute(**args_dict)
                        # detect failures in structured tool results
                        if isinstance(result, dict):
                            if result.get("error"):
                                _tool_failed = True
                            elif result.get("exit_code", 0) != 0:
                                _tool_failed = True
                        result_str = self._truncate_tool_result(str(result))
                    except json.JSONDecodeError as e:
                        result_str = f"Error: Failed to parse tool arguments: {e}"
                        _tool_failed = True
                    except Exception as e:
                        result_str = f"Error: {e}"
                        _tool_failed = True

                # ── track consecutive failures per tool ──
                is_failure = _tool_failed or (
                    result_str and (
                        result_str.startswith("Error") or result_str.startswith("[")
                    )
                )
                if is_failure:
                    self._tool_failures[tc["name"]] = self._tool_failures.get(tc["name"], 0) + 1
                    if self._tool_failures[tc["name"]] >= 3:
                        self.chat_history.append({
                            "role": "meta",
                            "content": (
                                f"[SYSTEM] Tool '{tc['name']}' has failed "
                                f"{self._tool_failures[tc['name']]} times in a row. "
                                f"Do NOT retry the same approach. Switch strategy "
                                f"or use ask_user to get guidance."
                            ),
                            "turn": self._turn_counter,
                        })
                        self._tool_failures[tc["name"]] = 0
                else:
                    self._tool_failures[tc["name"]] = 0

                self.chat_history.append({
                    "role": "tool",
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "result": result_str,
                    "turn": self._turn_counter,
                })
                self.emit({
                    "type": "tool_result",
                    "name": tc["name"],
                    "result": result_str,
                })

                db.save_message(
                    self.session_id, "tool",
                    json.dumps({"args": tc["arguments"], "result": result_str}, ensure_ascii=False),
                    tool_name=tc["name"], turn=self._turn_counter,
                )

            # ── compact history if needed ──
            self._compact_history()

        log.info(
            "[session=%s turn=%s] LLM done (tool_calls=%d)",
            self.session_id, self._turn_counter, len(tool_calls),
        )
        self.emit({"type": "complete"})
        self.emit({"type": "ready"})

    def run(self):
        log.info("Agent run loop started (stdin mode)")
        # Force UTF-8 on stdin (Windows pipes often use the wrong code page)
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")

        self.emit({"type": "ready"})
        first_message = True
        for line in sys.stdin:
            user_input = line.strip()
            if not user_input:
                continue

            self.add_user_message(user_input)
            self.emit({"type": "user_echo", "data": user_input})
            self.process_with_llm()


if __name__ == "__main__":

    from tool_registry import get_tools

    # Load config and filter tools by enabled_sets
    from config import load_config
    _cfg = load_config()
    _enabled = _cfg.get("tools", {}).get("enabled_sets", None)
    tools = get_tools(_enabled)

    # Inject interactive input callback (stdin-based, for headless mode)
    def _stdin_input(prompt: str, password: bool = False, choices: list | None = None) -> str:
        sys.stderr.write(prompt)
        if choices:
            sys.stderr.write("\n")
            for i, c in enumerate(choices, 1):
                sys.stderr.write(f"  [{i}] {c}\n")
            sys.stderr.write("Enter number or custom answer: ")
        sys.stderr.flush()
        try:
            line = sys.stdin.readline().rstrip("\n")
            if choices and line.isdigit():
                idx = int(line) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            return line
        except (EOFError, KeyboardInterrupt):
            return ""

    for t in tools.values():
        t.interactive_input = _stdin_input

    agent = Agent(tools=tools)
    agent.run()
