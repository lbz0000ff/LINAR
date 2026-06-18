"""Shared fixtures for memory system tests."""

import pytest


@pytest.fixture
def fact_store(tmp_path):
    """Point FactStore at a temp directory so tests don't pollute real state."""
    from memory.fact import FactStore
    d = tmp_path / "state"
    d.mkdir(exist_ok=True)
    return FactStore(
        path=str(d / "fact_pool.json"),
        version_path=str(d / "compiled_version.txt"),
    )


@pytest.fixture
def topic_registry(tmp_path):
    """Point TopicRegistry at a temp directory."""
    from memory.topic import TopicRegistry
    d = tmp_path / "state"
    d.mkdir(exist_ok=True)
    return TopicRegistry(path=str(d / "topics.json"))
