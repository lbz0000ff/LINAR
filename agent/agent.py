import sys
import json
import os
import time
import re
import subprocess
import threading
from llm import LLM
from config import load_config
from logger import get_logger
from permissions import PermissionManager
import database as db
from skill import get_skill

log = get_logger(__name__)

def _detect_shell() -> str:
    """Detect the effective shell used for cmd_execute on this platform."""
    import os, platform, shutil
    if platform.system() != "Windows":
        return "sh -c"
    # 1) Git Bash — best Unix compatibility
    git_path = shutil.which("git")
    if git_path:
        git_dir = os.path.dirname(os.path.dirname(git_path))
        bash = os.path.join(git_dir, "bin", "bash.exe")
        if os.path.isfile(bash):
            return f"Git Bash ({bash} -c)"
    # 2) PowerShell
    for exe in ("pwsh.exe", "powershell.exe"):
        if shutil.which(exe):
            return f"{exe} -Command"
    # 3) cmd fallback
    return "cmd /c"
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
        self._active_skill = None    # Skill instance reference, for hook lookup
        self.permissions = PermissionManager(cfg.get("permissions", {}))
        self.permissions.load_modes(cfg.get("permission_modes", {}))
        self._confirm_callback = None  # set by terminal to prompt user
        self.chat_history: list[dict] = []
        # ── database (archive chat history) ──
        db.init_db()
        self.session_id = None
        # ── conversation turn counter ──
        self._conversation_round = 0
        # ── consecutive tool failure tracker ──
        self._tool_failures: dict[str, int] = {}
        # ── reasoning-only turn retry guard ──
        self._reasoning_only_retries = 0
        # ── repeated command tracker ──
        self._cmd_history: list[str] = []
        # ── interrupt / btw ──
        self._interrupt_requested = False
        self.stop_event = threading.Event()
        self._btw_queue: list[str] = []
        # Propagate stop_event to tools that support it (e.g. web_search)
        if self.tools:
            for t in self.tools.values():
                if hasattr(t, 'stop_event'):
                    t.stop_event = self.stop_event
        # ── active task plan (set by orchestrator) ──
        self.current_plan = None
        # ── promise mechanism (async result delivery) ──
        self._promises: dict[str, dict] = {}       # promise_id → {status, result, ...}
        self._promise_callbacks: dict[str, callable] = {}  # promise_id → resolve callback
        self._resolved_since_last_build: set[str] = set()  # injected into _build_llm_messages
        # ── wire up agent_ref on tools that need it ──
        if self.tools:
            for t in self.tools.values():
                if hasattr(t, 'agent_ref'):
                    t.agent_ref = self
        # ── config values ──
        self.max_llm_calls = cfg.get("max_llm_calls", 5)
        self.chat_cfg = cfg.get("chat_history", {})
        log.info("Agent initialized (model=%s, max_llm_calls=%s)", self.llm.model, self.max_llm_calls)
        self.max_history_chars = self.chat_cfg.get("max_chars", 10000)
        self.trim_to_chars = self.chat_cfg.get("trim_to", 5000)
        self.protect_last_rounds = self.chat_cfg.get("protect_last_rounds", 3)
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
        import os, platform, sys as _sys, shutil
        _cwd = os.getcwd()
        _platform = platform.system()
        # project root is fixed: parent of agent/
        _agent_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_agent_dir)
        _shell = _detect_shell()
        parts.append(
            f"\n## Runtime context\n"
            f"Platform: {_platform}\n"
            f"Working directory: {_cwd}\n"
            f"Project root: {_project_root}\n"
            f"Shell: {_shell} (each command runs in a fresh shell, cd does NOT persist)\n"
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
        # dynamically append MCP tools so the LLM knows about them
        try:
            from tool_registry import _init_mcp_servers
            mcp_tools = _init_mcp_servers()
            if mcp_tools:
                lines = ["\n## MCP tools (loaded via external servers)"]
                for name, tool in mcp_tools.items():
                    desc = (tool.description or "").split(".")[0][:80]
                    lines.append(f"- `{name}` — {desc}")
                lines.append(
                    "\nThese tools work exactly like built-in tools — call them "
                    "by name via function calling."
                )
                parts.append("\n".join(lines))
        except ImportError:
            pass
        # append promise mechanism info so the LLM knows about async ops
        parts.append(
            "\n## Async operations (promises)\n"
            "Some tools return a PROMISE for long-running operations. "
            "You can check the status with `resolve_promise`. "
            "The operation continues in the background — "
            "you don't need to poll, just check back when you need the result."
        )
        return "\n\n".join(parts) if parts else "You are a helpful assistant."
    def _format_chat_history(self) -> str:
        """Serialize internal JSON history to text for the LLM prompt."""
        # Anchor: first user message reminds the LLM of the active task,
        # preventing context drift when history is long or compacted.
        anchor = ""
        for msg in self.chat_history:
            if msg["role"] == "user":
                anchor = f"\n[Active task: {msg['content'][:160]}]"
                break
        parts = [f"Chat history:{anchor}"]
        for msg in self.chat_history:
            role = msg["role"]
            conversation_round = msg.get("round")
            if role == "user":
                parts.append(f"[round {conversation_round}]\nUser: {msg['content']}")
            elif role == "agent":
                parts.append(f"Agent: {msg['content']}")
                if msg.get("reasoning"):
                    parts.append(f"[Reasoning]\n{msg['reasoning']}[/Reasoning]")
            elif role == "tool":
                parts.append(f"Tool [{msg.get('name', '?')}]: {msg.get('result', '')}")
            elif role == "meta":
                parts.append(msg["content"])
        return "\n".join(parts)
    def _build_llm_messages(self) -> list[dict]:
        """Build OpenAI-format messages list from internal chat history.
        Converts the internal JSON history into the message format the LLM
        API expects (assistant with tool_calls, tool with tool_call_id, etc.)
        so the model sees a conversation structure matching its training.
        """
        msgs: list[dict] = []
        # ── inject resolved promises into context ──
        newly_resolved = [pid for pid in list(self._resolved_since_last_build)
                          if self._promises.get(pid, {}).get("status") == "resolved"
                          and not self._promises[pid].get("_injected")]
        if newly_resolved:
            parts = []
            for pid in newly_resolved:
                info = self._promises[pid]
                parts.append(f"[PROMISE {pid} resolved]\n{str(info.get('result', ''))}")
                info["_injected"] = True
                self._resolved_since_last_build.discard(pid)
            msgs.append({"role": "system", "content": "\n\n".join(parts)})
        for msg in self.chat_history:
            role = msg["role"]
            if role == "user":
                msgs.append({"role": "user", "content": msg["content"]})
            elif role == "agent":
                content = msg.get("content", "")
                # DeepSeek requires content to be a non-null string when
                # there are no tool_calls; OpenAI spec says null is fine
                # when tool_calls are present.
                if msg.get("tool_calls") and not content:
                    content = None
                entry: dict = {"role": "assistant", "content": content}
                if msg.get("reasoning"):
                    # DeepSeek thinking mode requires reasoning_content to be
                    # passed back in assistant messages on subsequent requests.
                    entry["reasoning_content"] = msg["reasoning"]
                if msg.get("tool_calls"):
                    entry["tool_calls"] = msg["tool_calls"]
                msgs.append(entry)
            elif role == "tool":
                tool_id = msg.get("tool_call_id", "")
                if tool_id:
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": msg.get("result", ""),
                    })
                else:
                    # Tool without tool_call_id -- try to match by position
                    # to the last assistant's tool_calls.
                    _matched = False
                    if msgs and msgs[-1]["role"] == "assistant":
                        _last = msgs[-1]
                        _tcs = _last.get("tool_calls") or []
                        _existing = sum(
                            1 for m in reversed(msgs)
                            if m["role"] == "tool"
                        )
                        if _existing < len(_tcs):
                            _tc_entry = _tcs[_existing]
                            _tc_id = _tc_entry.get("id", "") if isinstance(_tc_entry, dict) else ""
                            if _tc_id:
                                msgs.append({
                                    "role": "tool",
                                    "tool_call_id": _tc_id,
                                    "content": msg.get("result", ""),
                                })
                                _matched = True
                    if not _matched:
                        # True orphan -- fold into preceding assistant as text
                        if msgs and msgs[-1]["role"] == "assistant":
                            suffix = (
                                f"\n[Tool result ({msg.get('name', '?')}): "
                                f"{msg.get('result', '')}]"
                            )
                            existing = msgs[-1]["content"] or ""
                            msgs[-1]["content"] = existing + suffix
            elif role == "meta":
                msgs.append({"role": "system", "content": msg["content"]})
        # ── safety: validate tool_calls/tool message alignment ──
        # If an assistant message has N tool_calls but fewer than N tool
        # messages follow (e.g. due to interrupt or partial compaction),
        # strip the unmatched tool_calls to prevent API 400 errors.
        i = 0
        while i < len(msgs):
            m = msgs[i]
            if m["role"] == "assistant" and m.get("tool_calls"):
                tcs = m["tool_calls"]
                # Count consecutive tool messages after this assistant
                j = i + 1
                tool_count = 0
                while j < len(msgs) and msgs[j]["role"] == "tool":
                    tool_count += 1
                    j += 1
                if tool_count < len(tcs):
                    # Strip tool_calls that have no matching tool message
                    remaining = tcs[:tool_count]
                    m["tool_calls"] = remaining
                    if not remaining:
                        m.pop("tool_calls", None)
                    # Fold stripped tool names into content so info isn't lost
                    if tool_count < len(tcs):
                        stripped = tcs[tool_count:]
                        names = ", ".join(
                            tc.get("function", {}).get("name", "?") for tc in stripped
                        )
                        suffix = f"\n[Tool calls without results: {names}]"
                        existing = m.get("content") or ""
                        m["content"] = existing + suffix if existing else suffix
            i += 1
        # Safety: fold orphaned tool messages — a tool message is orphaned
        # only when there is NO preceding assistant with tool_calls (scanning
        # backward past any consecutive tool messages).  If consecutive tools
        # appear after a valid assistant, leave them in place so tool_calls
        # and tool messages stay 1:1 aligned.
        i = 1
        while i < len(msgs):
            if msgs[i]["role"] == "tool":
                # Scan backward past any consecutive tool messages
                k = i - 1
                while k >= 0 and msgs[k]["role"] == "tool":
                    k -= 1
                if k < 0 or not (msgs[k]["role"] == "assistant" and msgs[k].get("tool_calls")):
                    # True orphan — fold into the nearest non-tool predecessor
                    prev = msgs[k] if k >= 0 else msgs[i - 1]
                    suffix = f"\n[Tool result: {msgs[i].get('content', '')}]"
                    existing = prev.get("content") or ""
                    prev["content"] = existing + suffix if existing else suffix
                    msgs.pop(i)
                    continue
            i += 1
        return msgs
    # ── truncation thresholds ──
    _TRUNCATION_FULL = 5000        # 以下：原样返回
    _TRUNCATION_SUMMARY = 50000    # 以下：摘要 + 前20后10行
    _TRUNCATION_ABANDON = 100000   # 以上：只存文件，字数行数
    @staticmethod
    def _save_to_temp(text: str, tool_name: str) -> str:
        """Save full output to .temp/{tool_name}_{hash}.txt, return filename."""
        import os, hashlib
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".temp")
        os.makedirs(temp_dir, exist_ok=True)
        h = hashlib.md5(text[:1000].encode()).hexdigest()[:8]
        fname = f"{tool_name.replace('/', '_')}_{h}.txt"
        fpath = os.path.join(temp_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text)
        return os.path.relpath(fpath, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    @staticmethod
    def _heuristic_summary(text: str) -> dict:
        """Quick heuristic summary without LLM."""
        lines = text.split("\n")
        total_lines = len(lines)
        total_chars = len(text)
        # Content type detection
        content_type = "text"
        first_line = lines[0].strip() if lines else ""
        if first_line.startswith("{") or first_line.startswith("["):
            try:
                data = json.loads(text[:50000])  # partial parse
                if isinstance(data, dict):
                    content_type = f"JSON object ({len(data)} keys)"
                elif isinstance(data, list):
                    content_type = f"JSON array ({len(data)} items)"
            except (json.JSONDecodeError, ValueError):
                pass
        elif first_line.startswith("Mode") and "LastWriteTime" in text[:200]:
            content_type = "file listing"
        elif "Traceback" in text or "Error" in text[:2000]:
            content_type = "error log"
        elif first_line.startswith("#!") or "import " in text[:2000]:
            content_type = "source code"
        elif first_line.startswith("<!DOCTYPE") or first_line.startswith("<html"):
            content_type = "HTML"
        elif "|" in first_line and "-" in text[:500]:
            content_type = "table"
        # Pattern counts
        error_count = sum(text.count(p) for p in ("error", "Error", "ERROR"))
        warning_count = sum(text.count(p) for p in ("warning", "Warning", "WARNING"))
        return {
            "chars": total_chars,
            "lines": total_lines,
            "type": content_type,
            "errors": error_count,
            "warnings": warning_count,
            "first_line": first_line[:200],
            "last_line": (lines[-1].strip() if lines else "")[:200],
        }
    def _apply_truncation(self, raw: str, tool_name: str) -> str:
        """Smart truncation with .temp save + heuristic summary.
        Thresholds:
          ≤ 5,000    → 原样返回
          5k ~ 50k   → 存 .temp, 摘要 + 前20行 + 后10行
          50k ~ 100k → 存 .temp, 仅摘要
          > 100k     → 存 .temp, 仅字数行数
        """
        if len(raw) <= self._TRUNCATION_FULL:
            return raw
        # Save full content to .temp
        rel_path = self._save_to_temp(raw, tool_name)
        # Get heuristic summary
        info = self._heuristic_summary(raw)
        # Build the output
        if len(raw) > self._TRUNCATION_ABANDON:
            return (
                f"[LARGE OUTPUT] '{tool_name}' returned {info['chars']:,} chars "
                f"({info['lines']:,} lines). "
                f"Full content saved to {rel_path}.\n"
                f"Content type: {info['type']}\n"
                f"Use read_file(\"{rel_path}\") to read it."
            )
        if len(raw) > self._TRUNCATION_SUMMARY:
            return (
                f"[TRUNCATED] '{tool_name}' returned {info['chars']:,} chars "
                f"({info['lines']:,} lines). "
                f"Full content saved to {rel_path}.\n"
                f"Content type: {info['type']}  |  "
                f"Errors: {info['errors']}  Warnings: {info['warnings']}\n"
                f"First line: {info['first_line']}\n"
                f"Last line: {info['last_line']}\n"
                f"Use read_file(\"{rel_path}\") to read the full content."
            )
        # 5k ~ 50k: summary + head 20 + tail 10
        lines = raw.split("\n")
        head = "\n".join(lines[:20])
        tail = "\n".join(lines[-10:] if len(lines) > 10 else lines)
        return (
            f"[TRUNCATED] '{tool_name}' returned {info['chars']:,} chars "
            f"({info['lines']:,} lines). "
            f"Full content saved to {rel_path}.\n"
            f"Content type: {info['type']}  |  "
            f"Errors: {info['errors']}  Warnings: {info['warnings']}\n"
            f"--- first 20 lines ---\n{head}\n"
            f"--- last 10 lines ---\n{tail}\n"
            f"---\n"
            f"Use read_file(\"{rel_path}\") to read the full content."
        )
    def _check_permission(self, tool_name: str, arguments: dict | str) -> str | None:
        """Check permission for a tool call.
        *arguments* is the tool arguments dict (or a JSON string — some
        providers send it serialised).  Returns ``None`` if allowed, or
        an error ``str`` if denied / rejected.
        """
        # Normalise: JSON string → dict
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
        level = self.permissions.check(tool_name, tool_args=arguments)
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
    # ── lifecycle hooks ──────────────────────────────────────────
    def _run_hook(self, event: str, context: dict) -> str | None:
        """Execute a lifecycle hook script for the active skill.
        *event* is one of "PreToolUse", "PostToolUse", etc.
        *context* is a dict of env vars to pass to the script.
        Returns the script's stdout (for PreToolUse, non-empty output
        may block the tool), or None if no hook is configured.
        """
        if not self._active_skill or not self._active_skill.hooks:
            return None
        script = self._active_skill.hooks.get(event)
        if not script:
            return None
        skill_dir = self._active_skill.skill_dir
        if not os.path.isabs(script):
            script = os.path.join(skill_dir, script)
        if not os.path.isfile(script):
            log.warning("Hook script not found: %s", script)
            return None
        # Pick the right interpreter based on extension
        ext = os.path.splitext(script)[1].lower()
        try:
            if ext == ".ps1":
                cmd = ["powershell", "-File", script]
            elif ext == ".sh":
                cmd = ["bash", script]
            elif ext == ".py":
                cmd = [sys.executable, script]
            else:
                cmd = [script]
            env = {**context, "CLAUDE_SKILL_DIR": skill_dir, "CLAUDE_HOOK_EVENT": event}
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                env={**os.environ, **env},
            )
            if result.returncode != 0:
                log.warning("Hook '%s' exited %d: %s", event, result.returncode, result.stderr.strip())
            stdout = result.stdout.strip()
            return stdout or None
        except subprocess.TimeoutExpired:
            log.warning("Hook '%s' timed out (30s)", event)
            return None
        except OSError as e:
            log.warning("Hook '%s' failed: %s", event, e)
            return None
    def _compact_history(self):
        """Compact chat history: remove tool noise from the middle region.
        DISABLED — was causing the LLM to fabricate tool results in text output
        by folding [Tool result (name): ...] into assistant messages, which the
        model learned to imitate instead of calling real tools.
        """
        return
        total = len(self._format_chat_history())
        if total <= self.max_history_chars:
            return
        user_indices = [i for i, m in enumerate(self.chat_history) if m["role"] == "user"]
        protect_count = min(self.protect_last_rounds, len(user_indices))
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
        # Before removing tool entries, fold their results into the
        # preceding assistant message as text so structured messages
        # still carry the information after compaction.  Search both
        # *head* and *compacted* (entries already processed from middle)
        # so an assistant in the middle section is also found.
        compacted: list[dict] = []
        for m in middle:
            if m["role"] == "tool":
                result_text = m.get("result", "")
                name = m.get("name", "?")
                # Search compacted first, then head.  Only pop tool_calls
                # when folding into compacted — head entries keep their
                # tool_calls intact so surviving tool messages stay paired.
                found = False
                for pool_name, pool in [("compacted", reversed(compacted)),
                                        ("head", reversed(head))]:
                    for entry in pool:
                        if entry["role"] == "agent":
                            suffix = f"\n[Tool result ({name}): {result_text}]"
                            existing = entry.get("content") or ""
                            entry["content"] = existing + suffix
                            if pool_name == "compacted":
                                entry.pop("tool_calls", None)
                            found = True
                            break
                    if found:
                        break
            else:
                compacted.append(m)
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
        """Append a user message with a [round N] marker and archive it."""
        if self.session_id is None:
            self.session_id = db.create_session()
            log.info("Created session #%s", self.session_id)
        log.info("[session=%s conversation_round=%s] User: %.120s", self.session_id, self._conversation_round + 1, text)
        self._conversation_round += 1
        self.chat_history.append({
            "role": "user", "content": text, "round": self._conversation_round,
        })
        db.save_message(self.session_id, "user", text, conversation_round=self._conversation_round)
        if self._conversation_round == 1:
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
        max_round = 0
        for msg in messages:
            conversation_round = msg.get("conversation_round", 0) or 0
            if conversation_round > max_round:
                max_round = conversation_round
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
                        "round": conversation_round,
                    }
                except (json.JSONDecodeError, TypeError, KeyError):
                    entry = {
                        "role": "tool",
                        "name": msg.get("tool_name", ""),
                        "arguments": "",
                        "result": msg.get("content", ""),
                        "round": conversation_round,
                    }
                tid = msg.get("tool_call_id")
                if tid:
                    entry["tool_call_id"] = tid
            else:
                entry = {
                    "role": role,
                    "content": msg.get("content", ""),
                    "round": conversation_round,
                }
                if role == "agent" and msg.get("reasoning"):
                    entry["reasoning"] = msg["reasoning"]
                if role == "agent":
                    tcs = msg.get("tool_calls")
                    if tcs:
                        try:
                            entry["tool_calls"] = json.loads(tcs)
                        except (json.JSONDecodeError, TypeError):
                            pass
            self.chat_history.append(entry)
        self._conversation_round = max_round
        self.session_id = session_id
        return True
    def get_current_session_info(self) -> dict:
        """Return info about the current session."""
        sess = db.get_session_by_id(self.session_id)
        if not sess:
            return {"session_id": self.session_id, "round": self._conversation_round}
        return {
            "session_id": sess["id"],
            "title": sess.get("title", ""),
            "marker": sess.get("marker"),
            "created_at": sess.get("created_at", ""),
            "round": self._conversation_round,
        }
    def reset_session(self):
        """Start a fresh conversation session"""
        self.chat_history = []
        self._conversation_round = 0
        self.session_id = None
        log.info("Session reset")
    # ── interrupt ──────────────────────────────────────────
    def interrupt(self):
        """Request the agent to stop after the current tool call."""
        self._interrupt_requested = True
        self.stop_event.set()
    # ── btw ────────────────────────────────────────────────
    def btw(self, msg: str):
        """Queue a BTW (By The Way) note for the next user instruction."""
        self._btw_queue.append(msg)
    def consume_btw(self) -> list[str]:
        """Drain and return all queued BTW notes."""
        notes = list(self._btw_queue)
        self._btw_queue.clear()
        return notes
    # ── promise mechanism ──────────────────────────────
    def create_promise(self, promise_id: str, meta: dict = None, callback: callable = None) -> str:
        """Register a pending async operation. Returns the promise_id.
        *meta* is an optional dict stored alongside the promise for
        introspection (e.g. check_type, start_time, job_id).
        """
        self._promises[promise_id] = {"status": "pending", "result": None, "meta": meta or {}}
        self._resolved_since_last_build.add(promise_id)
        if callback:
            self._promise_callbacks[promise_id] = callback
        return promise_id
    def cancel_promise(self, promise_id: str) -> bool:
        """Mark a pending promise as cancelled.  Returns True if actually cancelled."""
        info = self._promises.get(promise_id)
        if info and info["status"] == "pending":
            info["status"] = "cancelled"
            return True
        return False
    def fail_promise(self, promise_id: str, error: str) -> bool:
        """Mark a promise as failed (external job error / cancellation)."""
        info = self._promises.get(promise_id)
        if info and info["status"] == "pending":
            info["status"] = "failed"
            info["result"] = {"error": error}
            return True
        return False
    def resolve_promise(self, promise_id: str, result: dict) -> None:
        """Deliver an async result. Sets promise status and triggers callback."""
        info = self._promises.get(promise_id)
        if not info or info["status"] != "pending":
            return
        info["status"] = "resolved"
        info["result"] = result
        self._resolved_since_last_build.add(promise_id)
        callback = self._promise_callbacks.pop(promise_id, None)
        if callback:
            try:
                callback(result)
            except Exception as e:
                log.error("Promise callback failed for %s: %s", promise_id, e)
        # Emit event so the TUI can react
        self.emit({"type": "promise_resolved", "data": {"id": promise_id, "result": result}})
    def get_promise(self, promise_id: str) -> dict | None:
        """Query promise status. Returns {status, result, meta} or None if unknown."""
        return self._promises.get(promise_id)
    def emit(self, event: dict):
        """Write a JSON event to stdout."""
        print(json.dumps(event, ensure_ascii=False), flush=True)
    def process_with_llm(self):
        """Run the LLM (streaming), handle tool calls, emit events.
        Loops until the agent produces a final answer (no tool calls).
        max_llm_calls=0 means unlimited; otherwise caps the number of LLM rounds.
        """
        # ── reset interrupt state from any previous interrupted call ──
        self._interrupt_requested = False
        self.stop_event.clear()
        self._interrupted = False
        # ── re-read prompt files so memory writes take effect immediately ──
        if not self._skill_active:
            self.llm.system_prompt = self._build_prompt(self.cfg)
        turn = 0
        while True:
            # ── interrupt check before starting a new LLM round ──
            if self._interrupt_requested or self.stop_event.is_set():
                self._interrupt_requested = False
                self._interrupted = True
                self.chat_history.append({
                    'role': 'meta',
                    'content': '[SYSTEM] User interrupted. Report what was done so far.',
                    'round': self._conversation_round,
                })
                break
            turn += 1
            if self.max_llm_calls > 0 and turn > self.max_llm_calls:
                break
            llm_messages = self._build_llm_messages()
            self.emit({"type": "start"})
            stream = self.llm.stream_response_messages(llm_messages)
            text_parts = []
            reasoning_parts = []
            tool_call_deltas = {}
            for chunk in stream:
                # ── check interrupt mid-stream ──
                if self._interrupt_requested:
                    break
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
                    reasoning_parts.append(delta.reasoning_content)
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
            # ── If interrupted mid-stream, discard partial response ──
            if self._interrupt_requested:
                self._interrupted = True
                self.chat_history.append({
                    "role": "meta",
                    "content": "[SYSTEM] User interrupted. Report what was done so far.",
                    "round": self._conversation_round,
                })
                break
            self.emit({"type": "done"})
            text = "".join(text_parts)
            reasoning = "".join(reasoning_parts)
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
            # Save assistant entry (with tool_calls if any, for structured messages)
            if text or reasoning or tool_calls:
                entry: dict = {
                    "role": "agent", "content": text, "round": self._conversation_round,
                }
                if reasoning:
                    entry["reasoning"] = reasoning
                if tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in tool_calls
                    ]
                self.chat_history.append(entry)
                db.save_message(self.session_id, "agent", text, conversation_round=self._conversation_round,
                                reasoning=reasoning,
                                tool_calls=json.dumps([{
                                    "id": tc["id"], "type": "function",
                                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                                } for tc in tool_calls], ensure_ascii=False) if tool_calls else "")
            # No tool calls → this turn is the final answer
            if not tool_calls:
                # Safety net: if reasoning described tool calls but never
                # invoked them (common with DeepSeek), nudge the model
                # instead of stopping silently.  Limit to 1 retry to
                # avoid infinite loops.
                if reasoning and not text and self._reasoning_only_retries < 1:
                    self._reasoning_only_retries += 1
                    self.chat_history.append({
                        "role": "meta",
                        "content": (
                            "[SYSTEM] You described calling tools in your "
                            "reasoning but did not actually invoke any tool. "
                            "If you need a tool, call it now using the proper "
                            "function-calling format. If not, answer directly."
                        ),
                    })
                    log.info("Reasoning-only turn — giving model another chance")
                    continue
                break
            # Execute each tool and add results to history
            self._interrupted = False
            for tc in tool_calls:
                log.info(
                    "[session=%s conversation_round=%s] Tool call: %s",
                    self.session_id, self._conversation_round, tc["name"],
                )
                # ── interrupt check before each tool ──
                if self.stop_event.is_set() or self._interrupt_requested:
                    self._interrupt_requested = False
                    self._interrupted = True
                    self.chat_history.append({
                        'role': 'meta',
                        'content': (
                            '[SYSTEM] User interrupted the task. '
                            'Stop and report what was done so far.'
                        ),
                        'round': self._conversation_round,
                    })
                    break
                # ── permission check ──
                result_str = self._check_permission(tc["name"], tc["arguments"])
                _tool_failed = False
                if result_str is None:
                    # permitted — execute normally
                    raw_args = tc["arguments"]
                    args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    # ── PreToolUse hook ──
                    hook_result = self._run_hook("PreToolUse", {
                        "CLAUDE_TOOL_NAME": tc["name"],
                        "CLAUDE_TOOL_ARGUMENTS": tc["arguments"],
                    })
                    if hook_result:
                        try:
                            hook_data = json.loads(hook_result)
                            if hook_data.get("block"):
                                reason = hook_data.get("reason", "PreToolUse hook blocked this call")
                                result_str = f"[BLOCKED_BY_HOOK] {reason}"
                        except json.JSONDecodeError:
                            pass
                    if result_str is None:
                        # ── auto-load skill if a _script tool is missing ──
                        tool_obj = self.tools.get(tc["name"])
                        if tool_obj is None:
                            _m = re.match(r"^(.+)_script$", tc["name"])
                            if _m:
                                _skill = get_skill(_m.group(1))
                                if _skill:
                                    log.info("Auto-loading skill '%s' for tool '%s'",
                                              _m.group(1), tc["name"])
                                    _skill.on_load(self)
                                    tool_obj = self.tools.get(tc["name"])
                        try:
                            if tool_obj is None:
                                raise KeyError(tc["name"])
                            # ── run tool with interrupt support ──
                            import concurrent.futures
                            _exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                            _fut = _exec.submit(tool_obj.execute, **args_dict)
                            while not _fut.done():
                                if self.stop_event.wait(timeout=0.5):
                                    _exec.shutdown(wait=False)
                                    raise InterruptedError("User interrupted")
                            result = _fut.result()
                            # MCP tools return JSON strings — parse if needed
                            if isinstance(result, str) and result.strip().startswith('{'):
                                try:
                                    result = json.loads(result)
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    pass
                            # detect failures in structured tool results
                            if isinstance(result, dict):
                                if result.get("error"):
                                    _tool_failed = True
                                elif result.get("exit_code", 0) != 0:
                                    _tool_failed = True
                                result_str = self._apply_truncation(str(result), tc["name"])
                            elif result is not None:
                                result_str = self._apply_truncation(str(result), tc["name"])
                            else:
                                result_str = "[NO RESULT] Tool returned None."
                                _tool_failed = True
                        except json.JSONDecodeError as e:
                            result_str = f"Error: Failed to parse tool arguments: {e}"
                            _tool_failed = True
                        except InterruptedError:
                            result_str = "[SYSTEM] Tool execution interrupted by user."
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
                            "round": self._conversation_round,
                        })
                        self._tool_failures[tc["name"]] = 0
                else:
                    self._tool_failures[tc["name"]] = 0
                # ── repeated command detection ──
                if tc["name"] == "cmd_execute":
                    try:
                        args = json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"]
                        cmd = args.get("command", "")
                        if cmd:
                            self._cmd_history.append(cmd)
                            if len(self._cmd_history) >= 3 and len(set(self._cmd_history[-3:])) == 1:
                                self.chat_history.append({
                                    "role": "meta",
                                    "content": (
                                        f"[SYSTEM] The exact same command was executed "
                                        f"{len(self._cmd_history)} times in a row:\n  {cmd}\n"
                                        f"The output keeps getting truncated. Do NOT retry "
                                        f"the same command. Use a different approach "
                                        f"(e.g., redirect to a file, use a Python script)."
                                    ),
                                    "round": self._conversation_round,
                                })
                                self._cmd_history.clear()
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                # ---- interrupt checkpoint ----
                if self._interrupt_requested or self.stop_event.is_set():
                    self._interrupt_requested = False
                    self._interrupted = True
                    self.chat_history.append({
                        'role': 'meta',
                        'content': (
                            '[SYSTEM] User interrupted the task. '
                            'Stop and report what was done so far.'
                        ),
                        'round': self._conversation_round,
                    })
                    break
                self.chat_history.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "result": result_str,
                    "round": self._conversation_round,
                })
                self.emit({
                    "type": "tool_result",
                    "name": tc["name"],
                    "result": result_str,
                })
                # ── PostToolUse hook ──
                self._run_hook("PostToolUse", {
                    "CLAUDE_TOOL_NAME": tc["name"],
                    "CLAUDE_TOOL_ARGUMENTS": tc["arguments"],
                    "CLAUDE_TOOL_RESULT": result_str,
                    "CLAUDE_TOOL_ERROR": result_str if is_failure else "",
                })
                db.save_message(
                    self.session_id, "tool",
                    json.dumps({"args": tc["arguments"], "result": result_str}, ensure_ascii=False),
                    tool_name=tc["name"], conversation_round=self._conversation_round,
                    tool_call_id=tc.get("id", ""),
                )
            # ── compact history if needed ──
            self._compact_history()
            # ── if interrupted, stop the outer loop ──
            if self._interrupted:
                break
        log.info(
            "[session=%s conversation_round=%s] LLM done (tool_calls=%d)",
            self.session_id, self._conversation_round, len(tool_calls),
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
