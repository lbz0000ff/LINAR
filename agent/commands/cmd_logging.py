"""``/logging`` — toggle console log output on/off."""

from . import Command
from logger import set_console_logging, console_logging_enabled


class LoggingCommand(Command):
    name = "logging"
    description = "Show/hide console log output"

    def execute(self, args: str, terminal) -> bool:
        arg = args.strip().lower()

        if arg == "hide":
            set_console_logging(False)
        elif arg == "show":
            set_console_logging(True)
        else:
            # toggle
            set_console_logging(not console_logging_enabled())

        state = "show" if console_logging_enabled() else "hide"
        terminal.console.print(f"\n  Console logging: {state}")
        return True
