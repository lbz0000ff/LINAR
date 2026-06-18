"""Tests for memory.extractor — scheduling and window building.

Note: The actual LLM extraction call is tested via integration tests.
These unit tests focus on the scheduling logic and window construction
that don't require an LLM.
"""

from __future__ import annotations

import json
import os

import pytest
from memory.extractor import should_extract, _build_window


# ── should_extract scheduling ──────────────────────────────────


def test_should_extract_no_state():
    """Without state defaults, should_extract returns False (current_round=0)."""
    assert should_extract(state=None, current_round=0) is False


def test_should_extract_first_time():
    """With only 1 round, should NOT extract (min interval is 8)."""
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 0},
        current_round=1,
    ) is False


def test_should_extract_exact_interval():
    """At exactly min_interval rounds, should extract."""
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 0},
        current_round=8,
    ) is True


def test_should_extract_after_interval():
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 0},
        current_round=12,
    ) is True


def test_should_extract_max_interval_safety():
    """After max_interval (20), force extraction regardless of empty count."""
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 5},
        current_round=20,
    ) is True


def test_should_extract_skip_empty():
    """After consecutive_empty >= 2, skip if not at max_interval."""
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 2},
        current_round=12,
    ) is False


def test_should_extract_one_empty():
    """consecutive_empty=1 should still extract."""
    assert should_extract(
        state={"last_extraction_round": 0, "current_interval": 8, "consecutive_empty": 1},
        current_round=10,
    ) is True


def test_should_extract_missing_keys():
    """Missing state keys should use defaults safely."""
    assert should_extract(state={}, current_round=0) is False
    assert should_extract(state={}, current_round=20) is True


# ── _build_window ──────────────────────────────────────────────


def _msg(role: str, content: str, conversation_round: int = 1, tool_name: str = ""):
    return {"role": role, "content": content, "conversation_round": conversation_round, "tool_name": tool_name}


def test_build_window_empty():
    assert _build_window([], 0, 10) == ""


def test_build_window_excludes_old_rounds():
    msgs = [
        _msg("user", "old", conversation_round=1),
        _msg("user", "current", conversation_round=5),
    ]
    result = _build_window(msgs, start_round=3, end_round=10)
    assert "old" not in result
    assert "current" in result


def test_build_window_excludes_future_rounds():
    msgs = [
        _msg("user", "current", conversation_round=5),
        _msg("user", "future", conversation_round=15),
    ]
    result = _build_window(msgs, start_round=0, end_round=10)
    assert "current" in result
    assert "future" not in result


def test_build_window_user_and_assistant():
    msgs = [
        _msg("user", "hello", conversation_round=1),
        _msg("agent", "hi there", conversation_round=1),
    ]
    result = _build_window(msgs, start_round=0, end_round=10)
    assert "User: hello" in result
    assert "Assistant: hi there" in result


def test_build_window_tool_calls():
    msgs = [
        _msg("user", "run tool", conversation_round=1),
        _msg("tool", "result data", conversation_round=1, tool_name="test_tool"),
    ]
    result = _build_window(msgs, start_round=0, end_round=10)
    assert "User: run tool" in result
    assert "[Tool test_tool: result" in result


def test_build_window_truncates_long_content():
    long_content = "a" * 2000
    msgs = [_msg("user", long_content, conversation_round=1)]
    result = _build_window(msgs, start_round=0, end_round=10)
    # Should truncate to 1500 chars
    assert len(result) < 1600


def test_build_window_start_round_boundary():
    """Messages at exactly start_round should be excluded."""
    msgs = [
        _msg("user", "old", conversation_round=5),
        _msg("user", "new", conversation_round=6),
    ]
    result = _build_window(msgs, start_round=5, end_round=10)
    assert "old" not in result
    assert "new" in result


def test_build_window_ordered():
    """Messages should appear in original order."""
    msgs = [
        _msg("user", "first", conversation_round=1),
        _msg("agent", "second", conversation_round=1),
        _msg("user", "third", conversation_round=2),
    ]
    result = _build_window(msgs, start_round=0, end_round=10)
    first = result.index("first")
    second = result.index("second")
    third = result.index("third")
    assert first < second < third


def test_build_window_skips_empty_content():
    msgs = [
        _msg("user", "has content", conversation_round=1),
        _msg("user", "", conversation_round=2),
    ]
    result = _build_window(msgs, start_round=0, end_round=10)
    assert "has content" in result
