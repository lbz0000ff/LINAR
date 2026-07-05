"""Memory system evaluation — fact store, topic registry, compilation."""

from __future__ import annotations

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))


@pytest.mark.anyio
async def test_fact_store_basic():
    """Test FactStore commit and retrieval."""
    from memory.fact import Fact, FactStore

    store = FactStore()
    fact = Fact(content="User likes Python", topic="preference")
    store.commit(fact)

    facts = store.all(active=True)
    texts = [f.content for f in facts]
    assert "User likes Python" in texts


@pytest.mark.anyio
async def test_fact_topic_filter():
    """Test filtering facts by topic."""
    from memory.fact import Fact, FactStore

    store = FactStore()
    store.commit(Fact(content="User likes Python", topic="preference"))
    store.commit(Fact(content="LINAR is an agent", topic="project"))

    pref_facts = store.get_by_topic("preference")
    assert any(f.content == "User likes Python" for f in pref_facts)
    assert any(f.topic == "preference" for f in pref_facts)


@pytest.mark.anyio
async def test_fact_deactivation():
    """Test fact deactivation (superseding old facts)."""
    from memory.fact import Fact, FactStore

    store = FactStore()
    f1 = store.commit(Fact(content="User likes Python", topic="preference"))
    store.commit(Fact(content="User loves Rust", topic="preference"),
                 conflicting=f1)

    active = store.all(active=True)
    active_texts = [f.content for f in active]
    assert "User likes Python" not in active_texts  # superseded
    assert "User loves Rust" in active_texts


@pytest.mark.anyio
async def test_topic_registry():
    """Test topic listing."""
    from memory.topic import TopicRegistry

    tr = TopicRegistry()
    names = {t.name for t in tr.list_topics()}
    assert "preference" in names
    assert "project" in names


@pytest.mark.anyio
async def test_view_compilation():
    """Test compilation detects changes."""
    from memory.fact import Fact, FactStore

    store = FactStore()
    count_before = store.count(active=True)
    store.commit(Fact(content="Test fact", topic="preference"))
    # After commit, fact count should increase
    assert store.count(active=True) == count_before + 1
