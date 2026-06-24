"""Tests for state_machine — FSM transition validation."""

from __future__ import annotations

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.state_machine import Stage, stage_label, StateMachine, _TRANSITION_TABLE


class TestStageLabel:
    def test_lower_case(self):
        assert stage_label(Stage.SKILL_LOAD) == "skill_load"
        assert stage_label(Stage.COMPLETE) == "complete"


class TestTransitionTable:
    def test_all_stages_covered(self):
        """Every Stage value appears as a key in the table."""
        for s in Stage:
            assert s in _TRANSITION_TABLE, f"{s} missing from table"

    def test_all_targets_are_valid_stages(self):
        """Every target in the table is a real Stage value."""
        for src, targets in _TRANSITION_TABLE.items():
            for t in targets:
                assert isinstance(t, Stage), f"{src}→{t}: not a Stage"

    def test_error_is_terminal(self):
        """ERROR has no legal outgoing transitions."""
        assert _TRANSITION_TABLE[Stage.ERROR] == set()

    def test_complete_to_idle(self):
        """COMPLETE → IDLE is the only way out of COMPLETE."""
        assert Stage.IDLE in _TRANSITION_TABLE[Stage.COMPLETE]


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.current == Stage.IDLE
        assert sm.previous is None

    def test_can_transition_allows_valid(self):
        sm = StateMachine()
        assert sm.can_transition(Stage.INGEST) is True
        assert sm.can_transition(Stage.SKILL_LOAD) is True
        assert sm.can_transition(Stage.PROCESS) is False  # IDLE→PROCESS illegal

    @pytest.mark.anyio
    async def test_valid_transition(self):
        sm = StateMachine()
        await sm.transition(Stage.INGEST)
        assert sm.current == Stage.INGEST
        assert sm.previous == Stage.IDLE

    @pytest.mark.anyio
    async def test_invalid_transition_raises(self):
        sm = StateMachine()
        await sm.transition(Stage.INGEST)  # IDLE→INGEST valid
        with pytest.raises(ValueError, match="INGEST"):
            await sm.transition(Stage.INGEST)  # INGEST→INGEST illegal
        # ERROR is terminal → can't leave it
        await sm.transition(Stage.PROCESS)
        await sm.transition(Stage.ERROR)
        with pytest.raises(ValueError):
            await sm.transition(Stage.IDLE)  # ERROR→IDLE illegal

    @pytest.mark.anyio
    async def test_on_transition_callback(self):
        events = []

        async def track(prev, cur):
            events.append((prev.name, cur.name))

        sm = StateMachine(on_transition=track)
        await sm.transition(Stage.INGEST)
        await sm.transition(Stage.PROCESS)

        assert events == [("IDLE", "INGEST"), ("INGEST", "PROCESS")]

    @pytest.mark.anyio
    async def test_skill_abort_path(self):
        """SKILL_LOAD → COMPLETE is valid (fork-agent creation failed)."""
        sm = StateMachine()
        await sm.transition(Stage.SKILL_LOAD)
        assert sm.can_transition(Stage.COMPLETE) is True
        await sm.transition(Stage.COMPLETE)
        assert sm.current == Stage.COMPLETE

    def test_can_query_without_transitioning(self):
        sm = StateMachine()
        assert sm.can_transition(Stage.INGEST) is True
        assert sm.current == Stage.IDLE  # didn't change
