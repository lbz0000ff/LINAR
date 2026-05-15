"""Agent orchestrator — explicit state machine around the LLM loop.

The current single-path flow::

    IDLE → INGEST → ROUTE → PROCESS → COMPLETE → IDLE

Future states can be added by extending ``Stage`` and adding a branch
in ``_route()``.  Transitions are hardcoded;  LLM decisions happen
*inside* PROCESS via tool calling (same as before).
"""

from __future__ import annotations

from enum import Enum, auto


class Stage(Enum):
    """All valid states the orchestrator can be in."""

    IDLE = auto()          # waiting for user input
    INGEST = auto()        # received input, storing
    ROUTE = auto()         # classify → decide which path
    PROCESS = auto()       # LLM tool-calling loop
    SKILL_LOAD = auto()    # save state + swap prompt/tools
    SKILL_EXEC = auto()    # LLM tool-calling loop (skill mode)
    SKILL_UNLOAD = auto()  # restore pre-skill state
    COMPLETE = auto()      # finalizing turn
    ERROR = auto()         # unrecoverable error


# ── edge labels (used for logging / display) ────────────────

_STAGE_LABELS = {
    Stage.IDLE: "idle",
    Stage.INGEST: "ingest",
    Stage.ROUTE: "route",
    Stage.PROCESS: "process",
    Stage.SKILL_LOAD: "skill_load",
    Stage.SKILL_EXEC: "skill_exec",
    Stage.SKILL_UNLOAD: "skill_unload",
    Stage.COMPLETE: "complete",
    Stage.ERROR: "error",
}


def stage_label(stage: Stage) -> str:
    return _STAGE_LABELS.get(stage, stage.name.lower())


# ── orchestrator ───────────────────────────────────────────

class Orchestrator:
    """State machine that wraps ``agent.process_with_llm()``.

    Usage in the terminal REPL::

        orch = Orchestrator(agent)
        orch.start(user_text)           # run the full state machine
        print(orch.stage)               # → Stage.IDLE
    """

    def __init__(self, agent) -> None:
        self.agent = agent
        self.stage: Stage = Stage.IDLE
        self.previous_stage: Stage | None = None

    # ── public API ────────────────────────────────────────

    def start(self, user_input: str) -> None:
        """Run a full turn through the state machine.

        Blocks until the agent produces a final answer (or errors out).
        Events are emitted through ``agent.emit()`` as before.
        """
        self._transition(Stage.INGEST)
        self.agent.add_user_message(user_input)

        self._transition(Stage.ROUTE)
        self._route()

        self._transition(Stage.PROCESS)
        try:
            self.agent.process_with_llm()
        except Exception:
            self._transition(Stage.ERROR)
            raise

        self._transition(Stage.COMPLETE)
        self._transition(Stage.IDLE)

    def run_skill(self, skill, user_input: str) -> None:
        """Run a skill: save state → swap prompt/tools → LLM loop → restore.

        Blocks until the skill produces a final answer (or errors out).
        """
        self._transition(Stage.SKILL_LOAD)
        skill.on_load(self.agent)
        self.agent.add_user_message(user_input)

        self._transition(Stage.SKILL_EXEC)
        try:
            self.agent.process_with_llm()
        except Exception:
            self._transition(Stage.ERROR)
            skill.on_unload(self.agent)
            raise

        self._transition(Stage.SKILL_UNLOAD)
        skill.on_unload(self.agent)

        self._transition(Stage.COMPLETE)
        self._transition(Stage.IDLE)

    # ── routing ───────────────────────────────────────────

    def _route(self) -> None:
        """Classify input and decide which processing path.

        Single-agent: always continues to PROCESS.
        Future: LLM-driven dispatch to specialised sub-agents.
        """

    # ── helpers ───────────────────────────────────────────

    def _transition(self, stage: Stage) -> None:
        """Record a state change."""
        self.previous_stage = self.stage
        self.stage = stage
