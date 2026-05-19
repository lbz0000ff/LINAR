"""``/reset`` / ``/clear`` — reset agent memories.

- ``/reset`` — reset current session (keep saved history).
- ``/reset --all`` — reset EVERYTHING: all sessions and DB.
"""

from . import Command
import database as db


class ResetCommand(Command):
    name = "reset"
    aliases = ["clear"]
    description = "Reset current session; use --all to wipe all history"

    def execute(self, args: str, terminal) -> bool:
        args = args.strip().lower()

        if args == "--all":
            terminal.console.print("  Resetting all agent memories...")
            terminal.agent.reset_session()
            db.reset_db()
            ns = terminal.s("new_session")
            terminal.console.print(f"\n[{ns}]── full reset done ──[/{ns}]")
        else:
            terminal.agent.reset_session()
            ns = terminal.s("new_session")
            terminal.console.print(f"\n[{ns}]── new session ──[/{ns}]")

        return True
