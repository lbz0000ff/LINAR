import asyncio
import os
import sys
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llm


def _api_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", "https://example.com/v1/chat/completions"))


def _runtime(create):
    runtime = object.__new__(llm.LLM)
    runtime.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    runtime.system_prompt = "system"
    runtime.tools = {}
    runtime.model = "test-model"
    runtime.provider = "test-provider"
    return runtime


def test_client_disables_sdk_retries(monkeypatch) -> None:
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(llm, "AsyncOpenAI", fake_client)

    llm.LLM(api_key="test-key")

    assert captured["max_retries"] == 0


def test_generate_response_retries_api_errors_twice(monkeypatch) -> None:
    attempts = 0
    delays = []

    async def create(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _api_error()
        return SimpleNamespace(usage=None)

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    response = asyncio.run(_runtime(create).generate_response("hello"))

    assert response.usage is None
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_generate_response_raises_third_api_error(monkeypatch) -> None:
    attempts = 0

    async def create(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise _api_error()

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(APIConnectionError):
        asyncio.run(_runtime(create).generate_response("hello"))

    assert attempts == 3


class _Stream:
    def __init__(self, chunks, error_after=False):
        self._chunks = list(chunks)
        self._error_after = error_after

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._error_after:
            self._error_after = False
            raise _api_error()
        raise StopAsyncIteration


def test_stream_retries_when_error_occurs_before_first_chunk(monkeypatch) -> None:
    attempts = 0

    async def create(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return _Stream([], error_after=True)
        return _Stream(["ok"])

    async def fake_sleep(_delay):
        return None

    async def collect():
        return [chunk async for chunk in _runtime(create).stream_response_messages([])]

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    assert asyncio.run(collect()) == ["ok"]
    assert attempts == 3


def test_stream_does_not_retry_after_first_chunk(monkeypatch) -> None:
    attempts = 0

    async def create(**_kwargs):
        nonlocal attempts
        attempts += 1
        return _Stream(["partial"], error_after=True)

    async def collect():
        return [chunk async for chunk in _runtime(create).stream_response_messages([])]

    with pytest.raises(APIConnectionError):
        asyncio.run(collect())

    assert attempts == 1
