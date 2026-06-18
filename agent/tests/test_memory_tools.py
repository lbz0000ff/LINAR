"""Tests for memory system tools — Tool_Remember, Tool_RecallFact, etc.

These tools work directly with FactStore and TopicRegistry, so we
test them with temporary storage paths.
"""

from __future__ import annotations

import os

import pytest
from memory.fact import FactStore
from memory.topic import TopicRegistry

# Import tools (they use default FactStore/TopicRegistry paths internally,
# so we need to use temporary paths via environment or patching)
from tool.basic_tools.tool_memory import (
    Tool_Remember,
    Tool_RecallFact,
    Tool_RecallTopic,
    Tool_GetTopicList,
)


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Point FactStore and TopicRegistry at temp dirs by monkeypatching paths."""
    import memory.fact as mf
    import memory.topic as mt

    d = tmp_path / "state"
    d.mkdir()

    # Monkey-patch the module-level paths so tools use temp files
    old_fact_path = mf._FACT_POOL_PATH
    old_version_path = mf._VERSION_PATH
    old_topic_path = mt._TOPICS_PATH

    mf._FACT_POOL_PATH = str(d / "fact_pool.json")
    mf._VERSION_PATH = str(d / "compiled_version.txt")
    mt._TOPICS_PATH = str(d / "topics.json")

    yield

    mf._FACT_POOL_PATH = old_fact_path
    mf._VERSION_PATH = old_version_path
    mt._TOPICS_PATH = old_topic_path


# ── Tool_Remember ──────────────────────────────────────────────


def test_remember_new_topic():
    t = Tool_Remember()
    result = t.execute(content="user likes Python", topic="preference")
    assert "stored" in result.lower() or "Created" in result
    assert "fact_" in result
    assert "preference" in result


def test_remember_fuzzy_match():
    t = Tool_Remember()
    t.execute(content="user likes Python", topic="preference")
    # Typo should fuzzy-match to "preference"
    result = t.execute(content="user likes Rust", topic="prefrences")
    assert "matched existing" in result
    assert "preference" in result


def test_remember_creates_new_topic():
    t = Tool_Remember()
    result = t.execute(content="custom vocabulary", topic="custom_vocab")
    assert "Created new topic" in result
    assert "custom_vocab" in result


def test_remember_duplicate():
    t = Tool_Remember()
    t.execute(content="unique fact", topic="preference")
    result = t.execute(content="unique fact", topic="preference")
    assert "Already exists" in result


def test_remember_updates_fact():
    t = Tool_Remember()
    t.execute(content="old version", topic="preference")
    # Extending content should trigger Extends → "updated"
    result = t.execute(content="old version with additional details", topic="preference")
    assert "updated" in result or "conflict" in result or "stored" in result


def test_remember_very_long_content():
    t = Tool_Remember()
    long_content = "word " * 500
    result = t.execute(content=long_content, topic="preference")
    # Should not crash
    assert "stored" in result.lower() or "Created" in result


# ── Tool_RecallFact ────────────────────────────────────────────


def test_recall_fact_found():
    t = Tool_Remember()
    t.execute(content="prefers CLI tools", topic="preference")
    t.execute(content="likes VSCode editor", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="CLI")
    assert "prefers CLI" in result
    assert "VSCode" not in result


def test_recall_fact_not_found():
    s = Tool_RecallFact()
    result = s.execute(query="nonexistent")
    assert "No facts found" in result


def test_recall_fact_empty_query():
    s = Tool_RecallFact()
    result = s.execute(query="")
    assert "Error" in result


def test_recall_fact_limit():
    """Limit should cap the number of results."""
    t = Tool_Remember()
    for i in range(10):
        t.execute(content=f"keyword fact {i}", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="keyword", limit=3)
    # Should have at most 3 "fact" lines
    assert result.count("fact_") <= 3


def test_recall_fact_case_insensitive():
    t = Tool_Remember()
    t.execute(content="Python programming", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="python")
    assert "Python" in result or "python" in result


# ── Tool_RecallTopic ───────────────────────────────────────────


def test_recall_topic_found():
    t = Tool_Remember()
    t.execute(content="likes Python", topic="preference")
    t.execute(content="uses SQLite", topic="project")

    rt = Tool_RecallTopic()
    result = rt.execute(topic="preference")
    assert "likes Python" in result
    assert "SQLite" not in result


def test_recall_topic_empty():
    rt = Tool_RecallTopic()
    result = rt.execute(topic="nonexistent")
    assert "No facts" in result


def test_recall_topic_fuzzy():
    """Topic name should be fuzzy-resolved."""
    t = Tool_Remember()
    t.execute(content="test data", topic="preference")
    rt = Tool_RecallTopic()
    result = rt.execute(topic="prefrences")
    assert "test data" in result


def test_recall_topic_active_only():
    """active_only=True should only show active facts."""
    t = Tool_Remember()
    t.execute(content="active fact", topic="preference")
    rt = Tool_RecallTopic()
    result = rt.execute(topic="preference", active_only=True)
    assert "active fact" in result


# ── Tool_GetTopicList ──────────────────────────────────────────


def test_get_topic_list():
    g = Tool_GetTopicList()
    result = g.execute()
    assert "preference" in result
    assert "project" in result
    assert "behavior" in result
    assert "workflow" in result


def test_get_topic_list_with_facts():
    t = Tool_Remember()
    t.execute(content="fact in preference", topic="preference")
    t.execute(content="fact in project", topic="project")

    g = Tool_GetTopicList()
    result = g.execute()
    assert "(1 facts)" in result


def test_get_topic_list_no_general():
    g = Tool_GetTopicList()
    result = g.execute()
    assert "general" not in result


# ── Tool parameter validation ──────────────────────────────────


def test_remember_missing_params():
    t = Tool_Remember()
    # Calling with no args should be handled
    result = t.execute(content="", topic="")
    assert "Error" in result or "stored" in result or "general" in result


def test_tool_schemas_complete():
    """All tools should have name, description, and tool_schema."""
    for tool in [Tool_Remember(), Tool_RecallFact(), Tool_RecallTopic(), Tool_GetTopicList()]:
        assert tool.name
        assert tool.description
        assert tool.tool_schema
        assert tool.tool_schema["name"]
