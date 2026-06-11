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

        # Clear context tracking so progress bar doesn't show stale data
        terminal._prev_prompt_tokens = None
        terminal._last_usage = None
        terminal._last_prompt_delta = None
        terminal._total_usage = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
        }

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
