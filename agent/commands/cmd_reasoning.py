"""``/reasoning <mode>`` — set reasoning display mode."""

from . import Command

REASONING_MODES = ("hide", "full")


class ReasoningCommand(Command):
    name = "reasoning"
    description = "Set reasoning display: full | hide"

    def execute(self, args: str, terminal) -> bool:
        if not args:
            # toggle
            current_idx = REASONING_MODES.index(terminal.reasoning_mode)
            next_idx = (current_idx + 1) % len(REASONING_MODES)
            terminal.reasoning_mode = REASONING_MODES[next_idx]
        else:
            arg = args.strip().lower()
            if arg in REASONING_MODES:
                terminal.reasoning_mode = arg
            else:
                terminal.console.print(
                    f"  Invalid mode '{arg}'. "
                    f"Use: {' | '.join(REASONING_MODES)}"
                )
                return True

        terminal.console.print(
            f"  Reasoning mode set to: {terminal._reasoning_color(terminal.reasoning_mode)}\n"
        )
        return True
