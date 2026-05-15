"""``/reset`` / ``/clear`` — start a fresh conversation session."""

from . import Command


class ResetCommand(Command):
    name = "reset"
    aliases = ["clear"]
    description = "Start a new conversation session"

    def execute(self, args: str, terminal) -> bool:
        terminal.agent.reset_session()
        ns = terminal.s("new_session")
        terminal.console.print(f"\n[{ns}]── new session ──[/{ns}]")
        return True
