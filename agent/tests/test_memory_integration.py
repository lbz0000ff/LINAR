"""Integration tests for the memory system — full end-to-end scenarios.

Tests cover:
- Persistence across "restarts" (save → reload)
- View compilation output file correctness
- Full remember → recall → compile → load cycle
- Data consistency after multiple operations
"""

from __future__ import annotations

import json
import os

import pytest
from memory.fact import Fact, FactStore
from memory.topic import TopicRegistry
from memory.compiler import compile_view


# ── Integration: persistence across restarts ────────────────────


def test_persistence_remember_after_reload(tmp_path):
    """Simulate: session 1 writes facts → session 2 loads them."""
    d = tmp_path / "state"
    d.mkdir()

    # "Session 1"
    store1 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    store1.commit(Fact(content="fact from session 1", topic="preference", source="test"))
    store1.save()

    # "Session 2" — reload
    store2 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    assert store2.count() == 1
    assert store2.all()[0].content == "fact from session 1"


def test_persistence_supersede_chain(tmp_path):
    """Supersede relationship survives a reload."""
    d = tmp_path / "state"
    d.mkdir()

    store1 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    old = store1.commit(Fact(content="v1", topic="t", source="test"))
    store1.save()

    store2 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    old2 = store2.get_by_id(old.id)
    new = store2.commit(Fact(content="v2", topic="t", source="test"), conflicting=old2)
    store2.save()

    store3 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    assert store3.get_by_id(old.id).active is False
    assert store3.get_by_id(new.id).active is True
    assert store3.get_by_id(new.id).supersedes == old.id


def test_persistence_topic_created(tmp_path):
    """New topic created in one session is available in the next."""
    d = tmp_path / "state"
    d.mkdir()

    tr1 = TopicRegistry(path=str(d / "topics.json"))
    tr1.add("custom_topic", "custom definition")
    assert len(tr1.list_topics()) == 5

    tr2 = TopicRegistry(path=str(d / "topics.json"))
    assert tr2.find("custom_topic") is not None
    assert tr2.find("custom_topic").definition == "custom definition"


# ── Integration: View compilation ──────────────────────────────


def test_compile_view_output_split(tmp_path):
    """Verify preference/general facts → USER.md, project/behavior → AGT.md."""
    d = tmp_path / "state"
    d.mkdir()
    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    tr = TopicRegistry(path=str(d / "topics.json"))

    store.commit(Fact(content="user fact", topic="preference", source="t"))
    store.commit(Fact(content="project fact", topic="project", source="t"))
    store.commit(Fact(content="behavior fact", topic="behavior", source="t"))
    store.save()

    # We need to use the real prompt dir since compiler writes there
    compile_view(store, tr, llm_cfg=None)

    prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompt")
    usr = open(os.path.join(prompt_dir, "USER.md"), encoding="utf-8").read()
    agt = open(os.path.join(prompt_dir, "AGENT.md"), encoding="utf-8").read()

    assert "user fact" in usr
    assert "project fact" in agt
    assert "behavior fact" in agt
    assert "user fact" not in agt
    assert "project fact" not in usr

    os.remove(os.path.join(prompt_dir, "USER.md"))
    os.remove(os.path.join(prompt_dir, "AGENT.md"))


def test_compile_view_correct_score_decay(tmp_path):
    """After compile, view_score decays and selected facts get boost."""
    d = tmp_path / "state"
    d.mkdir()
    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    tr = TopicRegistry(path=str(d / "topics.json"))

    f1 = store.commit(Fact(content="fact one", topic="preference", source="t"))
    store.save()

    compile_view(store, tr, llm_cfg=None)

    # After compile with fallback: f1 is always selected
    # 0.3 * 0.8 + 1.0 = 1.24
    assert store.get_by_id(f1.id).view_score == pytest.approx(1.24, rel=1e-2)


# ── Integration: full cycle ────────────────────────────────────


def test_full_cycle_fact_pool_json(tmp_path):
    """Write facts → verify fact_pool.json on disk is valid JSON with correct data."""
    d = tmp_path / "state"
    d.mkdir()
    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))

    store.commit(Fact(content="fact A", topic="preference", source="t"))
    store.commit(Fact(content="fact B", topic="project", source="t"))
    store.save()

    with open(str(d / "fp.json"), encoding="utf-8") as f:
        raw = json.load(f)

    assert raw["version"] == 1
    assert raw["next_id"] == 3
    assert len(raw["facts"]) == 2
    contents = {fact["content"] for fact in raw["facts"]}
    assert "fact A" in contents
    assert "fact B" in contents


def test_full_cycle_properties(tmp_path):
    """Properties survive save/reload."""
    d = tmp_path / "state"
    d.mkdir()
    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))

    store.set_properties([{"key": "name", "value": "test_user"}])
    store.save()

    store2 = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    assert store2.get_properties() == [{"key": "name", "value": "test_user"}]


# ── Integration: edge cases ────────────────────────────────────


def test_empty_fact_pool_no_crash(tmp_path):
    """Missing or empty fact_pool.json should not crash the system."""
    d = tmp_path / "state"
    d.mkdir()

    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    assert store.count() == 0


def test_corrupted_fact_pool_no_crash(tmp_path):
    """Corrupted JSON should not crash — starts empty."""
    d = tmp_path / "state"
    d.mkdir()
    fp = str(d / "fp.json")
    with open(fp, "w") as f:
        f.write("{corrupted json")

    store = FactStore(path=fp, version_path=str(d / "cv.txt"))
    assert store.count() == 0


def test_resolve_topic_persistent_across_sessions(tmp_path):
    """Fuzzy-matched topic in session 1 should be available in session 2."""
    d = tmp_path / "state"
    d.mkdir()

    tr1 = TopicRegistry(path=str(d / "topics.json"))
    resolved, is_new, fuzzy = tr1.resolve_topic("prefrences")
    assert resolved == "preference"
    assert fuzzy is True

    tr2 = TopicRegistry(path=str(d / "topics.json"))
    assert tr2.find("preference") is not None
    # No new topic should have been created
    assert len(tr2.list_topics()) == 4


def test_compile_with_pinned_and_properties(tmp_path):
    """Pinned facts and properties always appear in compiled View."""
    d = tmp_path / "state"
    d.mkdir()
    store = FactStore(path=str(d / "fp.json"), version_path=str(d / "cv.txt"))
    tr = TopicRegistry(path=str(d / "topics.json"))

    store.set_properties([{"key": "language", "value": "zh-CN"}])
    store.commit(Fact(content="pinned fact", topic="preference", pinned=True, source="t"))
    store.commit(Fact(content="normal fact", topic="preference", source="t"))
    store.save()

    compile_view(store, tr, llm_cfg=None)

    prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompt")
    usr = open(os.path.join(prompt_dir, "USER.md"), encoding="utf-8").read()

    assert "language: zh-CN" in usr
    assert "pinned fact" in usr
    assert "normal fact" in usr

    os.remove(os.path.join(prompt_dir, "USER.md"))
    agt = os.path.join(prompt_dir, "AGENT.md")
    if os.path.exists(agt):
        os.remove(agt)
