"""Tests for memory.collision — Level 0 difflib collision detection."""

from __future__ import annotations

import pytest
from memory.fact import Fact
from memory.collision import (
    detect,
    Duplicate,
    Extends,
    Conflict,
    NewFact,
)


def make_fact(content: str, topic: str = "test") -> Fact:
    return Fact(id="x", content=content, topic=topic, active=True)


CANDIDATES = [
    make_fact("user prefers Python"),
    make_fact("project uses SQLite for storage"),
    make_fact("agent uses topic-based organization"),
]


# ── Duplicate ──────────────────────────────────────────────────


def test_exact_duplicate():
    r = detect("user prefers Python", CANDIDATES)
    assert isinstance(r, Duplicate)
    assert r.existing is not None
    assert r.ratio == 1.0


def test_case_difference():
    r = detect("User Prefers Python", CANDIDATES)
    assert isinstance(r, Duplicate)


def test_whitespace_duplicate():
    r = detect("  user prefers  python  ", CANDIDATES)
    assert isinstance(r, Duplicate)
    assert r.ratio >= 0.85


def test_close_but_not_exact():
    """High similarity (>0.85) but not exact."""
    r = detect("user prefers python", CANDIDATES)
    assert isinstance(r, Duplicate)
    assert r.ratio >= 0.85


# ── Extends ────────────────────────────────────────────────────


def test_extension_new_info():
    """New content contains old content plus additional info."""
    r = detect("project uses SQLite for storage and indexing", CANDIDATES)
    assert isinstance(r, (Extends, Conflict))
    assert r.existing is not None


def test_extension_subset():
    """Old content is a superset of new content."""
    r = detect("project uses SQLite", CANDIDATES)
    assert isinstance(r, (Extends, Conflict))


# ── Conflict ───────────────────────────────────────────────────


def test_conflict_different_direction():
    """Same topic, different position."""
    r = detect("user prefers Java for backend", CANDIDATES)
    assert isinstance(r, (Conflict, Extends))


# ── NewFact ────────────────────────────────────────────────────


def test_completely_unrelated():
    r = detect("the sky is blue", CANDIDATES)
    assert isinstance(r, NewFact)


def test_empty_content():
    r = detect("", CANDIDATES)
    assert isinstance(r, NewFact)


def test_no_candidates():
    r = detect("something", [])
    assert isinstance(r, NewFact)


# ── Edge cases ─────────────────────────────────────────────────


def test_single_character():
    r = detect("a", CANDIDATES)
    assert isinstance(r, NewFact)


def test_very_long_content():
    long = "word " * 200 + "Python"
    r = detect(long, CANDIDATES)
    # With 200+ extra words vs "user prefers Python", ratio should be very low
    assert isinstance(r, NewFact)


def test_unicode_content():
    r = detect("用户偏好使用 Python", CANDIDATES)
    assert isinstance(r, NewFact)


def test_chinese_duplicate():
    candidates = [make_fact("用户偏好使用 Python")]
    r = detect("用户偏好使用 Python", candidates)
    assert isinstance(r, Duplicate)


# ── Threshold edge cases ───────────────────────────────────────


def test_threshold_boundary_duplicate():
    """Exactly at the exact threshold boundary."""
    c = [make_fact("abc" * 10)]
    r = detect("ABC" * 10, c)
    # Case-insensitive: should match exactly since we lower()
    assert isinstance(r, Duplicate)


def test_threshold_floating_point():
    """Threshold comparisons should handle floating point."""
    candidates = [
        make_fact("user prefers Python for data processing and analysis"),
    ]
    r = detect("user prefers Python for data processing", candidates)
    assert isinstance(r, (Extends, Conflict, Duplicate))
