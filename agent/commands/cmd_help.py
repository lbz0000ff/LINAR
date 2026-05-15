"""``/help`` — show available commands and skills."""

from . import Command, all_commands
from skill import all_skills


class HelpCommand(Command):
    name = "help"
    description = "Show this message"

    def execute(self, args: str, terminal) -> bool:
        terminal.console.print("\nCommands:")
        for c in all_commands():
            names = f"/{c.name}"
            if c.aliases:
                names += f" (/{', /'.join(c.aliases)})"
            terminal.console.print(f"  {names:<30} {c.description}")

        skills = all_skills()
        if skills:
            terminal.console.print("\nSkills:")
            for s in skills:
                terminal.console.print(f"  /{s.name:<30} {s.description}")
        return True
