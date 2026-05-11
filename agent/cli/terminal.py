"""
Lily Agent Terminal — REPL-style streaming CLI with markdown rendering,
reasoning display, and live thinking stats.

Usage:
    cd agent && python -m cli.terminal
    cd agent && python cli/terminal.py
"""

import os
import sys
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.style import Style

# ── ensure agent/ directory is on sys.path ───────────────
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import agent
Agent = agent.Agent

# ── constants ─────────────────────────────────────────────

from config import load_config
_CFG = load_config()
MAX_TOKENS = _CFG.get("terminal_max_tokens", 1_000_000)

# ── WELCOME banner colours ── tweak these to adjust depth/shade ──
_C_BORDER = "grey"
_C_LILY  = "grey85"
_C_I     = "red"
_C_SHADOW = "grey"
_C_TITLE = "yellow"
_C_HINT  = "grey62"

WELCOME = f"""\
  [{_C_BORDER}]┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]                                                    [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_LILY}]██╗[/{_C_LILY}]      [{_C_I}]████[/{_C_I}][{_C_SHADOW}]╗[/{_C_SHADOW}] [{_C_LILY}]██╗     ██╗   ██╗[/{_C_LILY}]          [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_LILY}]██║[/{_C_LILY}]      [{_C_SHADOW}]╚[/{_C_SHADOW}][{_C_I}]██[/{_C_I}]╔╝ [{_C_LILY}]██║     ╚██╗ ██╔╝[/{_C_LILY}]          [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_LILY}]██║[/{_C_LILY}]       [{_C_I}]██[/{_C_I}][{_C_SHADOW}]║[/{_C_SHADOW}]  [{_C_LILY}]██║      ╚████╔╝[/{_C_LILY}]           [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_LILY}]██║[/{_C_LILY}]       [{_C_I}]██[/{_C_I}][{_C_SHADOW}]╚╗[/{_C_SHADOW}] [{_C_LILY}]██║       ╚██╔╝[/{_C_LILY}]            [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_LILY}]███████╗[/{_C_LILY}] [{_C_I}]████[/{_C_I}][{_C_SHADOW}]║[/{_C_SHADOW}] [{_C_LILY}]███████╗   ██║[/{_C_LILY}]             [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]          [{_C_SHADOW}]╚══════╝ ╚═══╝ ╚══════╝   ╚═╝[/{_C_SHADOW}]             [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]                                                    [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]           [{_C_TITLE}]Lily Agent Terminal  v0.1.0[/{_C_TITLE}]              [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]                                                    [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]            [{_C_HINT}]Type /help for command help[/{_C_HINT}]             [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┃[/{_C_BORDER}]                                                    [{_C_BORDER}]┃[/{_C_BORDER}]
  [{_C_BORDER}]┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛[/{_C_BORDER}]"""

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
            "/exit", "/quit", "/help",
            "/reasoning", "/tool_calls",
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

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.agent.emit = self._on_event

        self.console = Console(highlight=False)
        self.session: PromptSession | None = None

        # ── reasoning mode ──
        default_mode = _CFG.get("show_reasoning", "hide")
        self.reasoning_mode = default_mode if default_mode in REASONING_MODES else "hide"

        # ── tool call display mode ──
        default_tc = _CFG.get("show_tool_calls", "show_tools")
        self.tool_calls_mode = default_tc if default_tc in TOOL_CALL_MODES else "show_tools"

        # ── per-response state (reset on each "start") ──
        self._response_text = ""         # accumulated content tokens
        self._reasoning_text = ""        # accumulated reasoning tokens
        self._all_printed_text = ""      # all text printed since last "start"
        self._had_tool_calls = False     # whether tool calls occurred this cycle
        self._start_time = 0.0
        self._usage: dict | None = None
        self._header_printed = False       # whether "⚡ Lily" has been shown
        self._in_reasoning = False         # whether currently printing reasoning
        self._bold_active = False          # whether inside a **bold** segment
        self._pending = ""                 # pending text for ** marker parsing

    # ── helpers ───────────────────────────────────────────

    def _print_header(self) -> None:
        """Print the "⚡ Lily" header on first visible event of a response."""
        if not self._header_printed:
            self._header_printed = True
            self.console.print()
            self.console.print("[bold cyan]⚡ Lily[/bold cyan]")

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
                self.console.print(
                    data,
                    end="",
                    style=Style(dim=True, italic=True),
                )
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

            if self.tool_calls_mode == "show_tools":
                self.console.print(f"\n  [grey85]⚙ Using: {name}[/grey85]")

            elif self.tool_calls_mode == "detailed":
                preview = event.get("arguments", "")[:120]
                self.console.print(f"\n  [grey85]⚙ Using: {name}[/grey85]")
                self.console.print(f"  [grey62]  {preview}[/grey62]")

        # ── tool_result — show result in dark gray ────────
        elif etype == "tool_result":
            self._had_tool_calls = True

            if self.tool_calls_mode == "detailed":
                r = str(event.get("result", ""))[:200]
                self.console.print(f"  [grey62]  → {r}[/grey62]")
            sys.stdout.flush()

        elif etype == "error":
            self.console.print(
                f"\n[red]✖ Error: {event.get('data', 'unknown error')}[/red]"
            )

    # ── stats display ─────────────────────────────────────

    def _print_stats(self) -> None:
        """Print elapsed time and token usage line with dynamic color."""
        elapsed = time.time() - self._start_time
        elapsed_str = _format_time(elapsed)

        used = (self._usage or {}).get("total_tokens", 0)
        used_str = _format_tokens(used)
        max_str = _format_tokens(MAX_TOKENS)
        pct = min(used / MAX_TOKENS * 100, 100)

        # dynamic color by usage percentage
        if pct > 70:
            color = "red"
        elif pct > 50:
            color = "bold yellow"
        else:
            color = "bold green"

        bar = _progress_bar(used, MAX_TOKENS)

        line = (
            f"  [dim]⏱ {elapsed_str}  │  [/dim]"
            f"[{color}]Tokens: {used_str} / {max_str}  {bar}[/{color}]"
        )
        self.console.print(line)

    # ── commands ──────────────────────────────────────────

    @staticmethod
    def _reasoning_color(mode: str | None = None) -> str:
        """Return the mode name wrapped in the appropriate Rich color tag."""
        m = mode or "hide"
        color_map = {"hide": "red", "full": "yellow"}
        color = color_map.get(m, "white")
        return f"[{color}]{m}[/{color}]"

    @staticmethod
    def _tool_calls_color(mode: str | None = None) -> str:
        """Return the tool-call mode name in its colour tag."""
        m = mode or "show_tools"
        color_map = {"hide": "red", "show_tools": "cyan", "detailed": "yellow"}
        color = color_map.get(m, "white")
        return f"[{color}]{m}[/{color}]"

    def _handle_command(self, text: str) -> bool:
        cmd = text.strip()

        if cmd in ("/exit", "/quit"):
            return True

        if cmd == "/help":
            self.console.print("\nCommands:")
            self.console.print("  /exit or /quit         Exit the terminal")
            self.console.print("  /help                  Show this message")
            self.console.print(
                "  /reasoning <mode>      "
                "Set reasoning display: full | hide"
            )
            self.console.print(
                "  /tool_calls <mode>     "
                "Set tool call display: hide | show_tools | detailed"
            )
            self.console.print(
                f"  Current reasoning mode: {self._reasoning_color(self.reasoning_mode)}\n"
            )
            self.console.print(
                f"  Current tool calls  : {self._tool_calls_color(self.tool_calls_mode)}\n"
            )
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

        return False

    # ── main loop ─────────────────────────────────────────

    def run(self) -> None:
        self.console.print(WELCOME)
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
            self.agent.chat_history += f"User: {text}\n"

            try:
                self.agent.process_with_llm()
            except Exception as exc:
                self.console.print(f"\n[red]✖ Error: {exc}[/red]")

        self.console.print("\n[red]Goodbye![/red]")


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

    def _tui_input(prompt: str, password: bool = False) -> str:
        try:
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
