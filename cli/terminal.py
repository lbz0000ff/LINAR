"""
Lily Agent Terminal — REPL-style streaming CLI.

Messages print to normal terminal scrollback (scrollable with your terminal
emulator).  The prompt appears at the bottom after each response.

Usage:
    cd agent && python -m cli.terminal
    cd agent && python cli/terminal.py
"""

import os
import sys

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.text import Text
from rich.markdown import Markdown

# ── ensure agent/ directory is on sys.path ───────────────
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import agent
Agent = agent.Agent


# ── welcome screen ────────────────────────────────────────

WELCOME = """
  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃                                                    ┃
  ┃      ██████╗ ██╗     ██╗  ██╗██╗   ██╗           ┃
  ┃      ██╔══██╗██║     ██║  ██║╚██╗ ██╔╝           ┃
  ┃      ██████╔╝██║     ███████║ ╚████╔╝            ┃
  ┃      ██╔══██╗██║     ██╔══██║  ╚██╔╝             ┃
  ┃      ██████╔╝███████╗██║  ██║   ██║              ┃
  ┃      ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝              ┃
  ┃                                                    ┃
  ┃           Lily Agent Terminal  v0.1.0              ┃
  ┃                                                    ┃
  ┃     Welcome!  Type /help for commands.             ┃
  ┃                                                    ┃
  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
"""


# ── terminal ──────────────────────────────────────────────

class LilyTerminal:
    """REPL-style streaming terminal for the Lily Agent."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.agent.emit = self._on_event   # hijack agent JSON output → print

        self.console = Console(highlight=False)
        self.session = PromptSession()

    # ── event handler (called synchronously from process_with_llm) ──

    def _on_event(self, event: dict) -> None:
        etype = event.get("type")

        if etype == "start":
            self.console.print()
            self.console.print("[bold cyan]⚡ Lily[/bold cyan]")

        elif etype == "token":
            self.console.print(event["data"], end="", flush=True)

        elif etype == "done":
            self.console.print()

        elif etype == "tool_call":
            preview = event.get("arguments", "")[:100]
            self.console.print(
                f"\n  [italic magenta]⚙  Using: {event['name']}({preview})[/italic magenta]"
            )

        elif etype == "tool_result":
            r = str(event.get("result", ""))[:200]
            self.console.print(f"  [green]  → {r}[/green]")

        elif etype == "error":
            self.console.print(
                f"\n[bold red]✖ Error: {event.get('data', 'unknown error')}[/bold red]"
            )

    # ── commands ──────────────────────────────────────────

    @staticmethod
    def _handle_command(text: str) -> bool:
        """Return True if *text* was a built-in command (caller should skip
        sending it to the agent)."""
        cmd = text.strip().lower()

        if cmd == "/exit":
            return True   # caller breaks the loop

        if cmd == "/help":
            print("\nThis is help message, which is not implemented yet.\n")
            return True

        return False

    # ── main loop ─────────────────────────────────────────

    def run(self) -> None:
        self.console.print(WELCOME)

        while True:
            try:
                text = self.session.prompt("\n╭─ ")
            except (KeyboardInterrupt, EOFError):
                # Ctrl+C / Ctrl+D → exit
                break

            text = text.strip()
            if not text:
                continue

            if self._handle_command(text):
                if text.strip().lower() == "/exit":
                    break
                continue

            # show user message
            self.console.print()
            self.console.print("[bold yellow]✦ You[/bold yellow]")
            self.console.print(text)

            # feed to agent
            self.agent.chat_history += f"User: {text}\n"

            try:
                self.agent.process_with_llm()
            except Exception as exc:
                self.console.print(f"\n[bold red]✖ Error: {exc}[/bold red]")

        self.console.print("\n[bold red]Goodbye![/bold red]")


# ── entry point ───────────────────────────────────────────

def main() -> None:
    from tool_registry import tools

    agent = Agent(tools=tools)
    cli = LilyTerminal(agent)
    cli.run()


if __name__ == "__main__":
    main()
