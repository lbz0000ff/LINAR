"""EchoLily 最小桌面 GUI — Flet 实现。

用法:
    python -m agent.gui.main
"""

import os
import sys
import json
import queue
import threading
from datetime import datetime

import flet as ft

# ── agent 初始化 ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AGENT_DIR = os.path.join(_PROJECT_ROOT, "agent")
sys.path.insert(0, _AGENT_DIR)

from config import load_config
from logger import get_logger
from orchestrator import Orchestrator
from skill import load_skills_from_markdown
from tool_registry import get_tools
from agent.agent import Agent

log = get_logger(__name__)


class LilyGUI:
    """Flet 桌面 GUI — 最小可用版本。"""

    def __init__(self, page: ft.Page):
        self.page = page
        self._token_count = 0
        self._setup_page()

        # ── 初始化 Agent ────────────────────────────────────
        _cfg = load_config()
        _enabled = _cfg.get("tools", {}).get("enabled_sets", None)
        tools = get_tools(_enabled)
        _skills_dir = os.path.join(_PROJECT_ROOT, "skills")
        if os.path.isdir(_skills_dir):
            load_skills_from_markdown(_skills_dir)

        self.agent = Agent(tools=tools)
        self.orchestrator = Orchestrator(self.agent)
        self.agent.emit = self._on_event

        for t in tools.values():
            t.interactive_input = self._prompt_user
        self.agent._confirm_callback = self._confirm_tool

        # ── 线程通信 ────────────────────────────────────────
        self.input_queue: queue.Queue[str] = queue.Queue()
        self._input_result: list[str] = [""]
        self._input_event = threading.Event()

        # ── 启动 Agent 后台线程 ──────────────────────────────
        self._agent_thread = threading.Thread(
            target=self._run_agent, daemon=True, name="agent"
        )
        self._agent_thread.start()

    def _setup_page(self):
        self.page.title = "EchoLily"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.spacing = 0
        self.page.window_width = 1100
        self.page.window_height = 750

        self.chat_list = ft.ListView(
            expand=True,
            spacing=4,
            padding=ft.padding.only(left=16, right=16, top=16, bottom=8),
            auto_scroll=True,
        )

        self.input_field = ft.TextField(
            hint_text="输入消息…",
            border_color=ft.colors.with_opacity(0.3, "#ffffff"),
            focused_border_color="#7c4dff",
            cursor_color="#7c4dff",
            text_style=ft.TextStyle(color="#e0e0e0", size=14),
            bgcolor="#16213e",
            border_radius=8,
            expand=True,
            on_submit=self._on_submit,
        )

        send_btn = ft.IconButton(
            icon=ft.icons.SEND_ROUNDED,
            icon_color="#7c4dff",
            tooltip="发送",
            on_click=self._on_submit,
        )

        self.page.add(
            ft.Container(
                content=self.chat_list,
                expand=True,
                bgcolor="#1a1a2e",
            ),
            ft.Divider(height=1, color=ft.colors.with_opacity(0.1, "#ffffff")),
            ft.Container(
                content=ft.Row(
                    [self.input_field, send_btn],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(left=16, right=16, top=8, bottom=16),
                bgcolor="#16213e",
            ),
        )

        self._add_message("system", "EchoLily 已就绪。")
        self.page.update()

    # ── 消息渲染 ─────────────────────────────────────────────

    def _add_message(self, msg_type: str, text: str, **kw):
        if not text:
            return
        is_user = msg_type == "user"
        is_system = msg_type == "system"
        bubble_color = "#7c4dff" if is_user else "#0f3460" if is_system else "#16213e"

        ts = kw.get("timestamp", "")
        style = ft.TextStyle(color="#ffffff" if is_user else "#b0b0b0", size=14)
        if msg_type in ("tool_call", "tool_result"):
            style = ft.TextStyle(
                color="#ffab40" if msg_type == "tool_call" else "#9e9e9e",
                size=13, font_family="monospace",
            )

        msg = ft.Container(
            content=ft.Column([
                ft.Text(ts, size=11, color=ft.colors.with_opacity(0.4, "#ffffff")),
                ft.Text(text, style=style, selectable=True),
            ], spacing=2),
            bgcolor=bubble_color,
            border_radius=ft.border_radius.only(
                top_left=18 if is_user else 8,
                top_right=8 if is_user else 18,
                bottom_left=18, bottom_right=18,
            ),
            padding=ft.padding.all(12),
        )

        self.chat_list.controls.append(
            ft.Container(
                content=msg,
                margin=ft.margin.only(
                    left=60 if is_user else 0,
                    right=0 if is_user else 60,
                ),
            )
        )

    def _append_token(self, text: str):
        """追加流式 token 到最后一条助手消息。"""
        if not self.chat_list.controls:
            self._add_message("agent", text)
            return
        last = self.chat_list.controls[-1]
        if not hasattr(last, "content") or not hasattr(last.content, "content"):
            self._add_message("agent", text)
            return
        col = last.content.content
        if len(col.controls) >= 2 and isinstance(col.controls[1], ft.Text):
            existing = col.controls[1].value or ""
            col.controls[1].value = existing + text

    def _flush_ui(self):
        try:
            self.page.update()
        except Exception:
            pass

    # ── Agent 事件处理（在后台线程调用，Flet 方法线程安全）───────

    def _on_event(self, event: dict):
        etype = event.get("type", "")

        if etype == "user_echo":
            self._add_message("user", event.get("data", ""))
            self._flush_ui()

        elif etype == "token":
            self._append_token(event.get("data", ""))
            self._token_count += 1
            if self._token_count % 5 == 0:
                self._flush_ui()

        elif etype == "reasoning_token":
            pass

        elif etype == "tool_call":
            self._add_message("tool_call", f"⚙ 调用工具: {event.get('name', '?')}")
            self._flush_ui()

        elif etype == "tool_result":
            result = str(event.get("result", ""))[:300]
            self._add_message("tool_result", f"→ {result}")
            self._flush_ui()

        elif etype == "error":
            self._add_message("system", f"✖ 错误: {event.get('data', '')}")
            self._flush_ui()

        elif etype in ("complete", "done"):
            self._token_count = 0
            self._flush_ui()

    # ── 用户输入 ─────────────────────────────────────────────

    def _on_submit(self, e=None):
        text = self.input_field.value
        if not text or not text.strip():
            return
        self.input_field.value = ""
        self.input_field.focus()
        self.page.update()
        self.input_queue.put(text.strip())

    def _run_agent(self):
        while True:
            text = self.input_queue.get()
            if text is None:
                break
            self.orchestrator.start(text)

    # ── 交互回调（ask_user / 权限确认）──────────────────────

    def _prompt_user(self, prompt: str) -> str:
        result = [""]
        done = threading.Event()

        def on_confirm(e):
            result[0] = dlg_text.value or ""
            dlg.open = False
            done.set()
            self.page.update()

        dlg_text = ft.TextField(hint_text=prompt, multiline=True, min_lines=2, max_lines=8)
        dlg = ft.AlertDialog(
            title=ft.Text("Agent 需要输入"),
            content=dlg_text,
            actions=[ft.TextButton("确认", on_click=on_confirm)],
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()
        done.wait()
        return result[0]

    def _confirm_tool(self, tool_name: str, args: dict) -> bool | None:
        result = [None]
        done = threading.Event()

        def on_allow(e):
            result[0] = True
            dlg.open = False
            done.set()
            self.page.update()

        def on_deny(e):
            result[0] = False
            dlg.open = False
            done.set()
            self.page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(f"允许调用 {tool_name}？"),
            content=ft.Text(
                f"参数:\n{json.dumps(args, indent=2, ensure_ascii=False)[:500]}"
            ),
            actions=[
                ft.TextButton("拒绝", on_click=on_deny),
                ft.TextButton("允许", on_click=on_allow),
            ],
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()
        done.wait()
        return result[0]


# ── 入口 ─────────────────────────────────────────────────────

def main(page: ft.Page):
    LilyGUI(page)


if __name__ == "__main__":
    ft.app(target=main)
