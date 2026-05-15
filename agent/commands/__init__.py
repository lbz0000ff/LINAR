"""Command system — pluggable slash-command handlers for the Lily terminal.

Usage in ``terminal.py``::

    from commands import register, get_handler, all_commands

    register(SomeCommand())
    register(AnotherCommand())

    handler = get_handler(cmd_name)
    if handler:
        handler.execute(full_input, terminal)
"""


class Command:
    """Base class for a slash-command handler.

    Subclasses set ``name`` and ``description``; override ``execute()``.
    The handler runs synchronously — the LLM is not involved.

    For LLM-driven capabilities (custom prompts, tool sets) see the
    future ``Skill`` system instead.
    """

    name: str = ""
    """Slash-command name (without the ``/``)."""

    aliases: list[str] = []
    """Alternative names for the same command."""

    description: str = ""
    """One-line help text shown in ``/help``."""

    def matches(self, cmd: str) -> bool:
        """Return True if *cmd* (without ``/``) targets this command."""
        return cmd == self.name or cmd in self.aliases

    def execute(self, args: str, terminal) -> bool:
        """Handle the command.

        Parameters
        ----------
        args : str
            Everything after the command name: ``/reasoning full`` → ``"full"``.
        terminal : LilyTerminal
            The running terminal instance (access ``.agent``, ``.console``,
            ``.s()``, etc. on it).

        Return ``True`` if the command was handled (don't feed to agent),
        ``False`` to pass through.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_commands: dict[str, Command] = {}


def register(cmd: Command):
    """Register a command so it can be dispatched by name/aliases."""
    _commands[cmd.name] = cmd
    for alias in cmd.aliases:
        _commands[alias] = cmd


def get_handler(cmd: str) -> Command | None:
    """Look up a command by name (without ``/``)."""
    return _commands.get(cmd)


def all_commands() -> list[Command]:
    """Return all unique registered commands (deduplicated by name)."""
    seen: set[str] = set()
    result: list[Command] = []
    for cmd in _commands.values():
        if cmd.name not in seen:
            seen.add(cmd.name)
            result.append(cmd)
    return result
