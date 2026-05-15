"""``/history`` — show conversation history."""

from . import Command


class HistoryCommand(Command):
    name = "history"
    description = "Show conversation history"

    def execute(self, args: str, terminal) -> bool:
        terminal._print_history()
        return True
