"""Tests for memory.topic — TopicRegistry and topic resolution."""

from __future__ import annotations

import pytest
from memory.fact import Fact
from memory.topic import Topic, TopicRegistry


# ── Seed topics (no general) ───────────────────────────────────


def test_seed_topics_no_general():
    tr = TopicRegistry()
    names = {t.name for t in tr.list_topics()}
    assert "general" not in names
    assert names == {"preference", "project", "behavior", "workflow"}


def test_seed_topics_have_definitions():
    tr = TopicRegistry()
    for t in tr.list_topics():
        assert t.definition, f"topic '{t.name}' missing definition"


# ── Topic dataclass ────────────────────────────────────────────


def test_topic_defaults():
    t = Topic(name="test", definition="testing topic")
    assert t.name == "test"
    assert t.definition == "testing topic"
    assert t.created_at is not None


def test_topic_roundtrip():
    t = Topic(name="test", definition="testing")
    d = t.to_dict()
    t2 = Topic.from_dict(d)
    assert t2.name == "test"
    assert t2.definition == "testing"


# ── resolve_topic ──────────────────────────────────────────────


def test_resolve_exact_match(topic_registry):
    r = topic_registry.resolve_topic("preference")
    assert r == ("preference", False, False)


def test_resolve_case_insensitive(topic_registry):
    r = topic_registry.resolve_topic("PREFERENCE")
    assert r == ("preference", False, False)


def test_resolve_whitespace(topic_registry):
    r = topic_registry.resolve_topic("  preference  ")
    assert r == ("preference", False, False)


def test_resolve_fuzzy_match(topic_registry):
    """Typo in topic name gets fuzzy-corrected."""
    r = topic_registry.resolve_topic("prefrences")
    assert r == ("preference", False, True)


def test_resolve_fuzzy_match_threshold(topic_registry):
    """Very different name should NOT fuzzy-match."""
    r = topic_registry.resolve_topic("completely_unrelated")
    assert r[1] is True  # is_new = True
    assert r[2] is False  # fuzzy_matched = False


def test_resolve_create_new(topic_registry):
    r = topic_registry.resolve_topic("custom_tag")
    assert r[0] == "custom_tag"
    assert r[1] is True  # is_new
    assert r[2] is False
    # Verify it persisted
    assert topic_registry.find("custom_tag") is not None


def test_resolve_empty_fallback(topic_registry):
    """Empty string falls back to 'general' for safety."""
    r = topic_registry.resolve_topic("")
    assert r[0] == "general"
    assert r[1] is True  # new topic created


# ── TopicRegistry queries ──────────────────────────────────────


def test_find_existing(topic_registry):
    t = topic_registry.find("preference")
    assert t is not None
    assert t.definition


def test_find_nonexistent(topic_registry):
    assert topic_registry.find("nonexistent") is None


def test_contains(topic_registry):
    assert "preference" in topic_registry
    assert "nonexistent" not in topic_registry


def test_list_topics_after_add(topic_registry):
    topic_registry.add("new_topic", "desc")
    names = {t.name for t in topic_registry.list_topics()}
    assert "new_topic" in names
    assert "preference" in names


def test_add_overwrite(topic_registry):
    topic_registry.add("preference", "new definition")
    assert topic_registry.find("preference").definition == "new definition"


# ── Persistence ────────────────────────────────────────────────


def test_persistence(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    p = str(d / "topics.json")

    tr1 = TopicRegistry(path=p)
    tr1.add("saved_topic", "saved definition")
    assert len(tr1.list_topics()) == 5  # 4 seeds + 1 new

    tr2 = TopicRegistry(path=p)
    assert tr2.find("saved_topic") is not None
    assert len(tr2.list_topics()) == 5


# ── list_with_counts ───────────────────────────────────────────


def test_list_with_counts_no_store(topic_registry):
    result = topic_registry.list_with_counts(fact_store=None)
    for entry in result:
        assert "name" in entry
        assert "fact_count" not in entry  # None → no counts


def test_list_with_counts_with_store(topic_registry, fact_store):
    fact_store.commit(Fact(content="a", topic="preference"))
    fact_store.commit(Fact(content="b", topic="preference"))

    result = topic_registry.list_with_counts(fact_store=fact_store)
    pref = [e for e in result if e["name"] == "preference"][0]
    assert pref["fact_count"] == 2


def test_get_definitions_text(topic_registry):
    text = topic_registry.get_definitions_text()
    assert "preference" in text
    assert "Available topics" in text


# ── Edge cases ─────────────────────────────────────────────────


def test_reload_corrupted_file(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    p = str(d / "topics.json")
    # Write garbage
    with open(p, "w") as f:
        f.write("{invalid json")
    # Should reseed without crashing
    tr = TopicRegistry(path=p)
    assert len(tr.list_topics()) == 4


def test_save_and_reload_identity(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    p = str(d / "topics.json")
    tr = TopicRegistry(path=p)
    ts1 = {t.name: t.definition for t in tr.list_topics()}
    tr2 = TopicRegistry(path=p)
    ts2 = {t.name: t.definition for t in tr2.list_topics()}
    assert ts1 == ts2
