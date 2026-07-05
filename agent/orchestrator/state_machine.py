"""Finite state machine with explicit transition guards.

Pure Python — no dependencies on agent, hooks, or LINAR infrastructure.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum, auto


# ── Stages ──────────────────────────────────────────────────────────────────

class Stage(Enum):
    IDLE = auto()
    INGEST = auto()
    PROCESS = auto()
    SKILL_LOAD = auto()
    SKILL_EXEC = auto()
    SKILL_UNLOAD = auto()
    COMPLETE = auto()
    ERROR = auto()


_STAGE_LABELS = {s: s.name.lower() for s in Stage}


def stage_label(stage: Stage) -> str:
    """Return lower-case label (e.g. ``"dag_execute"``)."""
    return _STAGE_LABELS.get(stage, stage.name.lower())


# ── Transition table ────────────────────────────────────────────────────────

_TRANSITION_TABLE: dict[Stage, set[Stage]] = {
    Stage.IDLE:        {Stage.INGEST, Stage.SKILL_LOAD},
    Stage.INGEST:      {Stage.PROCESS},
    Stage.PROCESS:     {Stage.COMPLETE, Stage.ERROR},
    Stage.SKILL_LOAD:  {Stage.SKILL_EXEC, Stage.SKILL_UNLOAD, Stage.COMPLETE, Stage.ERROR},
    Stage.SKILL_EXEC:  {Stage.SKILL_UNLOAD, Stage.ERROR},
    Stage.SKILL_UNLOAD:{Stage.COMPLETE, Stage.ERROR},
    Stage.COMPLETE:    {Stage.IDLE, Stage.ERROR},
    Stage.ERROR:       set(),
}

# Notes:
# - create_plan is a blocking tool call — DAG execution happens inside the tool.
#   No FSM transitions for PLAN/DAG_EXECUTE needed.
# - SKILL_LOAD → COMPLETE: graceful abort when fork-agent creation fails.
# - ERROR is a terminal state — no legal exits.


# ── StateMachine ────────────────────────────────────────────────────────────

class StateMachine:
    """Validated FSM with optional async transition callback.

    Usage::

        async def on_trans(prev: Stage, cur: Stage) -> None:
            await hook_factory.state_enter(cur, prev)

        sm = StateMachine(on_transition=on_trans)
        await sm.transition(Stage.INGEST)
    """

    __slots__ = ("_stage", "_previous", "_on_transition")

    def __init__(
        self,
        on_transition: Callable[[Stage, Stage], Awaitable[None]] | None = None,
    ) -> None:
        self._stage: Stage = Stage.IDLE
        self._previous: Stage | None = None
        self._on_transition = on_transition

    @property
    def current(self) -> Stage:
        return self._stage

    @property
    def previous(self) -> Stage | None:
        return self._previous

    def can_transition(self, target: Stage) -> bool:
        """Return ``True`` if **target** is legal from the current stage."""
        allowed = _TRANSITION_TABLE.get(self._stage, set())
        return target in allowed

    async def transition(self, target: Stage) -> None:
        """Validate and apply **target**; await callback if set.

        Raises ``ValueError`` on illegal transitions.
        """
        if not self.can_transition(target):
            prev_name = self._stage.name
            target_name = target.name
            allowed = [s.name for s in _TRANSITION_TABLE.get(self._stage, set())]
            raise ValueError(
                f"Invalid FSM transition: {prev_name} → {target_name}. "
                f"Allowed: {allowed or '(none — terminal state)'}"
            )

        prev = self._stage
        self._previous = prev
        self._stage = target

        if self._on_transition is not None:
            await self._on_transition(prev, target)
