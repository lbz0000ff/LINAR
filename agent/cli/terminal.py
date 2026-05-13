"""
Lily Agent Terminal — REPL-style streaming CLI with markdown rendering,
reasoning display, and live thinking stats.

Usage:
    cd agent && python -m cli.terminal
    cd agent && python cli/terminal.py
"""

import os
import re
import sys
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.style import Style
from rich.text import cell_len

# ── ensure agent/ directory is on sys.path ───────────────
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import agent
import database as db
Agent = agent.Agent

# ── style system ──────────────────────────────────────────
from cli.style_loader import load_style

REASONING_MODES = ("hide", "full")
TOOL_CALL_MODES = ("hide", "show_tools", "detailed")

# ── tab completer ──────────────────────────────────────────

class _CommandCompleter(Completer):
    """Tab completer for slash commands — only activates when typing `/`."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # ── base commands ──────────────────────────────────
        commands = [
            "/exit", "/quit", "/help", "/reset", "/clear",
            "/reasoning", "/tool_calls", "/sessions", "/session","/history"
        ]
        for cmd in commands:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))

        # ── sub-arguments after a space ────────────────────
        if " " in text:
            cmd, _, partial = text.partition(" ")
            if cmd == "/reasoning":
                for mode in ("hide", "full"):
                    if mode.startswith(partial):
                        yield Completion(mode, start_position=-len(partial))
            elif cmd == "/tool_calls":
                for mode in ("hide", "show_tools", "detailed"):
                    if mode.startswith(partial):
                        yield Completion(mode, start_position=-len(partial))


# ── helpers ──────────────────────────────────────────────

def _format_time(seconds: float) -> str:
    """0.3 → "0.3s"   90 → "1m30s"   4000 → "1h6m"."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes}m" if minutes else f"{hours}h"


def _format_tokens(n: int) -> str:
    """999 → "999"   1234 → "1.2K"   1_200_000 → "1.2M"."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.2f}M"
    return f"{n / 1_000_000_000:.2f}G"


def _progress_bar(used: int, total: int, width: int = 12) -> str:
    """Return a text progress bar like `[#######   ]`."""
    pct = min(used / total, 1.0)
    filled = int(pct * width)
    empty = width - filled
    return "[" + "#" * filled + " " * empty + f"] {pct * 100:.0f}%"


# ── terminal ──────────────────────────────────────────────

class LilyTerminal:
    """REPL-style streaming terminal for the Lily Agent."""

    # Logo template: each line is [(text, style_key_or_None), ...]
    # style_key maps to banner.<key> in style.yaml; None = no markup.
    _logo = [
        [(" ", None),(" ", None),("██╗", "lily"), ("      ", None), ("████", "i"), ("╗", "shadow"), (" ", None),("██╗", "lily"), ("     ", None), ("██╗   ██╗", "lily")                                 ,(" ", None),(" ", None)],
        [(" ", None),(" ", None),("██║", "lily"), ("      ", None), ("╚", "shadow"), ("██", "i"), ("╔╝", "shadow"), (" ", None),("██║", "lily"), ("     ", None), ("╚", "shadow"), ("██╗ ██╔╝", "lily") ,(" ", None),(" ", None)],
        [(" ", None),(" ", None),("██║", "lily"), ("       ", None), ("██", "i"),("║", "shadow"), ("  ", None),("██║", "lily"), ("      ", None), ("╚████╔╝", "lily"), (" ", None)                      ,(" ", None),(" ", None)],
        [(" ", None),(" ", None),("██║", "lily"), ("       ", None), ("██", "i"), ("╚╗", "shadow"), (" ", None),("██║", "lily"), ("       ", None), ("╚██╔╝", "lily"), ("  ", None)                     ,(" ", None),(" ", None)],
        [(" ", None),(" ", None),("███████╗", "lily"), (" ", None), ("████", "i"), ("║", "shadow"), (" ", None),("███████╗", "lily"), ("   ", None), ("██║", "lily"), ("   ", None)                     ,(" ", None),(" ", None)],
        [(" ", None),(" ", None),("╚══════╝", "lily"), (" ", None), ("╚", "shadow"), ("═══", "shadow"), ("╝", "shadow"), (" ", None),("╚══════╝", "lily"), ("   ", None), ("╚═╝", "lily"), ("   ", None),(" ", None),(" ", None)],
    ]

    # Text lines below the logo: (template_text, banner_style_key)
    _banner_text = [
        ("Lily Agent Terminal  version {version}", "title"),
        ("Type /help for command help", "hint"),
    ]

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.agent.emit = self._on_event

        self.console = Console(highlight=False)
        self.session: PromptSession | None = None

        # ── load style config ──
        self.style = load_style()
        cfg = self._load_config()

        # ── reasoning mode ──
        default_mode = cfg.get("show_reasoning", "hide")
        self.reasoning_mode = default_mode if default_mode in REASONING_MODES else "hide"

        # ── tool call display mode ──
        default_tc = cfg.get("show_tool_calls", "show_tools")
        self.tool_calls_mode = default_tc if default_tc in TOOL_CALL_MODES else "show_tools"

        # ── max tokens for stats bar ──
        self._max_tokens = cfg.get("llm", {}).get("max_tokens", 1_000_000)
        self._version = cfg.get("version", "0.1.0")

        # ── per-response state (reset on each "start") ──
        self._response_text = ""
        self._reasoning_text = ""
        self._all_printed_text = ""
        self._had_tool_calls = False
        self._start_time = 0.0
        self._usage: dict | None = None
        self._header_printed = False
        self._in_reasoning = False
        self._bold_active = False
        self._pending = ""

    # ── config loader (module-level import replacement) ───

    @staticmethod
    def _load_config():
        from config import load_config as _lc
        return _lc()

    # ── style shortcut ────────────────────────────────────

    def s(self, key: str) -> str:
        """Shorthand — return color string for a console style key."""
        return self.style["console"].get(key, "")

    # ── welcome banner ─────────────────────────────────────

    @staticmethod
    def _dw(s: str) -> int:
        """Display width of a string (CJK-aware)."""
        return cell_len(s)

    def _build_welcome_message(self) -> str:
        """Build the welcome banner from structured components.

        Renders the LILY logo, adds text lines, and wraps everything
        in a border box.  Widths are computed with ``cell_len`` so
        CJK characters align correctly regardless of Rich markup.
        """
        banner = self.style["banner"]

        # ── raw text (no markup) for width computation ──────
        raw_logo = [
            "".join(text for text, _ in segs) for segs in self._logo
        ]
        raw_texts = list(raw_logo) + [
            t.format(version=self._version) for t, _ in self._banner_text
        ]
        content_w = max(self._dw(line) for line in raw_texts)

        # ── border wrappers ─────────────────────────────────
        bc = banner.get("border", "grey")
        top    = f"[{bc}]┏{'━' * content_w}┓[/{bc}]"
        bot    = f"[{bc}]┗{'━' * content_w}┛[/{bc}]"
        side   = f"[{bc}]┃[/{bc}]"
        blank  = f"{side}{' ' * content_w}{side}"

        lines = [top, blank]

        # ── logo lines ──────────────────────────────────────
        for i, segs in enumerate(self._logo):
            parts = []
            for text, sk in segs:
                color = banner.get(sk, "") if sk and text else ""
                if color:
                    parts.append(f"[{color}]{text}[/{color}]")
                else:
                    parts.append(text)
            colored = "".join(parts)
            pad = content_w - self._dw(raw_logo[i])
            lines.append(f"{side}{colored}{' ' * pad}{side}")

        lines.append(blank)

        # ── text lines (centered) ───────────────────────────
        for text, sk in self._banner_text:
            formatted = text.format(version=self._version)
            color = banner.get(sk, "")
            colored = f"[{color}]{formatted}[/{color}]" if color else formatted
            d_w = self._dw(formatted)
            left = (content_w - d_w) // 2
            right = content_w - d_w - left
            lines.append(f"{side}{' ' * left}{colored}{' ' * right}{side}")

        lines.append(blank)
        lines.append(bot)
        return "\n".join(lines)

    # ── helpers ───────────────────────────────────────────

    def _print_header(self) -> None:
        """Print the header on first visible event of a response."""
        if not self._header_printed:
            self._header_printed = True
            self.console.print()
            h = self.s("header")
            self.console.print(f"[grey]>>[/grey] [{h}]Lily[/{h}]")

    def _process_output(self, text: str) -> None:
        """Print text, rendering **bold** markers as actual bold.

        Accumulates a pending buffer across stream chunks so that **
        markers split across chunks are handled correctly. Text inside
        **...** is printed with Rich's bold style.
        """
        if not text:
            return

        self._pending += text

        # Process all complete **...** segments in the buffer
        while True:
            idx = self._pending.find("**")
            if idx == -1:
                break

            prefix = self._pending[:idx]
            if prefix:
                self.console.print(prefix, end="")

            self._bold_active = not self._bold_active
            self._pending = self._pending[idx + 2:]

        # Handle lone trailing * (could be start of ** in next chunk)
        if self._pending.endswith("*") and not self._pending.endswith("**"):
            trailing = self._pending[:-1]
            saved = "*"
        else:
            trailing = self._pending
            saved = ""

        if trailing:
            if self._bold_active:
                self.console.print(trailing, end="", style="bold")
            else:
                self.console.print(trailing, end="")

        self._pending = saved

    # ── event handler ─────────────────────────────────────

    def _on_event(self, event: dict) -> None:
        etype = event.get("type")

        # ── start ────────────────────────────────────────
        if etype == "start":
            self._response_text = ""
            self._reasoning_text = ""
            self._all_printed_text = ""
            self._had_tool_calls = False
            self._start_time = time.time()
            self._usage = None
            self._header_printed = False
            self._in_reasoning = False
            self._bold_active = False
            self._pending = ""

        # ── token ────────────────────────────────────────
        elif etype == "token":
            data = event["data"]
            # strip [turn N] markers (internal context, not for display)
            data = re.sub(r"\[turn \d+\]\s*", "", data)
            if not data:
                return
            self._response_text += data
            self._all_printed_text += data

            # newline between reasoning block and content
            if self._in_reasoning:
                self.console.print()
                self._in_reasoning = False

            self._print_header()
            self._process_output(data)
            sys.stdout.flush()

        # ── reasoning_token ──────────────────────────────
        elif etype == "reasoning_token":
            data = event["data"]
            self._reasoning_text += data

            if self.reasoning_mode == "full":
                self._all_printed_text += data
                self._print_header()
                self._in_reasoning = True
                r = self.s("reasoning")
                if r:
                    # named style (e.g. "dim italic")
                    self.console.print(data, end="", style=Style.parse(r))
                else:
                    self.console.print(data, end="", style=Style(dim=True, italic=True))
                sys.stdout.flush()

        # ── done (end of one LLM turn) ───────────────────
        elif etype == "done":
            self.console.print()

        # ── complete (end of all turns) ──────────────────
        elif etype == "complete":
            self._print_stats()

        # ── usage ────────────────────────────────────────
        elif etype == "usage":
            self._usage = event.get("data")

        # ── tool_call — show tool name in light gray ─────
        elif etype == "tool_call":
            self._had_tool_calls = True

            if self.tool_calls_mode == "hide":
                return

            self._print_header()
            name = event["name"]
            tn = self.s("tool_name")

            if self.tool_calls_mode == "show_tools":
                self.console.print(f"\n  [{tn}]⚙ Using: {name}[/{tn}]")

            elif self.tool_calls_mode == "detailed":
                preview = event.get("arguments", "")[:120]
                self.console.print(f"\n  [{tn}]⚙ Using: {name}[/{tn}]")
                td = self.s("tool_detail")
                self.console.print(f"  [{td}]  {preview}[/{td}]")

        # ── tool_result — show result in dark gray ────────
        elif etype == "tool_result":
            self._had_tool_calls = True

            if self.tool_calls_mode == "detailed":
                r = str(event.get("result", ""))[:200]
                td = self.s("tool_detail")
                self.console.print(f"  [{td}]  → {r}[/{td}]")
            sys.stdout.flush()

        elif etype == "error":
            e = self.s("error")
            self.console.print(
                f"\n[{e}]✖ Error: {event.get('data', 'unknown error')}[/{e}]"
            )

    # ── stats display ─────────────────────────────────────

    def _print_stats(self) -> None:
        """Print elapsed time and token usage line with dynamic color."""
        elapsed = time.time() - self._start_time
        elapsed_str = _format_time(elapsed)

        used = (self._usage or {}).get("total_tokens", 0)
        used_str = _format_tokens(used)
        max_str = _format_tokens(self._max_tokens)
        pct = min(used / self._max_tokens * 100, 100)

        # dynamic color by usage percentage
        if pct > 70:
            color = self.s("stats_bad")
        elif pct > 50:
            color = self.s("stats_warn")
        else:
            color = self.s("stats_good")

        bar = _progress_bar(used, self._max_tokens)
        dim = self.s("stats_dim")

        line = (
            f"  [{dim}]⏱ {elapsed_str}  │  [/{dim}]"
            f"[{color}]Tokens: {used_str} / {max_str}  {bar}[/{color}]"
        )
        self.console.print(line)

    # —— chat history display ——————————————
    
    def _print_history(self) -> None:
        """Print the conversation history with reasoning and tool calls."""
        history = self.agent.chat_history
        if history == []:
            return
        self.console.print("\n———————————— Conversation History ————————————")
        for chat in history:
            role = chat["role"]
            if role == "user":
                content = chat["content"]
                header = "[" + self.s("header_user") + "]" + "User[/" + self.s("header_user") + "]"
                self.console.print("\n" + header + "> " + "[grey62]" + content + "[/grey62]")
            elif role == "agent":
                content = chat["content"]
                header = "[" + self.s("header") + "]" + "Lily[/" + self.s("header") + "]"
                self.console.print("\n" + header + "> " + "[grey62]" + content + "[/grey62]")
            elif role == "tool":
                tool_name = chat.get("name")
                s = self.s("tool_name")
                self.console.print(f"\n    [{s}]Agent called tool {tool_name}[/{s}]...")
        self.console.print("\n———————————— Conversation History ————————————")
        

    # ── commands ──────────────────────────────────────────

    def _reasoning_color(self, mode: str | None = None) -> str:
        """Return the mode name wrapped in the appropriate Rich color tag."""
        m = mode or "hide"
        colors = self.style["mode_colors"]["reasoning"]
        color = colors.get(m, "white")
        return f"[{color}]{m}[/{color}]"

    def _tool_calls_color(self, mode: str | None = None) -> str:
        """Return the tool-call mode name in its colour tag."""
        m = mode or "show_tools"
        colors = self.style["mode_colors"]["tool_calls"]
        color = colors.get(m, "white")
        return f"[{color}]{m}[/{color}]"

    def _handle_command(self, text: str) -> bool:
        cmd = text.strip()

        if cmd in ("/exit", "/quit"):
            return True

        if cmd == "/help":
            self.console.print("\nCommands:")
            self.console.print("  /history               Show conversation history")
            self.console.print("  /exit or /quit         Exit the terminal")
            self.console.print("  /help                  Show this message")
            self.console.print(
                "  /reasoning <mode>      "
                f"Set reasoning display: full | hide. Currently: {self._reasoning_color(self.reasoning_mode)}"
            )
            self.console.print(
                "  /tool_calls <mode>     "
                f"Set tool call display: hide | show_tools | detailed. Currently: {self._tool_calls_color(self.tool_calls_mode)}"
            )
            self.console.print("  /reset or /clear        Start a new conversation session")
            self.console.print("  /sessions               List all sessions")
            self.console.print("  /session [id]           Show / switch session")
            self.console.print("  /session rename <id> <title>")
            self.console.print("  /session delete <id>    Delete a session")
            return True

        if cmd in ("/reset", "/clear"):
            self.agent.reset_session()
            ns = self.s("new_session")
            self.console.print(f"\n[{ns}]── new session ──[/{ns}]")
            return True

        if cmd in ("/history",):
            self._print_history()
            return True

        if cmd.startswith("/reasoning"):
            parts = cmd.split(maxsplit=1)
            if len(parts) == 1:
                # toggle
                current_idx = REASONING_MODES.index(self.reasoning_mode)
                next_idx = (current_idx + 1) % len(REASONING_MODES)
                self.reasoning_mode = REASONING_MODES[next_idx]
            else:
                arg = parts[1].lower()
                if arg in REASONING_MODES:
                    self.reasoning_mode = arg
                else:
                    self.console.print(
                        f"  Invalid mode '{arg}'. "
                        f"Use: {' | '.join(REASONING_MODES)}"
                    )
                    return True

            self.console.print(
                f"  Reasoning mode set to: {self._reasoning_color(self.reasoning_mode)}\n"
            )
            return True

        if cmd.startswith("/tool_calls"):
            parts = cmd.split(maxsplit=1)
            if len(parts) == 1:
                # toggle
                current_idx = TOOL_CALL_MODES.index(self.tool_calls_mode)
                next_idx = (current_idx + 1) % len(TOOL_CALL_MODES)
                self.tool_calls_mode = TOOL_CALL_MODES[next_idx]
            else:
                arg = parts[1].lower()
                if arg in TOOL_CALL_MODES:
                    self.tool_calls_mode = arg
                else:
                    self.console.print(
                        f"  Invalid mode '{arg}'. "
                        f"Use: {' | '.join(TOOL_CALL_MODES)}"
                    )
                    return True

            self.console.print(
                f"  Tool call display set to: {self._tool_calls_color(self.tool_calls_mode)}\n"
            )
            return True

        if cmd == "/sessions":
            sessions = db.get_recent_sessions(50)
            if not sessions:
                self.console.print("\n  No sessions yet.")
                return True

            from rich.table import Table
            table = Table(show_header=True, header_style="bold", box=None)
            table.add_column("#", style="dim", width=3)
            table.add_column("Date", width=19)
            table.add_column("Title")
            for s in sessions:
                sid = s["id"]
                marker = f"  ← active" if sid == self.agent.session_id else ""
                table.add_row(
                    str(sid),
                    s.get("created_at", "")[:19],
                    f"{s.get('title', '')[:60]}{marker}",
                )
            count = db.get_session_count()
            self.console.print(f"\n  Sessions ({count} total):")
            self.console.print(table)

            # Interactive session selector
            from prompt_toolkit.shortcuts import prompt as pt_prompt
            from prompt_toolkit.completion import Completer, Completion

            class _SessionPicker(Completer):
                def __init__(self, sessions):
                    self.sessions = sessions
                def get_completions(self, document, complete_event):
                    text = document.text_before_cursor
                    for s in self.sessions:
                        title = (s.get('title') or '')[:40]
                        display = f"#{s['id']}  {s.get('created_at', '')[:19]}  {title}"
                        if not text or str(s['id']).startswith(text):
                            yield Completion(str(s['id']), start_position=-len(text), display=display)

            try:
                result = pt_prompt(
                    "  Select session # (or Enter to cancel): ",
                    completer=_SessionPicker(sessions),
                    complete_while_typing=True,
                )
                result = result.strip()
                if result and result.isdigit():
                    sid = int(result)
                    if self.agent.switch_session(sid):
                        ns = self.s("new_session")
                        self.console.print(f"\n  [{ns}]Switched to session #{sid}[/{ns}]")
                    else:
                        e = self.s("error")
                        self.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
            except (KeyboardInterrupt, EOFError):
                pass
            return True

        if cmd.startswith("/session"):
            parts = cmd.split(maxsplit=2)
            sub = parts[1] if len(parts) > 1 else ""

            # /session — show current session info
            if not sub:
                info = self.agent.get_current_session_info()
                self.console.print(
                    f"\n  Session #{info['session_id']}"
                    f"  |  Turn {info['turn']}"
                    f"  |  {info.get('title', 'untitled')[:60]}"
                )
                return True

            # /session <id> — switch to a session
            if sub.isdigit():
                sid = int(sub)
                if self.agent.switch_session(sid):
                    ns = self.s("new_session")
                    self.console.print(f"\n  [{ns}]Switched to session #{sid}[/{ns}]")
                else:
                    e = self.s("error")
                    self.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
                return True

            # /session rename <id> <title>
            if sub == "rename" and len(parts) == 3:
                rename_parts = parts[2].split(maxsplit=1)
                if len(rename_parts) == 2:
                    sid, title = int(rename_parts[0]), rename_parts[1]
                    sess = db.get_session_by_id(sid)
                    if sess:
                        db.update_session_title(sid, title)
                        self.console.print(f"\n  Session #{sid} renamed to \"{title}\"")
                    else:
                        e = self.s("error")
                        self.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
                else:
                    self.console.print("\n  Usage: /session rename <id> <title>")
                return True

            # /session delete <id>
            if sub == "delete" and len(parts) >= 2:
                try:
                    sid = int(parts[2]) if len(parts) > 2 else 0
                except ValueError:
                    self.console.print("\n  Usage: /session delete <id>")
                    return True
                if sid <= 0:
                    self.console.print("\n  Usage: /session delete <id>")
                    return True
                count = db.get_session_count()
                if count <= 1:
                    self.console.print("\n  Cannot delete the only session.")
                    return True
                sess = db.get_session_by_id(sid)
                if not sess:
                    e = self.s("error")
                    self.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
                    return True
                db.delete_session(sid)
                if sid == self.agent.session_id:
                    self.agent.reset_session()
                    ns = self.s("new_session")
                    self.console.print(
                        f"\n  Session #{sid} deleted. "
                        f"[{ns}]Started new session #{self.agent.session_id}[/{ns}]"
                    )
                else:
                    self.console.print(f"\n  Session #{sid} deleted.")
                return True

            self.console.print(
                "\n  Usage:"
                "\n    /session              Show current session info"
                "\n    /session <id>         Switch to a session"
                "\n    /session rename <id> <title>"
                "\n    /session delete <id>  Delete a session"
            )
            return True

        return False

    # ── main loop ─────────────────────────────────────────

    def run(self) -> None:
        self.console.print(self._build_welcome_message())
        if self.session is None:
            self.session = PromptSession(completer=_CommandCompleter())

        while True:
            try:
                text = self.session.prompt("\n╭─ ")
            except (KeyboardInterrupt, EOFError):
                break

            text = text.strip()
            if not text:
                continue

            if self._handle_command(text):
                if text.strip().lower() in ("/exit", "/quit"):
                    break
                continue

            # feed to agent
            self.agent.add_user_message(text)

            try:
                self.agent.process_with_llm()
            except Exception as exc:
                e = self.s("error")
                self.console.print(f"\n[{e}]✖ Error: {exc}[/{e}]")

        g = self.s("goodbye")
        self.console.print(f"\n[{g}]Goodbye![/{g}]")


# ── entry point ───────────────────────────────────────────

def main() -> None:
    from tool_registry import get_tools

    # Load config and filter tools by enabled_sets
    from config import load_config
    _cfg = load_config()
    _enabled = _cfg.get("tools", {}).get("enabled_sets", None)
    tools = get_tools(_enabled)

    # Inject interactive password input via prompt_toolkit
    from prompt_toolkit import PromptSession as PromptSession_
    _pw_session = PromptSession_()

    def _tui_input(prompt: str, password: bool = False, choices: list | None = None) -> str:
        try:
            if choices:
                display = prompt + "\n"
                for i, c in enumerate(choices, 1):
                    display += f"  [{i}] {c}\n"
                display += "Enter number or type your answer: "
                result = _pw_session.prompt(display)
                if result.isdigit():
                    idx = int(result) - 1
                    if 0 <= idx < len(choices):
                        return choices[idx]
                return result
            return _pw_session.prompt(prompt, is_password=password)
        except (KeyboardInterrupt, EOFError):
            return ""

    for t in tools.values():
        t.interactive_input = _tui_input

    agent = Agent(tools=tools)
    cli = LilyTerminal(agent)
    cli.run()


if __name__ == "__main__":
    main()
