"""Tests for memory.fact — Fact model and FactStore persistence."""

from __future__ import annotations

import json

import pytest
from memory.fact import Fact, FactStore


# ── Fact model ────────────────────────────────────────────────


def test_fact_default_id():
    """Fact without id gets an empty string default."""
    f = Fact(content="hello", topic="test")
    assert f.id == ""
    assert f.content == "hello"
    assert f.topic == "test"


def test_fact_defaults():
    """Default optional fields are set correctly."""
    f = Fact(id="f1", content="hello", topic="test")
    assert f.active is True
    assert f.supersedes is None
    assert f.view_score == 0.0
    assert f.pinned is False


def test_fact_roundtrip():
    """to_dict → from_dict preserves all fields."""
    f = Fact(id="f1", content="hello", topic="test", source="s1_t1",
             active=True, supersedes=None, view_score=0.5, pinned=True)
    d = f.to_dict()
    f2 = Fact.from_dict(d)
    assert f2.id == "f1"
    assert f2.content == "hello"
    assert f2.topic == "test"
    assert f2.view_score == 0.5
    assert f2.pinned is True


def test_fact_pinned():
    f = Fact(id="f1", content="pinned", topic="test", pinned=True)
    assert f.pinned is True


# ── FactStore — commit / query ────────────────────────────────


def test_store_empty(fact_store):
    assert fact_store.count() == 0
    assert fact_store.all() == []


def test_store_commit_basic(fact_store):
    f = Fact(content="test", topic="general")
    f2 = fact_store.commit(f)
    assert f2.id.startswith("fact_")
    assert f2.content == "test"
    assert f2.active is True
    assert f2.view_score == 0.3
    assert fact_store.count() == 1


def test_store_commit_supersede(fact_store):
    old = fact_store.commit(Fact(content="old version", topic="test"))
    new = fact_store.commit(Fact(content="new version", topic="test"), conflicting=old)
    # Old should be inactive
    assert old.active is False
    # New should link to old
    assert new.supersedes == old.id
    # Only new is active
    active = fact_store.all(active=True)
    assert len(active) == 1
    assert active[0].id == new.id


def test_store_get_by_topic(fact_store):
    fact_store.commit(Fact(content="a", topic="preference"))
    fact_store.commit(Fact(content="b", topic="preference"))
    fact_store.commit(Fact(content="c", topic="project"))
    assert len(fact_store.get_by_topic("preference")) == 2
    assert len(fact_store.get_by_topic("project")) == 1
    assert len(fact_store.get_by_topic("nonexistent")) == 0


def test_store_get_by_id(fact_store):
    f = fact_store.commit(Fact(content="find me", topic="test"))
    assert fact_store.get_by_id(f.id) is not None
    assert fact_store.get_by_id("nonexistent") is None


def test_store_count_variants(fact_store):
    f1 = fact_store.commit(Fact(content="a", topic="t"))
    fact_store.commit(Fact(content="b", topic="t"), conflicting=f1)
    assert fact_store.count(active=True) == 1
    assert fact_store.count(active=False) == 1
    assert fact_store.count(active=None) == 2


# ── FactStore — persistence ────────────────────────────────────


def test_store_save_and_reload(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    p = str(d / "fp.json")
    vp = str(d / "cv.txt")

    fs1 = FactStore(path=p, version_path=vp)
    fs1.commit(Fact(content="persist me", topic="test"))
    fs1.save()

    fs2 = FactStore(path=p, version_path=vp)
    assert fs2.count() == 1
    assert fs2.all()[0].content == "persist me"


def test_store_json_file(tmp_path):
    """Verify the on-disk JSON has the expected structure."""
    d = tmp_path / "state"
    d.mkdir()
    p = str(d / "fp.json")
    vp = str(d / "cv.txt")

    fs = FactStore(path=p, version_path=vp)
    fs.commit(Fact(content="hello", topic="test"))
    fs.save()

    with open(p) as f:
        raw = json.load(f)
    assert raw["version"] == 1
    assert raw["next_id"] == 2
    assert len(raw["facts"]) == 1
    assert raw["facts"][0]["content"] == "hello"


# ── FactStore — compile tracking ───────────────────────────────


def test_compile_tracking_initial(fact_store):
    """Fresh store without version file needs compile."""
    assert fact_store.has_changed_since_last_compile() is True


def test_compile_tracking_after_mark(fact_store):
    fact_store.commit(Fact(content="x", topic="t"))
    fact_store.save()
    assert fact_store.has_changed_since_last_compile() is True
    fact_store.mark_compiled()
    assert fact_store.has_changed_since_last_compile() is False


def test_compile_tracking_new_commit_after_mark(fact_store):
    fact_store.commit(Fact(content="x", topic="t"))
    fact_store.save()
    fact_store.mark_compiled()
    assert fact_store.has_changed_since_last_compile() is False
    fact_store.commit(Fact(content="y", topic="t"))
    fact_store.save()
    assert fact_store.has_changed_since_last_compile() is True


# ── FactStore — view scores ────────────────────────────────────


def test_view_score_decay_and_boost(fact_store):
    f1 = fact_store.commit(Fact(content="a", topic="t"))
    f2 = fact_store.commit(Fact(content="b", topic="t"))
    assert f1.view_score == 0.3
    assert f2.view_score == 0.3

    fact_store.update_view_scores([f1.id], decay=0.8)
    assert fact_store.get_by_id(f1.id).view_score == pytest.approx(1.24)  # 0.3*0.8 + 1.0
    assert fact_store.get_by_id(f2.id).view_score == pytest.approx(0.24)  # 0.3*0.8


def test_view_score_decay_only_active(fact_store):
    f1 = fact_store.commit(Fact(content="a", topic="t"))
    fact_store.commit(Fact(content="b", topic="t"), conflicting=f1)
    fact_store.update_view_scores([], decay=0.8)
    # Inactive facts should not have their score decayed (or it doesn't matter)
    # but the active one should decay
    assert fact_store.get_by_id(f1.id).view_score == 0.3  # inactive → not updated
    active_facts = fact_store.all(active=True)
    assert len(active_facts) == 1
    assert active_facts[0].view_score == 0.24  # 0.3 * 0.8


# ── Properties ────────────────────────────────────────────────


def test_properties(fact_store):
    assert fact_store.get_properties() == []
    fact_store.set_properties([{"key": "name", "value": "test"}])
    assert fact_store.get_properties() == [{"key": "name", "value": "test"}]


# ── FactStore — edge cases ─────────────────────────────────────


def test_store_commit_empty_content(fact_store):
    f = fact_store.commit(Fact(content="", topic="t"))
    assert f.id.startswith("fact_")


def test_store_commit_same_id_twice(fact_store):
    """Commit assigns unique IDs regardless of input."""
    f1 = fact_store.commit(Fact(content="a", topic="t"))
    f2 = fact_store.commit(Fact(content="b", topic="t"))
    assert f1.id != f2.id


def test_store_save_twice(fact_store):
    """Saving multiple times shouldn't lose data."""
    fact_store.commit(Fact(content="a", topic="t"))
    fact_store.save()
    fact_store.save()  # second save is a no-op (not dirty)
    assert fact_store.count() == 1
