"""``/tool_calls <mode>`` — set tool call display mode."""

from . import Command

TOOL_CALL_MODES = ("hide", "show_tools", "detailed")


class ToolCallsCommand(Command):
    name = "tool_calls"
    description = "Set tool call display: hide | show_tools | detailed"

    def execute(self, args: str, terminal) -> bool:
        if not args:
            # toggle
            current_idx = TOOL_CALL_MODES.index(terminal.tool_calls_mode)
            next_idx = (current_idx + 1) % len(TOOL_CALL_MODES)
            terminal.tool_calls_mode = TOOL_CALL_MODES[next_idx]
        else:
            arg = args.strip().lower()
            if arg in TOOL_CALL_MODES:
                terminal.tool_calls_mode = arg
            else:
                terminal.console.print(
                    f"  Invalid mode '{arg}'. "
                    f"Use: {' | '.join(TOOL_CALL_MODES)}"
                )
                return True

        terminal.console.print(
            f"  Tool call display set to: {terminal._tool_calls_color(terminal.tool_calls_mode)}\n"
        )
        return True
