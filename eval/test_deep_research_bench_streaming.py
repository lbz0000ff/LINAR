"""Regression tests for streaming RACE evaluator requests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

import pytest


BENCH_DIR = Path(__file__).resolve().parent / "deep_research_bench"
sys.path.insert(0, str(BENCH_DIR))

from utils import api  # noqa: E402


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code
        self.text = "error body"
        self.closed = False

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def iter_lines(self, decode_unicode: bool = False):
        assert decode_unicode is False
        yield from (line.encode("utf-8") for line in self._lines)

    def close(self) -> None:
        self.closed = True


def _chunk(content: str = "", finish_reason: str | None = None) -> str:
    return "data: " + json.dumps({
        "choices": [{
            "delta": {"content": content},
            "finish_reason": finish_reason,
        }],
    })


def test_generate_enables_streaming_and_assembles_sse_chunks(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response = _FakeStreamResponse([
        ": heartbeat",
        _chunk("hello "),
        "",
        _chunk("world", "stop"),
        "data: [DONE]",
    ])

    def fake_post(*_args: object, **kwargs: object) -> _FakeStreamResponse:
        captured.update(kwargs)
        return response

    monkeypatch.setattr(api.requests, "post", fake_post)
    client = api.AIClient(api_key="test-key", model="gpt-test")

    result = client.generate("score this")

    assert result == "hello world"
    assert captured["stream"] is True
    assert captured["json"]["stream"] is True
    assert captured["timeout"] == (api.HTTP_CONNECT_TIMEOUT_S, api.HTTP_TIMEOUT_S)
    assert response.closed is True


def test_generate_preserves_stream_finish_reason(monkeypatch) -> None:
    response = _FakeStreamResponse([
        _chunk("partial", "length"),
        "data: [DONE]",
    ])
    monkeypatch.setattr(api.requests, "post", lambda *_args, **_kwargs: response)
    client = api.AIClient(api_key="test-key")

    assert client.generate(
        "clean this",
        return_metadata=True,
        stage="clean",
    ) == ("partial", "length")


def test_generate_keeps_utf8_continuation_byte_out_of_line_splitting(monkeypatch) -> None:
    # "全" contains UTF-8 byte 0x85. If requests decodes before splitlines(),
    # that byte becomes U+0085 (NEL) under a Latin-1 response and splits JSON.
    response = _FakeStreamResponse([
        _chunk("全部正常", "stop"),
        "data: [DONE]",
    ])
    monkeypatch.setattr(api.requests, "post", lambda *_args, **_kwargs: response)

    assert api.AIClient(api_key="test-key").generate("score") == "全部正常"


def test_generate_stops_reading_when_cancelled(monkeypatch) -> None:
    stop_event = threading.Event()

    class _CancellingResponse(_FakeStreamResponse):
        def iter_lines(self, decode_unicode: bool = False):
            yield _chunk("first")
            stop_event.set()
            yield _chunk("second", "stop")

    response = _CancellingResponse([])
    monkeypatch.setattr(api.requests, "post", lambda *_args, **_kwargs: response)
    client = api.AIClient(api_key="test-key", stop_event=stop_event)

    with pytest.raises(api.EvaluationCancelled):
        client.generate("score this")

    assert response.closed is True


def test_cancel_closes_an_active_stream(monkeypatch) -> None:
    started = threading.Event()
    released = threading.Event()

    class _BlockingResponse(_FakeStreamResponse):
        def iter_lines(self, decode_unicode: bool = False):
            started.set()
            released.wait(timeout=2)
            if False:
                yield ""

        def close(self) -> None:
            super().close()
            released.set()

    response = _BlockingResponse([])
    monkeypatch.setattr(api.requests, "post", lambda *_args, **_kwargs: response)
    client = api.AIClient(api_key="test-key")
    errors: list[BaseException] = []

    def run_request() -> None:
        try:
            client.generate("score this")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run_request)
    worker.start()
    assert started.wait(timeout=1)

    client.cancel()
    worker.join(timeout=1)

    assert worker.is_alive() is False
    assert response.closed is True
    assert len(errors) == 1
    assert isinstance(errors[0], api.EvaluationCancelled)


def test_cancel_does_not_block_on_a_stuck_response_close() -> None:
    close_started = threading.Event()
    release_close = threading.Event()

    class _StuckCloseResponse:
        def close(self) -> None:
            close_started.set()
            release_close.wait(timeout=2)

    client = api.AIClient(api_key="test-key")
    response = _StuckCloseResponse()
    with client._active_lock:
        client._active_responses.add(response)

    cancel_thread = threading.Thread(target=client.cancel)
    cancel_thread.start()
    assert close_started.wait(timeout=1)
    cancel_thread.join(timeout=0.1)

    try:
        assert cancel_thread.is_alive() is False
    finally:
        release_close.set()
        cancel_thread.join(timeout=1)
