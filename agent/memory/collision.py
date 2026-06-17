"""Collision detection — Level 0 (difflib-based, zero-dependency).

Compares a candidate fact against the existing facts in the same topic
to classify it as one of::

    Duplicate  — same meaning → discard
    Extends    — more complete version → supersede old
    Conflict   — different direction on same subject → supersede old
    NewFact    — unrelated → write fresh
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.fact import Fact


# ---------------------------------------------------------------------------
# Result hierarchy
# ---------------------------------------------------------------------------


@dataclass
class CollisionResult:
    """Base class for collision outcomes."""
    existing: "Fact | None" = None


@dataclass
class Duplicate(CollisionResult):
    """Exact or near-exact duplicate — discard the new candidate."""

    ratio: float = 0.0


@dataclass
class Extends(CollisionResult):
    """New candidate is a more complete version of an existing fact.

    The old fact should be superseded by the new one.
    """
    ratio: float = 0.0


@dataclass
class Conflict(CollisionResult):
    """Different factual direction on the same subject.

    The old fact should be superseded by the new one
    (the superseded chain preserves the old version for audit).
    """
    ratio: float = 0.0


@dataclass
class NewFact(CollisionResult):
    """No meaningful overlap — commit fresh."""
    pass


# ---------------------------------------------------------------------------
# Detect
# ---------------------------------------------------------------------------


def detect(
    content: str,
    candidates: list["Fact"],
    threshold_exact: float = 0.85,
    threshold_extends: float = 0.60,
) -> CollisionResult:
    """Classify *content* against a list of existing fact *candidates*.

    All candidates are assumed to be from the *same* topic (the caller
    is responsible for topic filtering).  This keeps the comparison
    cheap — typically 20-50 candidates.

    Returns one of ``Duplicate``, ``Extends``, ``Conflict``, ``NewFact``.
    """
    norm = content.lower().strip()
    if not norm:
        return NewFact()

    best: "Fact | None" = None
    best_ratio = 0.0
    best_coverage = 0.0

    for fact in candidates:
        fnorm = fact.content.lower().strip()
        if not fnorm:
            continue

        # Exact match shortcut
        if fnorm == norm:
            return Duplicate(existing=fact, ratio=1.0)

        ratio = difflib.SequenceMatcher(None, norm, fnorm).ratio()
        shorter = norm if len(norm) <= len(fnorm) else fnorm
        longer = fnorm if len(norm) <= len(fnorm) else norm
        coverage = len(shorter) / len(longer) if longer else 0

        if ratio > best_ratio:
            best_ratio = ratio
            best_coverage = coverage
            best = fact

    if best is None:
        return NewFact()

    if best_ratio >= threshold_exact:
        return Duplicate(existing=best, ratio=best_ratio)

    if best_ratio >= threshold_extends:
        if best_coverage > 0.85:
            return Extends(existing=best, ratio=best_ratio)
        # Sufficient ratio but poor coverage → different direction
        return Conflict(existing=best, ratio=best_ratio)

    return NewFact()
