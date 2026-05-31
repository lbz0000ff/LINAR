"""
Lily Agent Terminal — Dual-pane TUI with always-active input.
LLM output streams in the upper pane; a fixed input bar at the bottom
stays active so the user can type messages or /commands at any time.
Messages typed while the LLM is busy are queued and processed in order.
Usage:
    cd agent && python -m cli.terminal
    cd agent && python cli/terminal.py
"""
import os
import re
import sys
import json
import time
import atexit
import asyncio
import threading
from collections import deque
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.layout.containers import Window, Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.widgets import Frame, RadioList
from prompt_toolkit.layout import FloatContainer as _FloatContainer
from rich.console import Console
from rich.text import cell_len
from rich.markup import escape as rich_escape
# ── ensure agent/ directory is on sys.path ───────────────
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
# When loaded via runpy (e.g. lily.py), ``agent`` may already be cached
# as a namespace package.  Delete it so the real ``agent/agent.py``
# module is imported instead.
if 'agent' in sys.modules and getattr(sys.modules['agent'], '__file__', None) is None:
    del sys.modules['agent']
import agent
from config import load_config
from logger import get_logger, setup_logging
from orchestrator import Orchestrator, Stage, stage_label
from commands import get_handler, all_commands, register
from commands.cmd_help import HelpCommand
from commands.cmd_reset import ResetCommand
from commands.cmd_history import HistoryCommand
from commands.cmd_reasoning import ReasoningCommand
from commands.cmd_tool_calls import ToolCallsCommand
from commands.cmd_session import SessionCommand, SessionsCommand
from commands.cmd_logging import LoggingCommand
from commands.cmd_stop import StopCommand
from commands.cmd_jobs import ListJobsCommand
from commands.cmd_reload_mcp import ReloadMCPCommand
from skill import register_skill, get_skill, all_skills, load_skills_from_markdown
Agent = agent.Agent
log = get_logger(__name__)
# ── style system ──────────────────────────────────────────
from cli.style_loader import load_style
REASONING_MODES = ("hide", "full")
TOOL_CALL_MODES = ("hide", "show_tools", "detailed")
# ── Rich color name → hex mapping for colours that prompt_toolkit
#     doesn't recognise (e.g. grey62, grey85).
_RICH_COLORS: dict[str, str] = {}
for _v in range(0, 101):
    _rgb = round(_v / 100 * 255)
    _hex = f"#{_rgb:02x}{_rgb:02x}{_rgb:02x}"
    _RICH_COLORS[f"grey{_v}"] = _hex
_ptk_named = {"red", "green", "yellow", "blue", "magenta", "cyan",
              "white", "black", "default", "gray", "grey",
              "ansired", "ansigreen", "ansiyellow", "ansiblue",
              "ansimagenta", "ansicyan", "ansiwhite", "ansiblack"}
# ── tab completer ──────────────────────────────────────────
class _CommandCompleter(Completer):
    """Tab completer for slash commands — only activates when typing `/`."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        # ── sub-arguments after a space ──
        if " " in text:
            cmd, _, partial = text.partition(" ")
            if cmd == "/reasoning":
                for mode in REASONING_MODES:
                    if mode.startswith(partial):
                        yield Completion(mode, start_position=-len(partial))
            elif cmd == "/tool_calls":
                for mode in TOOL_CALL_MODES:
                    if mode.startswith(partial):
                        yield Completion(mode, start_position=-len(partial))
            return
        # ── commands (dynamic from registry) ───────────────
        from commands import all_commands as _cmds
        for c in _cmds():
            full = f"/{c.name}"
            if full.startswith(text):
                yield Completion(full, start_position=-len(text), display_meta="cmd")
        if "/btw".startswith(text):
            yield Completion("/btw", start_position=-len(text), display_meta="cmd")
        if "/steer".startswith(text):
            yield Completion("/steer", start_position=-len(text), display_meta="cmd")
        if "/exit".startswith(text):
            yield Completion("/exit", start_position=-len(text), display_meta="cmd")
        if "/quit".startswith(text):
            yield Completion("/quit", start_position=-len(text), display_meta="cmd")
        # ── skills (dynamic from registry) ─────────────────
        from skill import all_skills as _sks
        for s in _sks():
            full = f"/{s.name}"
            if full.startswith(text):
                yield Completion(full, start_position=-len(text), display_meta="skill")
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
# ── capture console for command output → TUI ────────────────
class _CaptureConsole:
    """File-like object that captures Console.print() output and converts
    it to prompt_toolkit (style, text) fragments for the TUI."""
    def __init__(self):
        self.buffer = ""
        self._output_deque = None   # set by LilyTerminal
        self._invalidate = None     # set by LilyTerminal (app.invalidate)
    def write(self, text: str):
        self.buffer += text
    def flush(self):
        pass
    def flush_to_tui(self) -> bool:
        """Convert captured buffer to fragments and push to output deque.
        Returns True if there was content to flush.
        """
        if not self.buffer:
            return False
        from prompt_toolkit.formatted_text import to_formatted_text as _to_ft
        for style, text in _to_ft(ANSI(self.buffer)):
            self._output_deque.append((style, text))
        self.buffer = ""
        return True
# ── terminal ──────────────────────────────────────────────
class LilyTerminal:
    """Dual-pane TUI: output streams in the upper pane, input bar at
    the bottom stays active so the user can type at any time."""
    # Logo template: ECHO in "echo" color, original LILY with 3D shadow effect
    _logo = [
        # Row 0
        [("███████", "echo"), (" ", None), ("██████╗", "echo"), (" ", None), ("██╗ ██╗", "echo"), (" ", None), ("██████╗", "echo"),
         (" ", None),("██╗", "lily"), ("      ", None), ("████", "i"), ("╗", "shadow"), (" ", None),("██╗", "lily"), ("     ", None), ("██╗   ██╗", "lily")                                 ,(" ", None),(" ", None)],
        # Row 1
        [("██╔════", "echo"), (" ", None), ("██╔═══╝", "echo"), (" ", None), ("██║ ██║", "echo"), (" ", None), ("██╔═██╗", "echo"),
         (" ", None),("██║", "lily"), ("      ", None), ("╚", "shadow"), ("██", "i"), ("╔╝", "shadow"), (" ", None),("██║", "lily"), ("     ", None), ("╚", "shadow"), ("██╗ ██╔╝", "lily") ,(" ", None),(" ", None)],
        # Row 2
        [("█████╗ ", "echo"), (" ", None), ("██║    ", "echo"), (" ", None), ("██████║", "echo"), (" ", None), ("██║ ██║", "echo"),
         (" ", None),("██║", "lily"), ("       ", None), ("██", "i"),("║", "shadow"), ("  ", None),("██║", "lily"), ("      ", None), ("╚████╔╝", "lily"), (" ", None)                      ,(" ", None),(" ", None)],
        # Row 3
        [("██╔══╝ ", "echo"), (" ", None), ("██║    ", "echo"), (" ", None), ("██╔═██║", "echo"), (" ", None), ("██║ ██║", "echo"),
         (" ", None),("██║", "lily"), ("       ", None), ("██", "i"), ("╚╗", "shadow"), (" ", None),("██║", "lily"), ("       ", None), ("╚██╔╝", "lily"), ("  ", None)                     ,(" ", None),(" ", None)],
        # Row 4
        [("███████", "echo"), (" ", None), ("╚█████╗", "echo"), (" ", None), ("██║ ██║", "echo"), (" ", None), ("╚████║ ", "echo"),
         (" ", None),("███████╗", "lily"), (" ", None), ("████", "i"), ("║", "shadow"), (" ", None),("███████╗", "lily"), ("   ", None), ("██║", "lily"), ("   ", None)                     ,(" ", None),(" ", None)],
        # Row 5
        [("╚══════", "echo"), (" ", None), (" ╚════╝", "echo"), (" ", None), ("╚═╝ ╚═╝", "echo"), (" ", None), (" ╚════╝", "echo"),
         (" ", None),("╚══════╝", "lily"), (" ", None), ("╚", "shadow"), ("═══", "shadow"), ("╝", "shadow"), (" ", None),("╚══════╝", "lily"), ("   ", None), ("╚═╝", "lily"), ("   ", None),(" ", None),(" ", None)],
    ]
    _banner_text = [
        ("EchoLily Terminal  version {version}", "title"),
        ("Type /help for command help", "hint"),
    ]
    def __init__(self, agent: Agent, orchestrator: Orchestrator | None = None) -> None:
        self.agent = agent
        self.agent.emit = self._on_event
        self.orchestrator = orchestrator or Orchestrator(agent)
        self.console: Console | None = None  # created in _build_tui
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
        self._had_tool_calls = False
        self._start_time = 0.0
        self._usage: dict | None = None
        self._header_printed = False
        self._in_reasoning = False
        self._bold_active = False
        self._pending = ""
        # ── TUI state ──
        self._render_fragments: list[tuple[str, str]] = []
        self._output_deque: deque[tuple[str, str]] = deque()
        self._input_queue: deque[str] = deque()
        self._processing = False
        self._llm_thread: threading.Thread | None = None
        self._follow_output = True   # auto-scroll to bottom
        # ── promise notification ──
        self._pending_promise_notification: str = ""
        # ── confirmation popup ──
        self._confirm_visible = False
        self._confirm_event: threading.Event | None = None
        self._confirm_result: Any = None
        self._confirm_radiobox = RadioList([("", "")])
        self._confirm_title = ""
        self._confirm_prompt = ""
        self._confirm_cursor = 0
        # ── inline prompt (ask_user / confirm) ──
        self._input_event: threading.Event | None = None
        self._input_result: list[str] = []
        # TUI widgets (set by _build_tui)
        self.app: Application | None = None
        self._input_buf: Buffer | None = None
        # ── current input being processed (for steer) ──
        self._current_input = ""
        # ── session picker ──
        self._session_picker_sessions: list[dict] = []
        self._session_picker_cursor = 0
        self._session_picker_scroll = 0
        self._session_picker_active = False
        # ── btw / steer ──
        self._btw_context = ""
        self._btw_visible = False
        self._btw_fragments: list = []
        self._btw_scroll = 0
        self._output_control: FormattedTextControl | None = None
        self._capture: _CaptureConsole | None = None
    # ── config loader ─────────────────────────────────────
    @staticmethod
    def _load_config():
        from config import load_config as _lc
        return _lc()
    # ── style shortcut ────────────────────────────────────
    def s(self, key: str) -> str:
        """Shorthand — return color string for a console style key."""
        return self.style["console"].get(key, "")
    # ── style converter: Rich → prompt_toolkit ────────────
    def _ptk(self, key: str) -> str:
        """Convert a Rich-style console style key to a prompt_toolkit
        style string (e.g. ``"bold green"`` → ``"bold fg:green"``)."""
        val = self.style["console"].get(key, "")
        if not val:
            return ""
        parts = val.split()
        mapped = []
        for p in parts:
            if p.startswith("#"):
                mapped.append(f"fg:{p}")
            elif p == "dim":
                mapped.append("fg:gray")        # no dim in ptk, use gray
            elif p in ("bold", "italic", "underline", "reverse"):
                mapped.append(p)
            elif p in _ptk_named:
                mapped.append(f"fg:{p}")
            elif p in _RICH_COLORS:
                mapped.append(f"fg:{_RICH_COLORS[p]}")
            else:
                # Last resort — pass through (may produce a ptk warning
                # but won't crash).
                mapped.append(f"fg:{p}")
        return " ".join(mapped)
    # ── welcome banner ─────────────────────────────────────
    @staticmethod
    def _dw(s: str) -> int:
        """Display width of a string (CJK-aware)."""
        return cell_len(s)
    def _build_welcome_message(self) -> str:
        """Build the welcome banner as a Rich markup string."""
        banner = self.style["banner"]
        raw_logo = [
            "".join(text for text, _ in segs) for segs in self._logo
        ]
        raw_texts = list(raw_logo) + [
            t.format(version=self._version) for t, _ in self._banner_text
        ]
        content_w = max(self._dw(line) for line in raw_texts)
        bc = banner.get("border", "grey")
        top    = f"[{bc}]┏{'━' * content_w}┓[/{bc}]"
        bot    = f"[{bc}]┗{'━' * content_w}┛[/{bc}]"
        side   = f"[{bc}]┃[/{bc}]"
        blank  = f"{side}{' ' * content_w}{side}"
        lines = [top, blank]
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
    # ── TUI construction ──────────────────────────────────
    def _build_tui(self):
        """Create the prompt_toolkit Application with split layout."""
        self._render_fragments = []
        # Output pane — displays fragments
        # get_cursor_position always points to the last content line so
        # the scroll algorithm naturally keeps the bottom visible.
        self._output_control = FormattedTextControl(
            self._get_fragments,
            get_cursor_position=self._cursor_at_bottom,
        )
        self._output_window = Window(
            content=self._output_control,
            wrap_lines=True,
        )
        # Capture console for command output
        self._capture = _CaptureConsole()
        self._capture._output_deque = self._output_deque
        # force_terminal + truecolor so Console outputs ANSI escape codes
        # that _CaptureConsole.flush_to_tui() converts via prompt_toolkit.ANSI
        self.console = Console(
            file=self._capture, highlight=False,
            force_terminal=True, color_system="truecolor",
        )
        # Print welcome banner to capture console
        self.console.print(self._build_welcome_message())
        self.console.print()
        # Input buffer
        self._input_buf = Buffer(
            accept_handler=self._accept_input,
            completer=_CommandCompleter(),
            complete_while_typing=True,
        )
        # Border line above input
        input_border = Window(
            height=Dimension.exact(1),
            char='─',
            style='fg:#40a1f2',
        )
        # ">> " prompt label — shows "The agent is working..." when busy + input empty
        input_prompt = Window(
            FormattedTextControl(self._get_input_prompt),
            dont_extend_width=True,
            always_hide_cursor=True,
        )
        # Input editor (wraps to multiple lines for long input)
        input_editor = Window(
            content=BufferControl(buffer=self._input_buf),
            wrap_lines=True,
            height=Dimension(min=1, max=8),
            dont_extend_height=True,
        )
        # Combine prompt + editor horizontally
        input_window = VSplit([input_prompt, input_editor])
        # Key bindings
        kb = KeyBindings()
        # ── session picker navigation ─────────────────────
        _picker = Condition(lambda: self._session_picker_active)
        @kb.add('up', filter=_picker)
        def _picker_up(event):
            n = len(self._session_picker_sessions)
            self._session_picker_cursor = (self._session_picker_cursor - 1) % n
            # scroll up when cursor moves above the visible window
            v = self._picker_visible_lines()
            if self._session_picker_cursor < self._session_picker_scroll:
                self._session_picker_scroll = self._session_picker_cursor
            event.app.invalidate()
        @kb.add('down', filter=_picker)
        def _picker_down(event):
            n = len(self._session_picker_sessions)
            self._session_picker_cursor = (self._session_picker_cursor + 1) % n
            # scroll down when cursor moves below the visible window
            v = self._picker_visible_lines()
            if self._session_picker_cursor >= self._session_picker_scroll + v:
                self._session_picker_scroll = self._session_picker_cursor - v + 1
            event.app.invalidate()
        @kb.add('enter')
        def _enter(event):
            if self._session_picker_active:
                self._session_picker_select()
                return
            buff = event.current_buffer
            if buff.complete_state:
                completions = buff.complete_state.completions
                if completions:
                    buff.text = completions[0].text
                    buff.cursor_position = len(completions[0].text)
            buff.validate_and_handle()
        @kb.add('c-c')
        def _ctrl_c(event):
            if self._input_event is not None:
                # Abort inline prompt
                self._input_result.append("")
                self._input_event.set()
            elif self._processing:
                self.agent.interrupt()
            else:
                event.app.exit()
        # ── scroll keybindings ────────────────────────────
        @kb.add('pageup')
        def _pgup(event):
            self._follow_output = False
            w = self._output_window
            step = 15
            w.vertical_scroll = max(0, w.vertical_scroll - step)
        @kb.add('pagedown')
        def _pgdn(event):
            w = self._output_window
            step = 15
            w.vertical_scroll = w.vertical_scroll + step
        @kb.add('home')
        def _home(event):
            self._follow_output = False
            self._output_window.vertical_scroll = 0
        @kb.add('end')
        def _end(event):
            self._follow_output = True
        @kb.add('escape')
        def _escape(event):
            if self._session_picker_active:
                self._session_picker_active = False
                self.app.invalidate()
                return
            if self._btw_visible:
                self._btw_visible = False
                self.app.invalidate()
                return
            if self._confirm_visible:
                self._confirm_result = None
                self._confirm_visible = False
                if self._confirm_event:
                    self._confirm_event.set()
                self.app.invalidate()
                return
        # ── confirm dialog navigation ──
        @kb.add('up', filter=Condition(lambda: self._confirm_visible))
        def _confirm_up(event):
            vals = self._confirm_radiobox.values
            cur = self._confirm_radiobox.current_value
            idx = next((i for i, (v, _) in enumerate(vals) if v == cur), 0)
            if idx > 0:
                self._confirm_radiobox.current_value = vals[idx - 1][0]
            event.app.invalidate()
        @kb.add('down', filter=Condition(lambda: self._confirm_visible))
        def _confirm_down(event):
            vals = self._confirm_radiobox.values
            cur = self._confirm_radiobox.current_value
            idx = next((i for i, (v, _) in enumerate(vals) if v == cur), 0)
            if idx < len(vals) - 1:
                self._confirm_radiobox.current_value = vals[idx + 1][0]
            event.app.invalidate()
        @kb.add('enter', filter=Condition(lambda: self._confirm_visible))
        def _confirm_enter(event):
            self._confirm_result = self._confirm_radiobox.current_value
            self._confirm_visible = False
            if self._confirm_event:
                self._confirm_event.set()
            event.app.invalidate()
        @kb.add('s-tab')
        def _shift_tab(event):
            """Cycle through permission modes: safe → auto → review."""
            if self._session_picker_active:
                return
            modes = ["safe", "auto", "review"]
            current = self.agent.permissions.mode
            idx = (modes.index(current) + 1) % len(modes)
            self.agent.permissions.switch_mode(modes[idx])
            self.app.invalidate()
        # BTW popup window (scrollable, hidden by default)
        self._btw_window = Frame(
            title=" BTW ",
            body=Window(
                content=FormattedTextControl(self._get_btw_fragments),
                style="bg:#000000",
                wrap_lines=True,
            ),
        )
        # Layout
        body = HSplit([self._output_window, input_border, input_window])
        layout = Layout(
            FloatContainer(
                content=body,
                floats=[
                    Float(
                        xcursor=True,
                        ycursor=True,
                        content=CompletionsMenu(max_height=8),
                    ),
                    Float(
                        content=self._btw_window,
                        left=2,
                        right=2,
                        bottom=5,
                        height=lambda: 0 if not self._btw_visible else min(
                            len(self._btw_fragments) // 2 + 2, 20
                        ),
                    ),
                    Float(
                        content=Window(
                            content=FormattedTextControl(self._session_picker_text),
                            style="bg:#1a1a2e",
                        ),
                        left=2,
                        right=2,
                        bottom=1,
                        height=lambda: (
                            0 if not self._session_picker_active
                            else self._picker_visible_lines() + 4
                        ),
                    ),
                    Float(
                        content=Window(
                            content=FormattedTextControl(self._build_confirm_dialog),
                            style="bg:#1a1a2e",
                        ),
                        left=6,
                        right=6,
                        top=3,
                        height=lambda: 8 if self._confirm_visible else 0,
                    ),
                ],
            )
        )
        layout.focus(self._input_buf)
        # Create output with fallback for environments where Win32 console
        # detection fails (e.g. TERM=xterm-256color on Windows).
        try:
            from prompt_toolkit.output import create_output as _co
            _output = _co()
        except Exception:
            from prompt_toolkit.output.vt100 import Vt100_Output
            from prompt_toolkit.data_structures import Size
            from shutil import get_terminal_size
            def _get_size():
                ts = get_terminal_size()
                return Size(columns=ts.columns, rows=ts.lines)
            _output = Vt100_Output(sys.stdout, _get_size)
        self.app = Application(
            layout=layout,
            full_screen=True,
            key_bindings=kb,
            mouse_support=True,
            # Note: text selection is still possible by holding Shift
            # while clicking/dragging (standard terminal behaviour when
            # mouse tracking is active).
            output=_output,
        )
        self._capture._invalidate = self.app.invalidate
        # Flush welcome banner to fragments before starting
        self._capture.flush_to_tui()
        self._flush_deque_to_fragments()
    def _get_fragments(self):
        """Callback for FormattedTextControl — returns fragments
        with a mouse handler for scroll events."""
        if not self._render_fragments:
            return []
        return [(s, t, self._on_output_mouse) for s, t in self._render_fragments]
    def _on_output_mouse(self, me):
        """Handle mouse events on the output pane (scroll wheel)."""
        w = self._output_window
        if me.event_type == MouseEventType.SCROLL_UP:
            self._follow_output = False
            w.vertical_scroll = max(0, w.vertical_scroll - 3)
            self.app.invalidate()
            return None
        elif me.event_type == MouseEventType.SCROLL_DOWN:
            w.vertical_scroll += 3
            self.app.invalidate()
            # Re-enable follow when we've scrolled past the bottom
            self._check_follow_output()
            return None
        return NotImplemented
    def _check_follow_output(self):
        """Re-enable follow-output when scrolled to/past the bottom edge."""
        info = self._output_window.render_info
        if info is None:
            return
        bottom = info.content_height - info.window_height
        if self._output_window.vertical_scroll >= bottom - 1:
            self._follow_output = True
    def _cursor_at_bottom(self) -> Point:
        """Return a cursor position that guides the scroll algorithm.
        When *following*, point to the last content line so the scroll
        algorithm keeps the latest output visible.  Otherwise keep the
        current scroll position stable so the user can read history.
        """
        if self._follow_output:
            n = sum(t.count("\n") for _, t in self._render_fragments)
            return Point(x=0, y=n)
        cur = self._output_window.vertical_scroll if self._output_window else 0
        return Point(x=0, y=cur)
    # ── output helpers ────────────────────────────────────
    def _flush_deque_to_fragments(self) -> bool:
        """Move all items from _output_deque to _render_fragments.
        Returns True if any items were moved (caller should invalidate).
        """
        if not self._output_deque:
            return False
        while self._output_deque:
            self._render_fragments.append(self._output_deque.popleft())
        # Trim if too large
        if len(self._render_fragments) > 10000:
            self._render_fragments = self._render_fragments[-5000:]
        return True
    # ── event handler (called from agent bg thread) ──────
    def _maybe_show_header(self):
        if not self._header_printed:
            self._header_printed = True
            self._output_deque.append(("", "\n"))
            self._output_deque.append(("bold", ">> Lily\n"))
    def _on_event(self, event: dict) -> None:
        etype = event.get("type")
        # ── start ────────────────────────────────────────
        if etype == "start":
            self._response_text = ""
            self._reasoning_text = ""
            self._had_tool_calls = False
            self._start_time = time.time()
            self._pending_promise_notification = ""
            self._usage = None
            self._header_printed = False
            self._in_reasoning = False
            self._bold_active = False
            self._pending = ""
        # ── token ────────────────────────────────────────
        elif etype == "token":
            data = event["data"]
            data = re.sub(r"\[turn \d+\]\s*", "", data)
            if not data:
                return
            self._response_text += data
            # Transition out of reasoning block
            if self._in_reasoning:
                self._output_deque.append(("", "\n"))
                self._in_reasoning = False
            self._maybe_show_header()
            self._process_output_fragments(data)
        # ── reasoning_token ──────────────────────────────
        elif etype == "reasoning_token":
            data = event["data"]
            self._reasoning_text += data
            if self.reasoning_mode == "full":
                if not self._in_reasoning:
                    # Newline before first reasoning token prevents it
                    # from gluing onto the user's ╭─ prompt.
                    self._output_deque.append(("", "\n"))
                self._in_reasoning = True
                r = self._ptk("reasoning")
                self._output_deque.append((r or "italic fg:gray", data))
        # ── plan events ─────────────────────────────────
        elif etype == "plan_start":
            self._maybe_show_header()
            self._output_deque.append(("fg:cyan", "\nGenerating task plan..."))
        elif etype == "plan":
            data = event.get("data", "")
            self._maybe_show_header()
            self._output_deque.append(("bold fg:cyan", "\nPlan:"))
            for line in data.split("\n"):
                if line.strip():
                    self._output_deque.append(("", f"\n  {line}"))
        elif etype == "plan_error":
            data = event.get("data", "")
            self._output_deque.append(("fg:yellow", f"\nPlan generation issue: {data}"))
        elif etype == "plan_complete":
            data = event.get("data", "")
            self._output_deque.append(("fg:green bold", "\nPlan complete."))
        # ── done ─────────────────────────────────────────
        elif etype == "done":
            self._output_deque.append(("", "\n"))
        # ── complete ─────────────────────────────────────
        elif etype == "complete":
            self._print_stats_fragments()
        # ── promise_resolved ──────────────────────────────
        elif etype == "promise_resolved":
            pid = event.get("data", {}).get("id", "?")
            result = event.get("data", {}).get("result", {})
            h = self.s("header")
            self._output_deque.append(
                (h, f"\n[Promise {pid} completed]")
            )
            # Notify user in the input prompt area on next refresh
            self._pending_promise_notification = pid
            mode = self.agent.permissions.mode.upper()
            if mode == "AUTO":
                self.agent.chat_history.append({
                    "role": "meta",
                    "content": "[BACKGROUND TASK COMPLETED] " + pid + "\nResult: " + str(result),
                })
                # Trigger LLM to process the completed task
                self._input_queue.append("[task completed]")
                if not self._processing:
                    self._start_processing()
            elif mode == "SAFE":
                choice = self._show_confirm_dialog(
                    "Task Completed",
                    "Job \"" + pid + "\" completed. Inform the agent now?",
                    [("yes", "Yes"), ("no", "Not now")],
                )
                if choice == "yes":
                    self.agent.chat_history.append({
                        "role": "meta",
                        "content": "[BACKGROUND TASK COMPLETED] " + pid + "\nResult: " + str(result),
                    })
                # Trigger LLM to process the completed task
                self._input_queue.append("[task completed]")
                if not self._processing:
                    self._start_processing()
        # ── skill_loaded ────────────────────────────────
        elif etype == "skill_loaded":
            data = event.get("data", {})
            name = data.get("name", "?")
            desc = data.get("desc", "")
            self._output_deque.append(("bold green", "  [Skill loaded] " + name))
            if desc:
                self._output_deque.append(("", f" — {desc}"))
        # ── usage ────────────────────────────────────────
        elif etype == "usage":
            self._usage = event.get("data")
        # ── tool_call ────────────────────────────────────
        elif etype == "tool_call":
            self._had_tool_calls = True
            if self.tool_calls_mode == "hide":
                return
            name = event["name"]
            tn = self._ptk("tool_name") or "fg:grey85"
            if self.tool_calls_mode == "show_tools":
                self._output_deque.append((tn, f"\n⚙ Using: {name}"))
            elif self.tool_calls_mode == "detailed":
                preview = event.get("arguments", "")[:120]
                self._output_deque.append((tn, f"\n⚙ Using: {name}"))
                td = self._ptk("tool_detail") or "fg:grey62"
                self._output_deque.append((td, f"\n  {preview}"))
        # ── tool_result ──────────────────────────────────
        elif etype == "tool_result":
            self._had_tool_calls = True
            if self.tool_calls_mode == "detailed":
                r = str(event.get("result", ""))[:200]
                td = self._ptk("tool_detail") or "fg:grey62"
                self._output_deque.append((td, f"\n  → {r}"))
        # ── error ────────────────────────────────────────
        elif etype == "error":
            data = str(event.get('data', 'unknown error'))
            err = self._ptk("error") or "fg:red"
            self._output_deque.append((err, f"\n✖ Error: {data}"))
        # ── btw ──────────────────────────────────────────
        elif etype == "btw":
            data = event.get("data", "")
            if data:
                g = self._ptk("success") or "fg:green"
                self._output_deque.append((g, f'\nBTW: "{data}"'))
    # ── output text processor (bold markers) ─────────────
    def _process_output_fragments(self, text: str) -> None:
        """Append text to the output deque, handling **bold** markers."""
        if not text:
            return
        self._pending += text
        while True:
            idx = self._pending.find("**")
            if idx == -1:
                break
            prefix = self._pending[:idx]
            if prefix:
                style = "bold" if self._bold_active else ""
                self._output_deque.append((style, prefix))
            self._bold_active = not self._bold_active
            self._pending = self._pending[idx + 2:]
        # Handle lone trailing * (start of ** in next chunk)
        if self._pending.endswith("*") and not self._pending.endswith("**"):
            trailing = self._pending[:-1]
            saved = "*"
        else:
            trailing = self._pending
            saved = ""
        if trailing:
            style = "bold" if self._bold_active else ""
            self._output_deque.append((style, trailing))
        self._pending = saved
    # ── stats display ─────────────────────────────────────
    def _print_stats_fragments(self) -> None:
        elapsed = time.time() - self._start_time
        elapsed_str = _format_time(elapsed)
        used = (self._usage or {}).get("total_tokens", 0)
        used_str = _format_tokens(used)
        max_str = _format_tokens(self._max_tokens)
        pct = min(used / self._max_tokens * 100, 100)
        if pct > 70:
            color = self._ptk("stats_bad") or "fg:red"
        elif pct > 50:
            color = self._ptk("stats_warn") or "fg:yellow bold"
        else:
            color = self._ptk("stats_good") or "fg:green bold"
        bar = _progress_bar(used, self._max_tokens)
        dim = self._ptk("stats_dim") or "fg:grey62"
        self._output_deque.append((dim, f"\n  ⏱ {elapsed_str}  │  "))
        self._output_deque.append((color, f"Tokens: {used_str} / {max_str}  {bar}"))
    # ── chat history display ──────────────────────────────
    def _print_history(self) -> None:
        """Print conversation history to the capture console."""
        history = self.agent.chat_history
        if not history:
            return
        self.console.print("\n— Conversation History —")
        for chat in history:
            role = chat["role"]
            if role == "user":
                content = rich_escape(chat["content"])
                self.console.print(
                    f"\n[{self.s('header_user')}]User[/{self.s('header_user')}]"
                    f"> [grey62]{content}[/grey62]"
                )
            elif role == "agent":
                content = rich_escape(chat["content"])
                self.console.print(
                    f"\n[{self.s('header')}]Lily[/{self.s('header')}]"
                    f"> [grey62]{content}[/grey62]"
                )
            elif role == "tool":
                tool_name = chat.get("name")
                tn = self.s("tool_name")
                self.console.print(f"\n    [{tn}]Agent called tool {tool_name}[/{tn}]...")
        self.console.print("\n— Conversation History —")
    # ── input prompt ─────────────────────────────────────
    def _get_input_prompt(self) -> list[tuple[str, str]]:
        """Return the input prompt label — shows mode and working status."""
        mode = self.agent.permissions.mode.upper()
        colors = {"SAFE": "#40a1f2", "AUTO": "#ff6b6b", "REVIEW": "#ffd93d"}
        color = colors.get(mode, "#40a1f2")
        parts = [
            (f"fg:{color}", f"[{mode}] "),
            ("fg:#40a1f2", ">> "),
        ]
        if self._processing and self._input_buf and not self._input_buf.text:
            parts.append((f"fg:{_RICH_COLORS.get('grey58', '#949494')}", "The agent is working... "))
        elif not self._processing and self._pending_promise_notification:
            pid = self._pending_promise_notification
            self._pending_promise_notification = ""  # 显示一次后清除
            parts.append((f"fg:green bold",
                          f"[Job {pid} completed] "))
        return parts
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
    # ── session picker (overlay) ──────────────────────────
    def activate_session_picker(self, sessions: list[dict]) -> None:
        """Show the session picker overlay."""
        self._session_picker_sessions = sessions
        self._session_picker_cursor = 0
        self._session_picker_scroll = 0
        self._session_picker_active = True
        self.app.invalidate()
    def _picker_visible_lines(self) -> int:
        """Number of session lines that fit in the picker overlay.
        Derived from the same computation used for the float height.
        """
        rows = self.app.output.get_size().rows if self.app else 24
        return max(6, rows // 2) - 4  # minus header(2) + footer(2)
    def _session_picker_text(self) -> list[tuple[str, str]]:
        """Formatted text for the session picker float."""
        if not self._session_picker_active:
            return []
        sessions = self._session_picker_sessions
        cursor = self._session_picker_cursor
        current_id = self.agent.session_id
        dim = f"fg:{_RICH_COLORS.get('grey58', '#949494')}"
        n_visible = self._picker_visible_lines()
        max_scroll = max(0, len(sessions) - n_visible)
        scroll = min(self._session_picker_scroll, max_scroll)
        lines: list[tuple[str, str]] = []
        lines.append(("bold", f"  Sessions ({len(sessions)} total)\n"))
        lines.append((dim, f"  {'─' * 50}\n"))
        for i in range(scroll, scroll + n_visible):
            if i >= len(sessions):
                break
            s = sessions[i]
            prefix = "▸ " if i == cursor else "  "
            marker = "  ← active" if s["id"] == current_id else ""
            title = (s.get("title") or "")[:60]
            date = (s.get("created_at") or "")[:19]
            style = "bold" if i == cursor else ""
            lines.append((style, f"{prefix}#{s['id']}  {date}  {title}{marker}\n"))
        lines.append((dim, f"\n  {'─' * 50}\n"))
        lines.append((dim, "  ↑↓ select  |  Enter switch  |  Esc cancel"))
        return lines
    def _session_picker_select(self) -> None:
        """Called when Enter is pressed with picker active."""
        if not self._session_picker_active:
            return
        sessions = self._session_picker_sessions
        cursor = self._session_picker_cursor
        self._session_picker_active = False
        if 0 <= cursor < len(sessions):
            sid = sessions[cursor]["id"]
            if sid != self.agent.session_id:
                if self._processing:
                    self.console.print("\n  Can't switch sessions while the agent is processing.")
                    self.app.invalidate()
                    return
                if self.agent.switch_session(sid):
                    ns = self.s("new_session")
                    self.console.print(f"\n  [{ns}]Switched to session #{sid}[/{ns}]")
                else:
                    e = self.s("error")
                    self.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
        self.app.invalidate()
    # ── TUI: input handler ────────────────────────────────
    def _accept_input(self, buf: Buffer) -> bool:
        """Called when the user presses Enter in the input buffer."""
        text = buf.text.strip()
        buf.text = ""
        if not text:
            return True
        # ── paste detection: collapse long pastes to a marker ──
        raw_lines = text.count('\n') + 1
        if raw_lines > 10:
            text = f"[pasted {raw_lines} lines]"
            self._output_deque.append(("fg:cyan", f"\n  {text}"))
        if text.startswith("/"):
            if text.lower() in ("/exit", "/quit"):
                # Do cleanup synchronously first, then exit immediately
                # without waiting for the prompt_toolkit event loop to
                # wind down (which can take time on large displays).
                from tool_registry import shutdown_mcp_servers
                shutdown_mcp_servers()
                import shutil
                _tmp = os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), ".temp")
                if os.path.isdir(_tmp):
                    shutil.rmtree(_tmp, ignore_errors=True)
                print("\nGoodbye!", flush=True)
                os._exit(0)
            if text.startswith("/steer"):
                msg = text[6:].strip()
                if self._processing and self._current_input:
                    self.agent.interrupt()
                    corrected = f"[修正: {msg}] {self._current_input}"
                    self._input_queue.appendleft(corrected)
                else:
                    self.agent.btw(msg or "(empty note)")
                self._output_deque.append(("fg:green", "\n✓ Steer noted"))
                return True
            if text.startswith("/btw"):
                msg = text[4:].strip()
                if msg:
                    self._output_deque.append(("fg:green", "\n⚡ BTW query..."))
                    threading.Thread(target=self._answer_btw, args=(msg,), daemon=True).start()
                return True
            cmd_name = text[1:].split(maxsplit=1)[0]
            args = text[len(cmd_name) + 1:].strip() if cmd_name else ""
            # Registered command handler — execute immediately
            handler = get_handler(cmd_name)
            if handler:
                self._follow_output = True
                self._output_deque.append(("bold", f"\n\n╭─ {text}"))
                handler.execute(args, self)
                return True
            # Skill — queue for background processing
            skill = get_skill(cmd_name)
            if skill:
                self._follow_output = True
                self._input_queue.append(text)
                if not self._processing:
                    self._start_processing()
                return True
            # Unknown command
            err = self._ptk("error") or "fg:red"
            self._output_deque.append(
                (err, f"\n Unknown command: '{cmd_name}'. Type /help.")
            )
            return True
        # Plain text — queue for LLM processing
        self._follow_output = True
        self._input_queue.append(text)
        if not self._processing:
            self._start_processing()
        return True
    # ── background LLM processing ─────────────────────────
    def _start_processing(self) -> None:
        """Start the background thread that processes queued messages."""
        self._processing = True
        def _run():
            try:
                while self._input_queue:
                    text = self._input_queue.popleft()
                    # Show user input in output now (about to process)
                    self._output_deque.append(("bold", f"\n\n╭─ {text}"))
                    # Check for skill invocation
                    if text.startswith("/"):
                        cmd_name = text[1:].split(maxsplit=1)[0]
                        args = text[len(cmd_name) + 1:].strip() if " " in text else ""
                        skill = get_skill(cmd_name)
                        if skill:
                            self.orchestrator.run_skill(skill, args)
                            continue
                    # Normal text — save as current/btw context, process through orchestrator
                    self._current_input = text
                    self._btw_context = text
                    self.orchestrator.start(text)
            except Exception as exc:
                log.exception("Unhandled error during processing")
                err = self._ptk("error") or "fg:red"
                self._output_deque.append((err, f"\n✖ Error: {exc}"))
            finally:
                self._processing = False
                self._output_deque.append(("", "\n"))
        self._llm_thread = threading.Thread(target=_run, daemon=True)
        self._llm_thread.start()
    # ── btw side query ─────────────────────────────────────
    def _get_btw_fragments(self):
        """Return BTW popup content (empty when hidden)."""
        if not self._btw_visible or not self._btw_fragments:
            return []
        return [(s, t, self._on_btw_mouse) for s, t in self._btw_fragments]
    def _on_btw_mouse(self, me):
        """Mouse handler for BTW popup — scroll inside float only."""
        if me.event_type == MouseEventType.SCROLL_UP:
            self._btw_scroll = max(0, self._btw_scroll - 1)
            self._btw_window.vertical_scroll = self._btw_scroll
            self.app.invalidate()
            return None
        elif me.event_type == MouseEventType.SCROLL_DOWN:
            self._btw_scroll += 1
            self._btw_window.vertical_scroll = self._btw_scroll
            self.app.invalidate()
            return None
        return NotImplemented
    def _answer_btw(self, question: str) -> None:
        """Lightweight side LLM query with original context, no tools."""
        try:
            cfg = load_config()
            aux_cfg = cfg.get("aux") or {}
            from openai import OpenAI
            client = OpenAI(
                base_url=aux_cfg.get("base_url") or cfg["llm"]["base_url"],
                api_key=aux_cfg.get("api_key") or cfg["llm"]["api_key"],
            )
            resp = client.chat.completions.create(
                model=aux_cfg.get("model") or cfg["llm"]["model"],
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer concisely based on the context provided."},
                    {"role": "user", "content": f"User's original request:\n{self._btw_context or '(no context)'}\n\nSide question:\n{question}"},
                ],
                temperature=0.5,
                max_tokens=500,
            )
            answer = resp.choices[0].message.content.strip()
        except Exception as exc:
            answer = f"(BTW query failed: {exc})"
        h = self._ptk("console.header") or "fg:#ad2228"
        s = self._ptk("success") or "fg:green"
        d = self._ptk("tool_detail") or "fg:grey62"
        self._btw_fragments = [
            (h, " ── BTW ────────────────────────────────────────\n"),
            ("", "Q: "), (s, f"{question}\n"),
            ("", "A: "), (d, f"{answer}\n"),
        ]
        self._btw_scroll = 0
        self._btw_window.vertical_scroll = 0
        self._btw_visible = True
        if self.app:
            self.app.invalidate()
    # ── inline prompt (called from bg thread via agent callbacks) ──
    def _capture_input(self) -> str:
        """Swap the input buffer to capture one line, return it."""
        ev = threading.Event()
        self._input_event = ev
        self._input_result.clear()
        def _handler(buf):
            text = buf.text.strip()
            buf.text = ""
            self._output_deque.append(("", f"{text}\n"))
            self._input_result.append(text)
            ev.set()
            return True
        old = self._input_buf.accept_handler
        self._input_buf.accept_handler = _handler
        ev.wait(timeout=120)
        self._input_buf.accept_handler = old
        self._input_event = None
        return self._input_result[0] if self._input_result else ""
    def _build_confirm_dialog(self) -> list[tuple[str, str]]:
        """Build the confirmation popup content."""
        if not self._confirm_visible:
            return []
        result: list[tuple[str, str]] = []
        # Title
        result.append(("bold fg:yellow", f"\n  {self._confirm_title}\n"))
        result.append(("", f"  {self._confirm_prompt}\n\n"))
        # RadioList entries
        for i, (value, text) in enumerate(self._confirm_radiobox.values):
            selected = self._confirm_radiobox.current_value == value
            marker = "●" if selected else "○"
            style = "fg:cyan bold" if selected else ""
            result.append((style, f"  {marker} {text}\n"))
        # Footer
        result.append(("fg:ansigray", "\n  ↑↓ Navigate  •  Enter Confirm  •  Esc Cancel"))
        return result
    def _show_confirm_dialog(self, title: str, prompt: str, options: list[tuple[str, str]]) -> str | None:
        """Show a popup with arrow-key navigation, return selected value or None on cancel."""
        ev = threading.Event()
        self._confirm_visible = True
        self._confirm_title = title
        self._confirm_prompt = prompt
        self._confirm_event = ev
        self._confirm_result = None
        self._confirm_radiobox.values = options
        self._confirm_radiobox.current_value = options[0][0] if options else ""
        self._confirm_cursor = 0
        self.app.invalidate()
        ev.wait(timeout=120)
        self._confirm_visible = False
        return self._confirm_result
    def _prompt_user(self, prompt: str, password: bool = False, choices: list | None = None) -> str:
        """Show a prompt with popup for choices, or fallback to text input."""
        if choices:
            options = [(str(i), c) for i, c in enumerate(choices)]
            result = self._show_confirm_dialog("Question", prompt, options)
            if result is not None:
                idx = int(result)
                if 0 <= idx < len(choices):
                    return choices[idx]
        # Fallback: text input
        if password:
            self._output_deque.append(("fg:yellow", " (password will be visible)"))
        self._output_deque.append(("bold", f"\n{prompt}\n> "))
        self.app.invalidate()
        return self._capture_input()
    def _confirm_tool(self, name: str, args: str | dict) -> bool | str:
        """Ask the user to confirm a tool call via popup."""
        if isinstance(args, dict):
            args_str = json.dumps(args, ensure_ascii=False)[:120]
        else:
            args_str = str(args)[:120]
        options = [
            ("allow", "Allow once"),
            ("always", "Always allow"),
            ("deny", "Deny once"),
            ("never", "Never allow"),
        ]
        result = self._show_confirm_dialog("Permission Required",
                                           f"Allow {name}({args_str})?", options)
        if result == "allow":
            return True
        if result == "always":
            return "always"
        if result == "deny":
            return False
        if result == "never":
            return "never"
        return False
    # ── main entry point ──────────────────────────────────
    def run(self) -> None:
        self._build_tui()
        async def _flush_loop():
            while True:
                try:
                    dirty = self._flush_deque_to_fragments()
                    # Also flush captured console output (from commands)
                    if self._capture.flush_to_tui():
                        dirty = True
                        # flush any new items that capture put in the deque
                        if self._flush_deque_to_fragments():
                            dirty = True
                    if dirty:
                        self.app.invalidate()
                except Exception as exc:
                    log.exception("_flush_loop error: %s", exc)
                await asyncio.sleep(0.05)
        async def _main():
            asyncio.ensure_future(_flush_loop())
            await self.app.run_async()
        asyncio.run(_main())
        log.info("Lily shutdown")
        goodbye = self._ptk("goodbye") or "fg:red"
        self._render_fragments.append((goodbye, "\nGoodbye!"))
        # Use print since the TUI is shutting down
        print("\nGoodbye!")
        # Shut down MCP servers
        try:
            from tool_registry import shutdown_mcp_servers
            shutdown_mcp_servers()
        except Exception:
            pass
        # Clean up .temp directory
        try:
            import shutil
            temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".temp")
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
# ── entry point ───────────────────────────────────────────
def main() -> None:
    from tool_registry import get_tools
    from config import load_config
    _cfg = load_config()
    log_cfg = _cfg.get("logging", {})
    setup_logging(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file"),
        max_bytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
        backup_count=log_cfg.get("backup_count", 7),
        console=log_cfg.get("console", True),
    )
    log.info("Lily v%s starting", _cfg.get("version", "?"))
    log.debug("Config: %s", _cfg)
    # Register .temp cleanup on exit / crash
    _temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".temp")
    def _clean_temp():
        import shutil
        if os.path.isdir(_temp_dir):
            shutil.rmtree(_temp_dir, ignore_errors=True)
    atexit.register(_clean_temp)
    # ── register commands ──
    register(HelpCommand())
    register(ResetCommand())
    register(HistoryCommand())
    register(ReasoningCommand())
    register(ToolCallsCommand())
    register(SessionCommand())
    register(SessionsCommand())
    register(LoggingCommand())
    register(StopCommand())
    register(ListJobsCommand())
    register(ReloadMCPCommand())
    log.info("Registered %d commands", len(all_commands()))
    # ── register skills ──
    md_count = load_skills_from_markdown(
        os.path.join(os.path.dirname(_AGENT_DIR), "skills")
    )
    if md_count:
        log.info("Loaded %d Markdown skill(s)", md_count)
    log.info("Registered %d skills", len(all_skills()))
    _enabled = _cfg.get("tools", {}).get("enabled_sets", None)
    tools = get_tools(_enabled)
    # Create agent (callbacks wired after cli is created below).
    agent = Agent(tools=tools)
    cli = LilyTerminal(agent)
    # Wire interactive callbacks to cli's inline prompt mechanism.
    # These run from the agent's bg thread and use threading.Event to
    # coordinate with the main event loop.
    for t in tools.values():
        t.interactive_input = cli._prompt_user
    agent._confirm_callback = cli._confirm_tool
    cli.run()
if __name__ == "__main__":
    main()
