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
        self._current_response_msg = None
        self._input_expanded = False
        self._reasoning_buffer = []  # reason tokens for current response
        self._reasoning_container = None
        self._current_body_control = None  # points to Markdown body for streaming
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
            bgcolor="#0d1117",
            border_radius=8,
            expand=True,
            on_submit=self._on_submit,
        )

        self._expand_btn = ft.IconButton(
            icon=ft.icons.OPEN_IN_FULL,
            icon_color=ft.colors.with_opacity(0.5, "#ffffff"),
            tooltip="展开输入框",
            on_click=self._toggle_input_expand,
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
                    [self.input_field, send_btn, self._expand_btn],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(left=16, right=16, top=8, bottom=16),
                bgcolor="#0d1117",
            ),
        )

        self.page.update()

    # ── 消息渲染 ─────────────────────────────────────────────

    def _add_message(self, msg_type: str, text: str, **kw):
        if not text and msg_type != "agent":
            return
        is_user = msg_type == "user"
        is_system = msg_type == "system"
        bubble_color = "#7c4dff" if is_user else "#0f3460" if is_system else "#0d1117"

        ts = kw.get("timestamp", "")
        style = ft.TextStyle(color="#ffffff" if is_user else "#b0b0b0", size=14)
        if msg_type in ("tool_call", "tool_result"):
            style = ft.TextStyle(
                color="#ffab40" if msg_type == "tool_call" else "#9e9e9e",
                size=13, font_family="monospace",
            )

        # 构建消息内容列
        content_cols = []

        # 推理内容（agent 消息，可折叠）
        reasoning = kw.get("reasoning", "")
        if msg_type == "agent" and reasoning:
            reason_body = ft.Container(
                content=ft.Column([
                    ft.Text(reasoning, size=12, color="#888888", italic=True, selectable=True),
                ]),
                visible=False,
                padding=ft.padding.all(4),
            )
            self._reasoning_container = reason_body

            def make_toggle(rb):
                def toggle(e):
                    rb.visible = not rb.visible
                    self.page.update()
                return toggle

            reason_header = ft.Container(
                content=ft.Text("🤔 思考过程 ▸", size=12, color="#888888"),
                on_click=make_toggle(reason_body),
                padding=ft.padding.symmetric(vertical=4),
            )

            content_cols.append(ft.Column([reason_header, reason_body], spacing=2))

        # 消息文本
        if msg_type == "agent":
            md = ft.Markdown(
                text or "",
                extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                code_theme="monokai-sublime",
                latex_scale_factor=1.5,
                latex_style=None,
                selectable=True,
                on_tap_link=lambda e: e.page.launch_url(e.data),
            )
            content_cols.append(md)
            self._current_body_control = md
        else:
            content_cols.append(ft.Text(text, style=style, selectable=True))

        msg = ft.Container(
            content=ft.Column(content_cols, spacing=4),
            bgcolor=bubble_color,
            border_radius=ft.border_radius.only(
                top_left=18 if is_user else 8,
                top_right=8 if is_user else 18,
                bottom_left=18, bottom_right=18,
            ),
            padding=ft.padding.all(12),
        )

        wrapper = ft.Container(
            content=msg,
            margin=ft.margin.only(
                left=60 if is_user else 0,
                right=0 if is_user else 60,
            ),
        )
        self.chat_list.controls.append(wrapper)
        return msg  # return the inner Column container for _current_response_msg

    def _append_token(self, text: str):
        """追加流式 token 到当前活跃的助手回复消息。"""
        if self._current_response_msg is None:
            # 如果有推理内容，传给 _add_message
            reason_text = "".join(self._reasoning_buffer) if self._reasoning_buffer else ""
            self._current_response_msg = self._add_message("agent", "", reasoning=reason_text)
            if self._reasoning_buffer:
                self._reasoning_buffer = []
            if self._current_response_msg is None:
                return
        if self._current_body_control:
            existing = self._current_body_control.value or ""
            self._current_body_control.value = existing + text

    def _flush_ui(self):
        try:
            self.page.update()
        except Exception:
            pass

    # ── Agent 事件处理（在后台线程调用，Flet 方法线程安全）───────

    def _on_event(self, event: dict):
        etype = event.get("type", "")

        if etype == "token":
            self._append_token(event.get("data", ""))
            self._token_count += 1
            if self._token_count % 5 == 0:
                self._flush_ui()

        elif etype == "reasoning_token":
            data = event.get("data", "")
            self._reasoning_buffer.append(data)
            # 如果 reasoning container 已存在，实时追加内容
            if self._reasoning_container:
                col = self._reasoning_container.content
                if col and len(col.controls) >= 1 and isinstance(col.controls[0], ft.Text):
                    col.controls[0].value = "".join(self._reasoning_buffer)
                    if self._token_count % 5 == 0:
                        self._flush_ui()

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
            self._current_response_msg = None  # next token is a new response
            self._flush_ui()

    # ── 用户输入 ─────────────────────────────────────────────

    def _on_submit(self, e=None):
        text = self.input_field.value
        if not text or not text.strip():
            return
        self.input_field.value = ""
        self.input_field.focus()
        # Display user message immediately
        self._current_response_msg = None  # new round → new response
        self._add_message("user", text.strip())
        self._flush_ui()
        self.input_queue.put(text.strip())

    def _toggle_input_expand(self, e=None):
        """展开/折叠输入框。"""
        self._input_expanded = not self._input_expanded
        if self._input_expanded:
            self.input_field.multiline = True
            self.input_field.min_lines = 3
            self.input_field.max_lines = 10
            self.input_field.text_style = ft.TextStyle(color="#e0e0e0", size=14)
            e.control.icon = ft.icons.CLOSE_FULLSCREEN
            e.control.tooltip = "收起输入框"
        else:
            self.input_field.multiline = False
            self.input_field.min_lines = None
            self.input_field.max_lines = None
            e.control.icon = ft.icons.OPEN_IN_FULL
            e.control.tooltip = "展开输入框"
        self.page.update()

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
        """权限确认 — 内联按钮（非弹窗）。"""
        result = [None]
        done = threading.Event()
        import json

        def make_handler(value):
            def handler(e):
                result[0] = value
                done.set()
                # 移除按钮行
                if len(self.chat_list.controls) > 0:
                    self.chat_list.controls.pop()
                self.page.update()
            return handler

        btn_allow = ft.ElevatedButton(
            "✓ 允许", on_click=make_handler(True),
            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.2, "#4caf50"), color="#4caf50"),
        )
        btn_deny = ft.ElevatedButton(
            "✗ 拒绝", on_click=make_handler(False),
            style=ft.ButtonStyle(bgcolor=ft.colors.with_opacity(0.2, "#f44336"), color="#f44336"),
        )
        btn_always = ft.TextButton(
            "永久允许", on_click=make_handler("always"),
            style=ft.ButtonStyle(color=ft.colors.with_opacity(0.5, "#4caf50")),
        )
        btn_never = ft.TextButton(
            "永久拒绝", on_click=make_handler("never"),
            style=ft.ButtonStyle(color=ft.colors.with_opacity(0.5, "#f44336")),
        )

        perm_msg = ft.Container(
            content=ft.Column([
                ft.Text(f"🔒 允许调用 {tool_name}？", size=13, color="#ffab40"),
                ft.Text(f"参数: {json.dumps(args, ensure_ascii=False)[:200]}", size=11, color="#888888"),
                ft.Row([btn_allow, btn_deny, btn_always, btn_never], spacing=8),
            ], spacing=6),
            bgcolor="#1e1e2e",
            border_radius=8,
            padding=ft.padding.all(12),
            margin=ft.margin.only(left=40, right=40, top=4, bottom=4),
        )
        self.chat_list.controls.append(perm_msg)
        self._flush_ui()
        done.wait()
        return result[0]


# ── 入口 ─────────────────────────────────────────────────────

def main(page: ft.Page):
    LilyGUI(page)


if __name__ == "__main__":
    ft.app(target=main)
