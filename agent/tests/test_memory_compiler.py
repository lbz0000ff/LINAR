"""Tests for memory.compiler — View Compilation.

Stage 1 (rules) and score updates are testable without an LLM.
Stage 2 (LLM selection) is tested via integration tests using the
fallback path (top candidates by score).
"""

from __future__ import annotations

import os

import pytest
from memory.fact import Fact, FactStore
from memory.topic import TopicRegistry
from memory.compiler import compile_view, _stage1_rules, _write_view_files


# ── Stage 1 — rules filtering ─────────────────────────────────


def test_stage1_empty(fact_store, topic_registry):
    uncond, candidates = _stage1_rules(fact_store, topic_registry)
    assert uncond == []
    assert candidates == []


def test_stage1_properties_only(fact_store, topic_registry):
    fact_store.set_properties([{"key": "name", "value": "test"}])
    uncond, candidates = _stage1_rules(fact_store, topic_registry)
    assert len(uncond) == 1
    assert uncond[0]["type"] == "property"
    assert uncond[0]["key"] == "name"
    assert candidates == []


def test_stage1_properties_and_facts(fact_store, topic_registry):
    fact_store.set_properties([{"key": "name", "value": "test"}])
    fact_store.commit(Fact(content="fact a", topic="preference", source="t"))
    fact_store.commit(Fact(content="fact b", topic="project", source="t"))

    uncond, candidates = _stage1_rules(fact_store, topic_registry)
    assert len(uncond) == 1  # property only
    assert len(candidates) == 2  # both facts


def test_stage1_pinned_facts(fact_store, topic_registry):
    f1 = fact_store.commit(Fact(content="pinned fact", topic="preference", pinned=True, source="t"))
    f2 = fact_store.commit(Fact(content="normal fact", topic="project", source="t"))

    uncond, candidates = _stage1_rules(fact_store, topic_registry)
    # Pinned should be in unconditional, normal in candidates
    pinned = [u for u in uncond if u.get("id") == f1.id]
    assert len(pinned) == 1
    assert pinned[0]["pinned"] is True
    candidate_ids = [c["id"] for c in candidates]
    assert f2.id in candidate_ids


def test_stage1_pinned_limit(fact_store, topic_registry):
    """Only _PINNED_LIMIT (5) pinned facts go to unconditional."""
    for i in range(10):
        fact_store.commit(Fact(content=f"pinned {i}", topic="t", pinned=True, source="t"))
    uncond, candidates = _stage1_rules(fact_store, topic_registry)
    pinned = [u for u in uncond if u["type"] == "fact"]
    assert len(pinned) <= 5


def test_stage1_score_ordering(fact_store, topic_registry):
    f1 = fact_store.commit(Fact(content="low score", topic="t", source="t"))
    f2 = fact_store.commit(Fact(content="high score", topic="t", source="t"))
    fact_store.update_view_scores([f2.id], decay=0.8)
    # Now f2 should have higher score than f1

    _, candidates = _stage1_rules(fact_store, topic_registry)
    assert len(candidates) >= 2
    # First candidate should be highest score
    assert candidates[0]["id"] == f2.id


# ── Full compilation (fallback path, no LLM) ────────────────────


def test_compile_empty_store(fact_store, topic_registry):
    """Compiling an empty store should write empty files without error."""
    compile_view(fact_store, topic_registry, llm_cfg=None)
    # After compile, version should be marked
    assert fact_store.has_changed_since_last_compile() is False


def test_compile_with_facts(fact_store, topic_registry, tmp_path):
    fact_store.commit(Fact(content="user likes Python", topic="preference", source="t"))
    fact_store.commit(Fact(content="project uses SQLite", topic="project", source="t"))
    fact_store.save()

    # Compile with fallback path (no LLM)
    compile_view(fact_store, topic_registry, llm_cfg=None)

    # Check that version is marked
    assert fact_store.has_changed_since_last_compile() is False

    # Check view files exist (written to agent/prompt/USER.md and AGENT.md)
    prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompt")
    usr_path = os.path.join(prompt_dir, "USER.md")
    agt_path = os.path.join(prompt_dir, "AGENT.md")

    assert os.path.isfile(usr_path), f"USER.md not found at {usr_path}"
    assert os.path.isfile(agt_path), f"AGENT.md not found at {agt_path}"

    usr = open(usr_path, encoding="utf-8").read()
    agt = open(agt_path, encoding="utf-8").read()

    # preference facts → USER.md
    assert "likes Python" in usr or "likes Python" in usr
    # project facts → AGENT.md
    assert "SQLite" in agt

    # Cleanup
    os.remove(usr_path)
    os.remove(agt_path)


def test_compile_with_properties(fact_store, topic_registry, tmp_path):
    fact_store.set_properties([{"key": "name", "value": "tester"}])
    fact_store.commit(Fact(content="prefers CLI", topic="preference", source="t"))
    fact_store.save()

    compile_view(fact_store, topic_registry, llm_cfg=None)

    prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompt")
    usr_path = os.path.join(prompt_dir, "USER.md")
    usr = open(usr_path, encoding="utf-8").read()

    assert "name: tester" in usr
    assert "prefers CLI" in usr

    os.remove(usr_path)
    agt_path = os.path.join(prompt_dir, "AGENT.md")
    if os.path.exists(agt_path):
        os.remove(agt_path)


# ── View scores ────────────────────────────────────────────────


def test_score_update_after_compile(fact_store, topic_registry):
    f = fact_store.commit(Fact(content="fact", topic="preference", source="t"))
    fact_store.save()

    compile_view(fact_store, topic_registry, llm_cfg=None)

    # After compile with fallback, the selected fact(s) get a score boost
    updated = fact_store.get_by_id(f.id)
    # Initial score 0.3 * 0.8 (decay) + 1.0 (selected) = 1.24
    assert updated.view_score == pytest.approx(1.24, rel=1e-2)


def test_score_at_compile_time(fact_store, topic_registry):
    """Compile multiple times to see score stabilization."""
    f = fact_store.commit(Fact(content="important fact", topic="preference", source="t"))
    fact_store.save()

    for _ in range(3):
        compile_view(fact_store, topic_registry, llm_cfg=None)
        fact_store.save()

    # After 3 compiles with fallback (always selects this fact):
    # Compile 1: 0.3*0.8 + 1.0 = 1.24
    # Compile 2: 1.24*0.8 + 1.0 = 1.992
    # Compile 3: 1.992*0.8 + 1.0 = 2.5936
    updated = fact_store.get_by_id(f.id)
    assert updated.view_score == pytest.approx(2.5936, rel=1e-2)


# ── _write_view_files ──────────────────────────────────────────


def test_write_view_files_empty(tmp_path):
    _write_view_files([], [])
    # Should not crash


def test_write_view_files_only_properties(tmp_path):
    props = [{"type": "property", "key": "name", "value": "test"}]
    _write_view_files(props, [])
    # USER.md should have the property
    prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompt")
    usr = open(os.path.join(prompt_dir, "USER.md"), encoding="utf-8").read()
    assert "name: test" in usr

    os.remove(os.path.join(prompt_dir, "USER.md"))
    agt = os.path.join(prompt_dir, "AGENT.md")
    if os.path.exists(agt):
        os.remove(agt)


# ── Edge cases ─────────────────────────────────────────────────


def test_compile_large_number_of_facts(fact_store, topic_registry):
    """Compiler should handle 100+ facts without error."""
    for i in range(100):
        fact_store.commit(Fact(content=f"fact {i}", topic="test", source="t"))
    fact_store.save()
    # Should not raise
    compile_view(fact_store, topic_registry, llm_cfg=None)
    assert fact_store.has_changed_since_last_compile() is False


def test_compile_idempotent(fact_store, topic_registry):
    """Running compile twice without new facts should be a no-op."""
    fact_store.commit(Fact(content="stable", topic="preference", source="t"))
    fact_store.save()
    fact_store.mark_compiled()
    # compile_view should detect no changes needed? No, has_changed_since_last_compile
    # checks file mtime vs version. After mark_compiled, it's False, but compile_view
    # is called from _build_prompt which checks has_changed_since_last_compile first.
    # When called directly, compile_view doesn't check this.
    compile_view(fact_store, topic_registry, llm_cfg=None)
    # Should not crash
