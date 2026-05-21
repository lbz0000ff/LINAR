"""``/stop`` / ``/interrupt`` — interrupt the agent's current task."""

from . import Command


class StopCommand(Command):
    name = "stop"
    aliases = ["interrupt"]
    description = "Interrupt the agent's current task (alias: /interrupt)"

    def execute(self, args: str, terminal) -> bool:
        if terminal._processing:
            terminal.agent.interrupt()
            terminal._output_deque.append(
                ("fg:yellow", "\n⏹  Stop signal sent — agent will halt after current tool.")
            )
        else:
            terminal._output_deque.append(
                ("fg:cyan", "\nNothing to stop — agent is not processing a task.")
            )
        return True
