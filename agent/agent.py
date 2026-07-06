import asyncio
import json
import os
import re
import subprocess
import sys
import time

from llm import LLM
from config import load_config
from content_block import (
    is_blocks, text_block, image_url_block,
    has_image_blocks, extract_text,
)
from observation_store import ObservationStore
from logger import get_logger
from permissions import PermissionManager
import database as db
from skill import get_skill
from hooks import HookRegistry, HookContext, HookEvent, _LEGACY_HOOK_EVENT

log = get_logger(__name__)


def _detect_shell() -> str:
    import platform, shutil
    if platform.system() != "Windows":
        return "sh -c"
    git_path = shutil.which("git")
    if git_path:
        git_dir = os.path.dirname(os.path.dirname(git_path))
        bash = os.path.join(git_dir, "bin", "bash.exe")
        if os.path.isfile(bash):
            return f"Git Bash ({bash} -c)"
    for exe in ("pwsh.exe", "powershell.exe"):
        if shutil.which(exe):
            return f"{exe} -Command"
    return "cmd /c"


class Agent:
    def __init__(self, tools: dict = None, memory_enabled: bool = True):
        cfg = load_config()
        self.cfg = cfg
        self._memory_enabled = memory_enabled

        # ── Multimodal support (must be before _build_prompt) ──────
        self._is_multimodal = cfg.get("llm", {}).get("multimodal", False)
        self._visual_resolver = None
        if self._is_multimodal:
            from visual import VisualResolver
            self._visual_resolver = VisualResolver(
                provider=cfg["llm"].get("provider", ""),
                api_key=cfg["llm"].get("api_key", ""),
                base_url=cfg["llm"].get("base_url", ""),
            )
        self._project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.observation_store = ObservationStore()

        api_key = cfg["llm"]["api_key"]
        base_url = cfg["llm"].get("base_url", "https://api.deepseek.com/v1")
        model = cfg["llm"].get("model", "deepseek-v4-flash")
        system_prompt = self._build_prompt(cfg)
        self.llm = LLM(api_key, system_prompt, tools, base_url=base_url, model=model)
        self.tools = tools
        self._skill_active = False
        self._active_skill = None
        self.permissions = PermissionManager(cfg.get("permissions", {}))
        self.permissions.load_modes(cfg.get("permission_modes", {}))
        self._confirm_callback = None
        self.chat_history: list[dict] = []
        db.init_db()
        self.session_id = None
        self._conversation_round = 0
        self._tool_failures: dict[str, int] = {}
        self._reasoning_only_retries = 0
        self._cmd_history: list[str] = []
        self.stop_event = asyncio.Event()
        self._last_prompt_tokens = 0
        self._btw_queue: list[str] = []
        self._workspace_root: str | None = None
        self._sent_skill_names: set[str] = set()
        if self.tools:
            for t in self.tools.values():
                if hasattr(t, 'stop_event'):
                    t.stop_event = self.stop_event
        self.current_plan = None
        # promise mechanism (temporarily disabled)
        self._promises: dict[str, dict] = {}
        self._promise_callbacks: dict[str, callable] = {}
        self._resolved_since_last_build: set[str] = set()
        if self.tools:
            for t in self.tools.values():
                if hasattr(t, 'agent_ref'):
                    t.agent_ref = self
        self.max_llm_calls = cfg.get("max_turns", cfg.get("max_llm_calls", 80))
        self.chat_cfg = cfg.get("chat_history", {})
        log.info("Agent initialized (model=%s, max_llm_calls=%s)", self.llm.model, self.max_llm_calls)
        self.max_history_chars = self.chat_cfg.get("max_chars", 10000)
        self.trim_to_chars = self.chat_cfg.get("trim_to", 5000)
        self.protect_last_rounds = self.chat_cfg.get("protect_last_rounds", 3)
        self.strategy = self.chat_cfg.get("strategy", "compact")

        # ── Hook system ───────────────────────────────────────────────────
        self.hooks = HookRegistry()
        # Load hooks from config
        hooks_config = cfg.get("hooks", {})
        from hooks_config import load_hooks_from_config, DEFAULT_HOOKS_CONFIG

        # Merge config hooks with defaults
        merged_hooks_config = DEFAULT_HOOKS_CONFIG.copy()
        if hooks_config:
            # Merge register lists (config overrides defaults)
            config_register = hooks_config.get("register")
            if isinstance(config_register, list):
                # Remove disabled hooks from defaults
                disabled_events = {h["event"] for h in config_register if h.get("enabled", False) is False}
                active_config_hooks = [h for h in config_register if h.get("enabled", True) is not False]

                # Start with defaults (excluding disabled)
                merged_hooks_config["register"] = [
                    h for h in DEFAULT_HOOKS_CONFIG["register"]
                    if h["event"] not in disabled_events
                ] + active_config_hooks

        load_hooks_from_config(merged_hooks_config, self.hooks)
    def _build_prompt(self, cfg):
        """Load and join prompt files listed in config."""
        # ── Memory View compilation (session start, one-shot) ──────────
        if self._memory_enabled and cfg.get("memory", {}).get("enabled", True):
            try:
                from memory.fact import FactStore
                from memory.topic import TopicRegistry
                from memory.compiler import compile_view

                store = FactStore()
                tr = TopicRegistry()
                if store.has_changed_since_last_compile():
                    # Use aux model if available, otherwise main model
                    mem_cfg = cfg.get("aux") or cfg.get("llm", {})
                    compile_view(store, tr, llm_cfg=mem_cfg)
            except Exception as e:
                log.warning("Memory compilation skipped: %s", e)

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
        from datetime import datetime
        _now = datetime.now().strftime("%Y/%m/%d - %H:%M")
        parts.append(
            f"\n## Runtime context\n"
            f"Current time: {_now}\n"
            f"Platform: {_platform}\n"
            f"Working directory: {_cwd}\n"
            f"Project root: {_project_root}\n"
            f"Shell: {_shell} (each command runs in a fresh shell, cd does NOT persist)\n"
            f"Use absolute paths or chain commands with && to keep the same session."
        )
        # Skill listing is injected dynamically as a system-reminder message
        # in _build_llm_messages(), available skills are listed there.
        # Use the `skill` tool to load and execute a skill.
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
        # ── multimodal vision instruction ──
        if self._is_multimodal:
            parts.append(
                "\n## Vision\n"
                "You can directly see images in user messages. "
                "Images appear as inline content blocks in the message "
                "(not as text `[file:...]` markers which are removed).\n"
                "- If an image is already visible in the user message, "
                "DO NOT call `vision_query` — just describe what you see.\n"
                "- Only call `vision_query` when the image reference is "
                "a URL or file path in plain text (not attached as upload).\n"
                "- When `vision_query` resolves an image, it becomes "
                "visible to you directly — no additional tool needed."
            )
        return "\n\n".join(parts) if parts else "You are a helpful assistant."

    # ── Content Block helpers ─────────────────────────────────────

    def _resolve_blocks(self, blocks_or_str: str | list[dict],
                        resolve_images: bool = True) -> str | list[dict]:
        """Resolve Content Blocks for LLM consumption.

        - str → returned as-is
        - *resolve_images=True* (current turn): ``file://`` → base64.
        - *resolve_images=False* (older history): image_url → ``(image: url)``
          text note — LLM knows an image was shared without wasted tokens.
        """
        if isinstance(blocks_or_str, str):
            return blocks_or_str
        if not is_blocks(blocks_or_str):
            return blocks_or_str

        if not resolve_images:
            stripped: list[dict] = []
            for b in blocks_or_str:
                if b.get("type") == "image_url":
                    url = (b.get("image_url") or {}).get("url", "")
                    label = url[7:] if url.startswith("file://") else url
                    stripped.append(text_block(f"(image: {label})"))
                    continue
                stripped.append(b)
            if not stripped:
                return ""
            if len(stripped) == 1 and stripped[0].get("type") == "text":
                return stripped[0].get("text", "")
            return stripped

        resolved: list[dict] = []
        for b in blocks_or_str:
            if b.get("type") == "image_url":
                url = (b.get("image_url") or {}).get("url", "")
                detail = (b.get("image_url") or {}).get("detail", "high")
                if url.startswith("file://"):
                    materialised = self._materialise_file_url(url[7:])
                    if materialised:
                        resolved.append(image_url_block(materialised, detail))
                else:
                    resolved.append(b)
            else:
                resolved.append(b)
        if len(resolved) == 0:
            return ""
        if len(resolved) == 1 and resolved[0].get("type") == "text":
            return resolved[0].get("text", "")
        return resolved

    def _materialise_file_url(self, path: str) -> str | None:
        """Convert a local *path* to a base64 ``data:`` URL.

        Tries ``VisualResolver`` first (which may use provider upload APIs).
        Falls back to plain base64 encoding.
        """
        # strip query params if any
        if "?" in path:
            path = path.split("?")[0]
        if self._visual_resolver:
            return self._visual_resolver.resolve(path)
        # simple fallback
        import base64 as _b64
        ext = os.path.splitext(path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                     ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}
        try:
            with open(path, "rb") as f:
                b64 = _b64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime_map.get(ext, 'image/png')};base64,{b64}"
        except Exception:
            return None

    def _format_chat_history(self) -> str:
        """Serialize internal JSON history to text for the LLM prompt."""
        # Anchor: first user message reminds the LLM of the active task,
        # preventing context drift when history is long or compacted.
        anchor = ""
        for msg in self.chat_history:
            if msg["role"] == "user":
                anchor_text = extract_text(msg["content"]) if is_blocks(msg.get("content")) else str(msg.get("content", ""))
                anchor = f"\n[Active task: {anchor_text[:160]}]"
                break
        parts = [f"Chat history:{anchor}"]
        for msg in self.chat_history:
            role = msg["role"]
            conversation_round = msg.get("round")
            if role == "user":
                user_content = extract_text(msg["content"]) if is_blocks(msg.get("content")) else msg.get("content", "")
                parts.append(f"[round {conversation_round}]\nUser: {user_content}")
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

        # ── skill listing (dynamic, with dedup) ──
        try:
            from skill import all_skills
            current_skills = all_skills()
            new_skills = [s for s in current_skills if s.name not in self._sent_skill_names]
            if new_skills:
                lines = [
                    "<system-reminder>",
                    "The following skills are available for use with the Skill tool:",
                ]
                for s in new_skills:
                    desc = s.description or "(no description)"
                    if s.when_to_use:
                        desc += f" — {s.when_to_use}"
                    lines.append(f"- {s.name}: {desc}")
                lines.append(
                    "When a skill matches the user's request, "
                    "invoke the `skill` tool BEFORE generating any other response."
                )
                lines.append("</system-reminder>")
                msgs.append({"role": "system", "content": "\n".join(lines)})
                for s in new_skills:
                    self._sent_skill_names.add(s.name)
        except ImportError:
            pass

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
        # Count user messages so we only resolve images for the latest N
        _user_indices = [j for j, m in enumerate(self.chat_history) if m["role"] == "user"]
        _resolve_count = _user_indices[-2:] if len(_user_indices) > 2 else _user_indices  # last 2
        for msg_idx, msg in enumerate(self.chat_history):
            role = msg["role"]
            if role == "user":
                _resolve = msg_idx in _resolve_count
                content = self._resolve_blocks(msg["content"], resolve_images=_resolve) if self._is_multimodal else msg["content"]
                msgs.append({"role": "user", "content": content})
            elif role == "agent":
                content = msg.get("content", "")
                # DeepSeek requires content to be a non-null string when
                # there are no tool_calls; OpenAI spec says null is fine
                # when tool_calls are present.
                if msg.get("tool_calls") and not content:
                    content = None
                entry: dict = {"role": "assistant", "content": content}
                # reasoning_content is DeepSeek-specific; skip for other providers
                _provider = (self.cfg.get("llm", {}).get("provider", "") or "").lower()
                if _provider == "deepseek" and msg.get("reasoning") and msg.get("tool_calls"):
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
        # Match tool_calls to tool messages by tool_call_id.
        # Strip any tool_calls whose ID has no response (prevent 400 errors).
        i = 0
        while i < len(msgs):
            m = msgs[i]
            if m["role"] == "assistant" and m.get("tool_calls"):
                tcs = m["tool_calls"]
                # Collect IDs from tool messages that immediately follow
                responded_ids = set()
                j = i + 1
                while j < len(msgs) and msgs[j]["role"] == "tool":
                    tid = msgs[j].get("tool_call_id", "")
                    if tid:
                        responded_ids.add(tid)
                    j += 1
                # Keep only tool_calls whose ID has a response
                matched = [tc for tc in tcs if tc.get("id", "") in responded_ids]
                unmatched = [tc for tc in tcs if tc.get("id", "") not in responded_ids]
                if unmatched:
                    if matched:
                        m["tool_calls"] = matched
                    else:
                        m.pop("tool_calls", None)
                    names = ", ".join(
                        tc.get("function", {}).get("name", "?") for tc in unmatched
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
        # ── attach images from observation_store at request boundary ──
        if self._is_multimodal and self.observation_store.has_images():
            img_uris = self.observation_store.pop_attachable_images()
            if img_uris:
                content: list = [{"type": "text", "text": "(image attached)"}]
                for uri in img_uris:
                    if uri.startswith("file://"):
                        resolved = self._materialise_file_url(uri[7:])
                        if resolved:
                            content.append({"type": "image_url", "image_url": {"url": resolved, "detail": "high"}})
                    elif uri:
                        content.append({"type": "image_url", "image_url": {"url": uri, "detail": "high"}})
                if len(content) > 1:
                    msgs.append({"role": "user", "content": content})
        # ── ensure tool contents are strings (dict → str for API compat) ──
        for m in msgs:
            if m["role"] == "tool" and isinstance(m.get("content"), dict):
                c = m["content"]
                m["content"] = c.get("message", str(c))
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
    async def _check_permission(self, tool_name: str, arguments: dict | str) -> str | None:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}

        # Dispatch PERMISSION_CHECK hook (observation-only, cannot override)
        await self.hooks.dispatch_fire_and_forget(
            HookContext(
                event=HookEvent.PERMISSION_CHECK,
                agent=self,
                timestamp=time.time(),
                tool_name=tool_name,
                tool_arguments=arguments,
                metadata={"permission_level": None},
            )
        )

        level = self.permissions.check(tool_name, tool_args=arguments)
        if level == "deny":
            # Dispatch TOOL_DENIED hook
            await self.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.TOOL_DENIED,
                    agent=self,
                    timestamp=time.time(),
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    metadata={"reason": "permission_denied"},
                )
            )
            return (
                f"[PERMISSION_DENIED] Tool '{tool_name}' is restricted by "
                f"permission settings. Do NOT retry — it will fail again."
            )
        # ask_user is an interactive tool that already asks the user;
        # requiring a separate permission prompt would double the popups.
        if tool_name == "ask_user":
            return None
        if level == "ask" and self._confirm_callback:
            if asyncio.iscoroutinefunction(self._confirm_callback):
                result = await self._confirm_callback(tool_name, arguments)
            else:
                result = self._confirm_callback(tool_name, arguments)
            if result is True:
                return None
            if result == "always":
                self.permissions.set_override(tool_name, "allow")
                return None
            if result == "never":
                self.permissions.set_override(tool_name, "deny")
                # Dispatch TOOL_DENIED hook (user rejected)
                await self.hooks.dispatch_fire_and_forget(
                    HookContext(
                        event=HookEvent.TOOL_DENIED,
                        agent=self,
                        timestamp=time.time(),
                        tool_name=tool_name,
                        tool_arguments=arguments,
                        metadata={"reason": "user_rejected_never"},
                    )
                )
                return (
                    f"[REJECTED_BY_USER] Tool '{tool_name}' was blocked — "
                    f"the user chose to never allow it. Do NOT retry."
                )
            # Dispatch TOOL_DENIED hook (user rejected)
            await self.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.TOOL_DENIED,
                    agent=self,
                    timestamp=time.time(),
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    metadata={"reason": "user_rejected_once"},
                )
            )
            return (
                f"[REJECTED_BY_USER] Tool '{tool_name}' was not approved by the "
                f"user. Try a different approach or ask the user."
            )
        return None
    # ── lifecycle hooks ──────────────────────────────────────────
    async def _run_hook(self, event: str, context: dict) -> str | None:
        """Run hook (legacy external process shim).

        This method maintains backward compatibility with skill-based external
        process hooks. It also triggers HookRegistry hooks for the same event.

        DEPRECATED: New code should use HookRegistry directly via self.hooks.dispatch().

        Args:
            event: Legacy event name (e.g., "PreToolUse", "PostToolUse")
            context: Context dictionary (passed as env vars to external process)

        Returns:
            String result from external process hook, or None
        """
        # ── Trigger HookRegistry hooks (new system) ────────────────────────
        hook_event = _LEGACY_HOOK_EVENT.get(event)
        if hook_event:
            # Build HookContext from legacy context dict
            hook_ctx = HookContext(
                event=hook_event,
                agent=self,
                timestamp=time.time(),
                tool_name=context.get("LINAR_TOOL_NAME") or context.get("ECHOLILY_TOOL_NAME", ""),
                tool_arguments=context.get("LINAR_TOOL_ARGUMENTS") or context.get("ECHOLILY_TOOL_ARGUMENTS", ""),
                tool_result=context.get("LINAR_TOOL_RESULT") or context.get("ECHOLILY_TOOL_RESULT", ""),
                tool_error=context.get("LINAR_TOOL_ERROR") or context.get("ECHOLILY_TOOL_ERROR", ""),
                user_input=context.get("LINAR_USER_INPUT") or context.get("ECHOLILY_USER_INPUT", ""),
                agent_text=context.get("LINAR_AGENT_TEXT") or context.get("ECHOLILY_AGENT_TEXT", ""),
                stage=context.get("LINAR_STAGE") or context.get("ECHOLILY_STAGE", ""),
                previous_stage=context.get("LINAR_PREVIOUS_STAGE") or context.get("ECHOLILY_PREVIOUS_STAGE", ""),
            )

            # Dispatch hooks
            await self.hooks.dispatch(hook_ctx)

            # Check if HookRegistry hooks blocked execution
            if hook_ctx.blocked:
                return f"[BLOCKED_BY_HOOK] {hook_ctx.block_reason}"

        # ── Legacy external process hooks (for backward compatibility) ───────
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
            env = {**context, "LINAR_SKILL_DIR": skill_dir, "LINAR_HOOK_EVENT": event,
                   "ECHOLILY_SKILL_DIR": skill_dir, "ECHOLILY_HOOK_EVENT": event}
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=30,
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
    async def add_user_message(self, text: str, blocks: list[dict] | None = None):
        """Append a user message, optionally with Content Blocks.

        When *blocks* is provided they are combined with *text* into a
        Content Block array stored in chat_history.  Otherwise *text* is
        stored as a plain string (backwards compatible).
        """
        if self.session_id is None:
            self.session_id = db.create_session()
            log.info("Created session #%s", self.session_id)

        # Build content: Content Block array or plain string
        if blocks and has_image_blocks(blocks):
            if self._is_multimodal:
                # Multimodal: store as Content Block array → _resolve_blocks will attach image
                content: str | list[dict] = [text_block(text)] if text else []
                content.extend(blocks)
            else:
                # Non-multimodal: flatten to text note so the API doesn't receive image_url
                from content_block import extract_image_urls as _eiu
                urls = _eiu(blocks)
                path_note = " ".join(urls)
                content = f"{text}\n(User attached image: {path_note})" if text else f"(User attached image: {path_note})"
        else:
            content = text

        log.info("[session=%s conversation_round=%s] User: %.120s",
                 self.session_id, self._conversation_round + 1, text)
        self._conversation_round += 1
        self.chat_history.append({
            "role": "user", "content": content, "round": self._conversation_round,
        })
        # Dispatch USER_MESSAGE hook (fire-and-forget for db persistence)
        await self.hooks.dispatch_fire_and_forget(
            HookContext(
                event=HookEvent.USER_MESSAGE,
                agent=self,
                timestamp=time.time(),
                user_input=text,
            )
        )
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
                raw_content = msg.get("content", "")
                # Try to restore Content Block arrays from JSON
                from content_block import blocks_from_json
                parsed = blocks_from_json(raw_content) if isinstance(raw_content, str) else None
                entry = {
                    "role": role,
                    "content": parsed if parsed else raw_content,
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

        # ── restore workspace ──
        ws = sess.get("workspace_path", "") or ""
        if ws and os.path.isdir(ws):
            self._workspace_root = ws
            os.chdir(ws)
            log.info("Restored workspace: %s", ws)
        else:
            self._workspace_root = None
            # Reset to project root when leaving a workspace
            os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
            "workspace_path": sess.get("workspace_path", "") or "",
        }
    def reset_session(self):
        """Start a fresh conversation session"""
        self.chat_history = []
        self._conversation_round = 0
        self.session_id = None
        log.info("Session reset")
    # ── interrupt ──────────────────────────────────────────
    def interrupt(self):
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
        print(json.dumps(event, ensure_ascii=False), flush=True)

    async def process_with_llm(self):
        # Fresh Event bound to this event loop (Python 3.10's
        # _LoopBoundMixin raises "bound to a different event loop"
        # when the same Event is awaited across asyncio.run() calls).
        self.stop_event = asyncio.Event()
        self._interrupted = False
        if not self._skill_active and not getattr(self, '_custom_system_prompt', False):
            self.llm.system_prompt = self._build_prompt(self.cfg)
        llm_call = 0
        while True:
            if self.stop_event.is_set():
                self._interrupted = True
                self.chat_history.append({
                    'role': 'meta',
                    'content': '[SYSTEM] User interrupted. Report what was done so far.',
                    'round': self._conversation_round,
                })
                break
            llm_call += 1
            if self.max_llm_calls > 0 and llm_call > self.max_llm_calls:
                notice = (
                    f"[SYSTEM] LLM call limit reached ({self.max_llm_calls}). "
                    "Stopping this turn before another model call. Increase "
                    "`max_turns` in agent/config.yaml if the task needs more "
                    "tool/LLM rounds."
                )
                self.chat_history.append({
                    "role": "meta",
                    "content": notice,
                    "round": self._conversation_round,
                })
                log.warning(
                    "[session=%s round=%s] %s",
                    self.session_id,
                    self._conversation_round,
                    notice,
                )
                self.emit({"type": "token", "data": notice})
                break
            llm_messages = self._build_llm_messages()

            # Dispatch LLM_START hook
            await self.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.LLM_START,
                    agent=self,
                    timestamp=time.time(),
                    metadata={"call_number": llm_call},
                )
            )

            self.emit({"type": "start"})
            stream = self.llm.stream_response_messages(llm_messages)
            text_parts = []
            reasoning_parts = []
            tool_call_deltas = {}
            async for chunk in stream:
                if self.stop_event.is_set():
                    break
                if hasattr(chunk, "usage") and chunk.usage:
                    u = chunk.usage
                    extra = getattr(u, "model_extra", None) or {}
                    self._last_prompt_tokens = u.prompt_tokens or 0
                    usage_data = {
                        "prompt_tokens": u.prompt_tokens or 0,
                        "completion_tokens": u.completion_tokens or 0,
                        "total_tokens": u.total_tokens or 0,
                        "prompt_cache_hit_tokens": extra.get("prompt_cache_hit_tokens", 0),
                        "prompt_cache_miss_tokens": extra.get("prompt_cache_miss_tokens", 0),
                    }
                    self.emit({"type": "usage", "data": usage_data})
                    # Dispatch LLM_USAGE hook (fire-and-forget for metrics tracking)
                    await self.hooks.dispatch_fire_and_forget(
                        HookContext(
                            event=HookEvent.LLM_USAGE,
                            agent=self,
                            timestamp=time.time(),
                            usage_data=usage_data,
                        )
                    )
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_parts.append(delta.content)
                    self.emit({"type": "token", "data": delta.content})
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_parts.append(delta.reasoning_content)
                    self.emit({"type": "reasoning_token", "data": delta.reasoning_content})
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_deltas:
                            tool_call_deltas[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_call_deltas[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_call_deltas[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_call_deltas[idx]["arguments"] += tc.function.arguments
            if self.stop_event.is_set():
                self._interrupted = True
                self.chat_history.append({
                    "role": "meta",
                    "content": "[SYSTEM] User interrupted. Report what was done so far.",
                    "round": self._conversation_round,
                })
                break

            # Dispatch LLM_DONE hook
            await self.hooks.dispatch_fire_and_forget(
                HookContext(
                    event=HookEvent.LLM_DONE,
                    agent=self,
                    timestamp=time.time(),
                    agent_text="".join(text_parts),
                    metadata={"call_number": llm_call},
                )
            )

            self.emit({"type": "done"})
            text = "".join(text_parts)
            reasoning = "".join(reasoning_parts)
            tool_calls = []
            for idx in sorted(tool_call_deltas.keys()):
                tc = tool_call_deltas[idx]
                if tc["name"]:
                    tool_calls.append(tc)
                    self.emit({"type": "tool_call", "name": tc["name"], "id": tc["id"], "arguments": tc["arguments"]})
            if text or reasoning or tool_calls:
                entry = {
                    "role": "agent", "content": text, "round": self._conversation_round,
                }
                if reasoning:
                    entry["reasoning"] = reasoning
                if tool_calls:
                    entry["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in tool_calls
                    ]
                self.chat_history.append(entry)
                # Dispatch AGENT_RESPONSE hook (fire-and-forget for db persistence)
                await self.hooks.dispatch_fire_and_forget(
                    HookContext(
                        event=HookEvent.AGENT_RESPONSE,
                        agent=self,
                        timestamp=time.time(),
                        agent_text=text,
                        metadata={
                            "reasoning": reasoning,
                            "tool_calls": tool_calls,
                            "prompt_tokens": self._last_prompt_tokens or 0,
                        }
                    )
                )
            if not tool_calls:
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
            self._interrupted = False
            for tc in tool_calls:
                # Tool logging handled by log_tool_call hook (hooks_builtin.py)
                if self.stop_event.is_set():
                    self._interrupted = True
                    self.chat_history.append({
                        'role': 'meta',
                        'content': '[SYSTEM] User interrupted. Stop and report.',
                        'round': self._conversation_round,
                    })
                    break
                result_str = await self._check_permission(tc["name"], tc["arguments"])
                _tool_failed = False
                if result_str is None:
                    raw_args = tc["arguments"]
                    try:
                        args_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        result_str = (
                            f"Error: Failed to parse arguments for tool "
                            f"'{tc['name']}': invalid JSON. "
                            f"Do NOT retry with the same arguments."
                        )
                        _tool_failed = True
                    if result_str is None:
                        hook_result = await self._run_hook("PreToolUse", {
                        "LINAR_TOOL_NAME": tc["name"],
                        "ECHOLILY_TOOL_NAME": tc["name"],
                        "LINAR_TOOL_ARGUMENTS": tc["arguments"],
                        "ECHOLILY_TOOL_ARGUMENTS": tc["arguments"],
                    })
                    if hook_result:
                        try:
                            hook_data = json.loads(hook_result)
                            if hook_data.get("block"):
                                result_str = f"[BLOCKED_BY_HOOK] {hook_data.get('reason', 'blocked')}"
                        except json.JSONDecodeError:
                            pass
                    if result_str is None:
                        tool_obj = self.tools.get(tc["name"])
                        if tool_obj is None:
                            _m = re.match(r"^(.+)_script$", tc["name"])
                            if _m:
                                _skill = get_skill(_m.group(1))
                                if _skill:
                                    log.info("Auto-loading skill '%s' for tool '%s'", _m.group(1), tc["name"])
                                    _skill.on_load(self)
                                    tool_obj = self.tools.get(tc["name"])
                        try:
                            if tool_obj is None:
                                raise KeyError(tc["name"])
                            # Ensure stop_event is clear before each tool
                            # execution.  The event is recreated at the top
                            # of process_with_llm so this is defensive.
                            self.stop_event.clear()
                            # Some tools (e.g. MCPTool) expose an async
                            # execute() — handle both sync and async.
                            if asyncio.iscoroutinefunction(tool_obj.execute):
                                execute_task = asyncio.create_task(
                                    tool_obj.execute(**args_dict)
                                )
                            else:
                                execute_task = asyncio.create_task(
                                    asyncio.to_thread(tool_obj.execute, **args_dict)
                                )
                            interrupt_task = asyncio.create_task(self.stop_event.wait())
                            done, pending = await asyncio.wait(
                                [execute_task, interrupt_task],
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            for task in pending:
                                task.cancel()
                            if interrupt_task in done:
                                raise InterruptedError("User interrupted")
                            result = execute_task.result()
                            if isinstance(result, str) and result.strip().startswith('{'):
                                try:
                                    result = json.loads(result)
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    pass
                            if isinstance(result, dict):
                                if result.get("error"):
                                    _tool_failed = True
                                elif result.get("exit_code", 0) != 0:
                                    _tool_failed = True
                                # Extract image_uri for observation_store
                                if result.get("image_uri"):
                                    self.observation_store.add_image(result["image_uri"])
                                # Tool result text: use `message` field, fall back to str(dict)
                                result_str = result.get("message", str(result))
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
                        except asyncio.CancelledError:
                            result_str = "[SYSTEM] Tool execution cancelled."
                            _tool_failed = True
                        except Exception as e:
                            result_str = f"Error: {e}"
                            _tool_failed = True
                is_failure = _tool_failed or (
                    isinstance(result_str, str) and result_str and (result_str.startswith("Error") or result_str.startswith("["))
                )
                if is_failure:
                    self._tool_failures[tc["name"]] = self._tool_failures.get(tc["name"], 0) + 1
                    if self._tool_failures[tc["name"]] >= 3:
                        self.chat_history.append({
                            "role": "meta",
                            "content": (
                                f"[SYSTEM] Tool '{tc['name']}' has failed "
                                f"{self._tool_failures[tc['name']]} times in a row. "
                                f"Do NOT retry. Switch strategy or use ask_user."
                            ),
                            "round": self._conversation_round,
                        })
                        self._tool_failures[tc["name"]] = 0
                else:
                    self._tool_failures[tc["name"]] = 0
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
                                        f"[SYSTEM] Same command {len(self._cmd_history)} times:\n  {cmd}\n"
                                        f"Use a different approach."
                                    ),
                                    "round": self._conversation_round,
                                })
                                self._cmd_history.clear()
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                if self.stop_event.is_set():
                    self._interrupted = True
                    self.chat_history.append({
                        'role': 'meta',
                        'content': '[SYSTEM] User interrupted. Stop and report.',
                        'round': self._conversation_round,
                    })
                    break
                self.chat_history.append({
                    "role": "tool", "tool_call_id": tc.get("id", ""),
                    "name": tc["name"], "arguments": tc["arguments"],
                    "result": result_str, "round": self._conversation_round,
                })
                self.emit({"type": "tool_result", "name": tc["name"], "id": tc["id"], "result": result_str})
                await self._run_hook("PostToolUse", {
                    "LINAR_TOOL_NAME": tc["name"], "ECHOLILY_TOOL_NAME": tc["name"],
                    "LINAR_TOOL_ARGUMENTS": tc["arguments"], "ECHOLILY_TOOL_ARGUMENTS": tc["arguments"],
                    "LINAR_TOOL_RESULT": result_str, "ECHOLILY_TOOL_RESULT": result_str,
                    "LINAR_TOOL_ERROR": result_str if is_failure else "",
                    "ECHOLILY_TOOL_ERROR": result_str if is_failure else "",
                })
                # Tool persistence handled by persist_tool_result hook (hooks_builtin.py)
            self._compact_history()
            if self._interrupted:
                break
        log.info("[session=%s round=%s] LLM done", self.session_id, self._conversation_round)
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
