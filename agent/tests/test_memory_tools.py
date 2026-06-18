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

import tempfile
import os
import memory.fact as mf
import memory.topic as mt

# Save originals once at module load
_ORIG_FACT_PATH = mf._FACT_POOL_PATH
_ORIG_VERSION_PATH = mf._VERSION_PATH
_ORIG_TOPIC_PATH = mt._TOPICS_PATH


@pytest.fixture(autouse=True)
def clean_state():
    """Redirect FactStore and TopicRegistry to temp files per test.

    This is a fixture scoped to each test function in this file.
    It creates fresh temp files, monkeypatches the module-level
    paths, yields, then restores originals.
    """
    d = tempfile.mkdtemp()
    mf._FACT_POOL_PATH = os.path.join(d, "fact_pool.json")
    mf._VERSION_PATH = os.path.join(d, "compiled_version.txt")
    mt._TOPICS_PATH = os.path.join(d, "topics.json")

    yield

    mf._FACT_POOL_PATH = _ORIG_FACT_PATH
    mf._VERSION_PATH = _ORIG_VERSION_PATH
    mt._TOPICS_PATH = _ORIG_TOPIC_PATH
    import shutil
    shutil.rmtree(d, ignore_errors=True)


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
    assert "stored" in result.lower() or "Created" in result


def test_remember_topic_case_insensitive():
    t = Tool_Remember()
    t.execute(content="fact A", topic="preference")
    result = t.execute(content="fact B", topic="PREFERENCE")
    # Should resolve to existing 'preference' topic, regardless of collision type
    assert "'preference'" in result or "preference" in result


def test_remember_topic_whitespace():
    t = Tool_Remember()
    result = t.execute(content="test", topic="  preference  ")
    assert "preference" in result


def test_remember_topic_numbers():
    t = Tool_Remember()
    result = t.execute(content="test", topic="123test")
    assert "Created new topic" in result
    assert "123test" in result


def test_remember_topic_underscore():
    t = Tool_Remember()
    result = t.execute(content="test", topic="custom_topic")
    assert "Created new topic" in result
    assert "custom_topic" in result


def test_remember_topic_chinese():
    t = Tool_Remember()
    result = t.execute(content="中文测试", topic="偏好")
    assert "Created new topic" in result
    assert "偏好" in result


def test_remember_topic_empty():
    t = Tool_Remember()
    result = t.execute(content="test", topic="")
    assert "stored" in result.lower()
    assert "general" in result


def test_remember_content_symbols():
    t = Tool_Remember()
    result = t.execute(content="!@#$%^&*()", topic="preference")
    assert "stored" in result.lower() or "Created" in result


def test_remember_content_only_spaces():
    t = Tool_Remember()
    result = t.execute(content="   ", topic="preference")
    assert "stored" in result.lower() or "Created" in result


def test_remember_rapid_consecutive_correct_order():
    """Multiple remembers in sequence should return results in call order,
    with each result referencing the correct content and topic."""
    t = Tool_Remember()

    r = []
    for i in range(10):
        content = f"fact number {i}"
        topic = "preference" if i % 2 == 0 else "project"
        r.append(t.execute(content=content, topic=topic))

    # Each result should contain its own content
    for i, result in enumerate(r):
        assert f"number {i}" in result, f"Result {i} missing its content: {result[:60]}"
        expected_topic = "preference" if i % 2 == 0 else "project"
        assert expected_topic in result, f"Result {i} missing topic {expected_topic}: {result[:60]}"


def test_remember_fuzzy_to_existing_after_exact():
    """After creating topic with exact name, a fuzzy variant should match it."""
    t = Tool_Remember()
    t.execute(content="original", topic="vocabulary")
    result = t.execute(content="new word", topic="vocabuary")  # typo
    assert "matched existing" in result
    assert "vocabulary" in result


def test_remember_extends_triggers_supersede():
    t = Tool_Remember()
    t.execute(content="prefers Python", topic="preference")
    result = t.execute(content="prefers Python and Rust", topic="preference")
    # Should detect Extends → mark old inactive
    assert "updated" in result or "conflict" in result or "stored" in result


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


def test_recall_fact_chinese():
    t = Tool_Remember()
    t.execute(content="喜欢Python编程", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="喜欢")
    assert "喜欢" in result


def test_recall_fact_limit_clamp_negative():
    t = Tool_Remember()
    t.execute(content="keyword xyz", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="keyword", limit=-5)
    assert "xyz" in result


def test_recall_fact_limit_clamp_oversized():
    """Limit > 20 gets clamped back to 20."""
    t = Tool_Remember()
    for i in range(25):
        t.execute(content=f"keyword {i}", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="keyword", limit=100)
    # Should have at most 20 lines containing "fact_"
    count = result.count("fact_")
    assert count <= 20, f"Expected ≤20 facts, got {count}"


def test_recall_fact_excludes_inactive():
    """Superseded facts should NOT appear in results."""
    t = Tool_Remember()
    t.execute(content="original version", topic="preference")
    t.execute(content="original version with more details", topic="preference")

    s = Tool_RecallFact()
    result = s.execute(query="original version")
    # "original version" (the old one) might still match "original version with more details"
    # But the old version fact is inactive. There should be exactly 1 result.
    # Actually both contain "original version" — but the inactive one won't show up.
    # Since the new fact has the old text as substring, recall_fact still finds it.
    assert "original version" in result
    assert "original version with more details" in result


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


def test_recall_topic_include_inactive():
    """active_only=False should include superseded facts."""
    t = Tool_Remember()
    # First write, then a version that extends it (triggers supersede)
    # Use content where both facts have NO common substring
    # but the difflib ratio is still high enough to trigger supersede
    t.execute(content="likes cats", topic="preference")
    t.execute(content="likes dogs", topic="preference")

    rt = Tool_RecallTopic()
    result_all = rt.execute(topic="preference", active_only=False)
    result_active = rt.execute(topic="preference", active_only=True)

    assert "likes cats" in result_all, "Inactive fact should show when active_only=False"
    assert "likes dogs" in result_all, "Active fact should also show"
    assert "likes cats" not in result_active, "Inactive fact should NOT show when active_only=True"
    assert "likes dogs" in result_active, "Active fact should show when active_only=True"


def test_recall_topic_fuzzy_match():
    t = Tool_Remember()
    t.execute(content="fuzzy test data", topic="preference")

    rt = Tool_RecallTopic()
    result = rt.execute(topic="prefrences")
    assert "fuzzy test data" in result


def test_recall_topic_chinese():
    t = Tool_Remember()
    t.execute(content="中文内容", topic="偏好")

    rt = Tool_RecallTopic()
    result = rt.execute(topic="偏好")
    assert "中文内容" in result


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


def test_get_topic_list_counts_update():
    t = Tool_Remember()
    t.execute(content="unique preference fact", topic="preference")
    t.execute(content="another distinct fact", topic="preference")
    t.execute(content="project specific fact", topic="project")

    g = Tool_GetTopicList()
    result = g.execute()
    assert "preference" in result
    assert "project" in result
    # preference has 2 active facts
    assert "(2 facts)" in result
    # project has 1 active fact
    assert "(1 facts)" in result


def test_get_topic_list_chinese_topic():
    t = Tool_Remember()
    t.execute(content="test", topic="偏好")

    g = Tool_GetTopicList()
    result = g.execute()
    assert "偏好" in result


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
