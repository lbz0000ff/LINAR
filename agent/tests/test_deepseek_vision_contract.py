import base64
import asyncio
import os
import sys
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import Agent
from observation_store import ObservationStore
from visual import DEEPSEEK_FILE_URI_PREFIX, VisualResolver, detect_image_mime
from tool.basic_tools import tool_vision_vlm


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _runtime(llm_cfg: dict | None = None) -> Agent:
    runtime = Agent.__new__(Agent)
    runtime._is_multimodal = True
    runtime.cfg = {"llm": llm_cfg or {}}
    runtime.tools = {}
    runtime.llm = SimpleNamespace(
        provider="deepseek",
        model="deepseek-v4-flash-vision-exp",
        system_prompt="vision test",
    )
    return runtime


def test_visual_resolver_detects_content_instead_of_extension(tmp_path):
    image = tmp_path / "fixture.bin"
    image.write_bytes(_PNG_1X1)

    resolved = VisualResolver(provider="deepseek").resolve(str(image))

    assert detect_image_mime(str(image)) == "image/png"
    assert resolved is not None
    assert resolved.startswith("data:image/png;base64,")


def test_visual_resolver_rejects_bmp_content(tmp_path):
    image = tmp_path / "fixture.bmp"
    image.write_bytes(b"BM" + b"\x00" * 32)

    assert detect_image_mime(str(image)) is None
    assert VisualResolver(provider="deepseek").resolve(str(image)) is None


def test_deepseek_files_api_upload_is_cached(monkeypatch, tmp_path):
    image = tmp_path / "fixture.png"
    image.write_bytes(_PNG_1X1)
    calls = []

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"id": "file-api-test123"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setattr("requests.post", fake_post)
    resolver = VisualResolver(
        provider="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        file_upload_mode="always",
        file_upload_expires_seconds=86400,
    )

    first = resolver.resolve(str(image))
    second = resolver.resolve(str(image))

    assert first == f"{DEEPSEEK_FILE_URI_PREFIX}file-api-test123"
    assert second == first
    assert len(calls) == 1
    assert calls[0][0] == "https://api.deepseek.com/files"
    assert calls[0][1]["data"] == {
        "purpose": "user_data",
        "expires_after[anchor]": "created_at",
        "expires_after[seconds]": "86400",
    }


def test_deepseek_upload_failure_falls_back_to_inline(monkeypatch, tmp_path):
    image = tmp_path / "fixture.png"
    image.write_bytes(_PNG_1X1)

    def fail_post(*_args, **_kwargs):
        raise RuntimeError("upload unavailable")

    monkeypatch.setattr("requests.post", fail_post)
    resolver = VisualResolver(
        provider="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        file_upload_mode="always",
    )

    assert resolver.resolve(str(image)).startswith("data:image/png;base64,")


def test_local_file_upload_materialises_as_file_content_block():
    runtime = _runtime()
    runtime._materialise_file_url = lambda _path: (
        f"{DEEPSEEK_FILE_URI_PREFIX}file-api-test123"
    )

    resolved = runtime._resolve_blocks([{
        "type": "image_url",
        "image_url": {"url": "file:///tmp/image.png", "detail": "high"},
    }])

    assert resolved == [{"type": "file", "file_id": "file-api-test123"}]


def test_observation_images_are_attached_only_once():
    store = ObservationStore()
    store.add_image("https://example.com/one.png")
    store.add_image("https://example.com/two.png")

    assert store.has_images() is True
    assert store.pop_attachable_images() == [
        "https://example.com/one.png",
        "https://example.com/two.png",
    ]
    assert store.has_images() is False
    assert store.pop_attachable_images() == []


def test_deepseek_rejects_images_outside_user_messages():
    runtime = _runtime()
    messages = [{
        "role": "assistant",
        "content": [{
            "type": "image_url",
            "image_url": {"url": "https://example.com/image.png"},
        }],
    }]

    with pytest.raises(ValueError, match="only appear in user messages"):
        runtime._validate_deepseek_multimodal_request(messages)


def test_deepseek_enforces_linar_image_count_limit():
    runtime = _runtime({"max_images_per_request": 1})
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/1.png"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/2.png"}},
        ],
    }]

    with pytest.raises(ValueError, match="Too many images"):
        runtime._validate_deepseek_multimodal_request(messages)


def test_deepseek_rejects_unsupported_inline_mime():
    runtime = _runtime()
    messages = [{
        "role": "user",
        "content": [{
            "type": "image_url",
            "image_url": {"url": "data:image/bmp;base64,Qk0="},
        }],
    }]

    with pytest.raises(ValueError, match="JPEG, PNG, GIF, or WebP"):
        runtime._validate_deepseek_multimodal_request(messages)


def test_deepseek_enforces_configured_request_body_limit():
    runtime = _runtime({"max_request_size_mb": 0.0001})
    messages = [{"role": "user", "content": "x" * 1024}]

    with pytest.raises(ValueError, match="request body"):
        runtime._validate_deepseek_multimodal_request(messages)


def test_remote_vision_preserves_provider_side_url():
    url = "https://example.com/image.png"

    result = tool_vision_vlm.Tool_Vision().execute(url)

    assert result["image_uri"] == url


def _image_download_error() -> BadRequestError:
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "Failed to download image from https://example.com/image.png",
        response=response,
        body={"error": {"message": "Failed to download image"}},
    )


def test_provider_image_fetch_error_becomes_vision_tool_error():
    runtime = _runtime()
    runtime.chat_history = [{
        "role": "tool",
        "tool_call_id": "vision-1",
        "name": "vision",
        "result": "vision: image loaded",
    }]
    runtime._last_attached_image_events = [{
        "uri": "https://example.com/image.png",
        "tool_name": "vision",
        "tool_call_id": "vision-1",
    }]
    runtime._tool_failures = {}
    emitted = []
    runtime.emit = emitted.append

    assert runtime._handle_remote_image_fetch_error(_image_download_error()) is True
    assert runtime.chat_history[0]["result"].startswith("Error: DeepSeek could not download")
    assert emitted[0]["type"] == "tool_result"
    assert emitted[0]["id"] == "vision-1"


def test_unrelated_bad_request_is_not_demoted_to_tool_error():
    runtime = _runtime()
    runtime.chat_history = []
    runtime._last_attached_image_events = []

    assert runtime._handle_remote_image_fetch_error(_image_download_error()) is False


def test_img_to_text_fetch_error_stays_at_tool_boundary():
    runtime = _runtime()
    runtime.chat_history = [{
        "role": "tool",
        "tool_call_id": "img2text-1",
        "name": "img_to_text",
        "result": "vision_query: image loaded",
    }]
    runtime._last_attached_image_events = [{
        "uri": "https://example.com/image.png",
        "tool_name": "img_to_text",
        "tool_call_id": "img2text-1",
    }]
    runtime._tool_failures = {}
    emitted = []
    runtime.emit = emitted.append

    assert runtime._handle_remote_image_fetch_error(_image_download_error()) is True
    assert runtime.chat_history[0]["result"].startswith("Error: DeepSeek could not download")
    assert runtime._tool_failures == {"img_to_text": 1}
    assert emitted == [{
        "type": "tool_result",
        "name": "img_to_text",
        "id": "img2text-1",
        "result": runtime.chat_history[0]["result"],
    }]


def test_image_fetch_error_updates_only_the_failed_url():
    runtime = _runtime()
    runtime.chat_history = [
        {"role": "tool", "tool_call_id": "one", "name": "vision", "result": "loaded"},
        {"role": "tool", "tool_call_id": "two", "name": "img_to_text", "result": "loaded"},
    ]
    runtime._last_attached_image_events = [
        {"uri": "https://example.com/image.png", "tool_name": "vision", "tool_call_id": "one"},
        {"uri": "https://example.com/other.png", "tool_name": "img_to_text", "tool_call_id": "two"},
    ]
    runtime._tool_failures = {}
    runtime.emit = lambda _event: None

    assert runtime._handle_remote_image_fetch_error(_image_download_error()) is True
    assert runtime.chat_history[0]["result"].startswith("Error:")
    assert runtime.chat_history[1]["result"] == "loaded"


class _FetchFailingLLM:
    provider = "deepseek"
    model = "deepseek-v4-flash-vision-exp"
    system_prompt = "vision test"

    def __init__(self) -> None:
        self.calls = 0

    def stream_response_messages(self, _messages):
        async def stream():
            self.calls += 1
            if self.calls == 1:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=None,
                    reasoning_content=None,
                    tool_calls=[SimpleNamespace(
                        index=0,
                        id="vision-1",
                        function=SimpleNamespace(
                            name="vision",
                            arguments='{"image":"https://example.com/image.png"}',
                        ),
                    )],
                ))])
            elif self.calls == 2:
                raise _image_download_error()
            else:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="The image provider could not fetch the URL.",
                    reasoning_content=None,
                    tool_calls=None,
                ))])
        return stream()


def test_provider_image_failure_stays_inside_agent_tool_loop(monkeypatch):
    cfg = {
        "llm": {
            "api_key": "test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash-vision-exp",
            "provider": "deepseek",
            "multimodal": True,
        },
        "max_turns": 10,
        "chat_history": {},
        "permissions": {"default": "allow"},
        "permission_modes": {},
    }
    monkeypatch.setattr("agent.load_config", lambda: cfg)
    runtime = Agent(tools={"vision": tool_vision_vlm.Tool_Vision()}, memory_enabled=False)
    runtime.llm = _FetchFailingLLM()
    events = []
    runtime.emit = events.append

    asyncio.run(runtime.process_with_llm())

    vision_result = next(
        message["result"]
        for message in runtime.chat_history
        if message.get("role") == "tool" and message.get("name") == "vision"
    )
    assert runtime.llm.calls == 3
    assert vision_result.startswith("Error: DeepSeek could not download")
    assert any(
        event.get("type") == "tool_result"
        and event.get("id") == "vision-1"
        and str(event.get("result", "")).startswith("Error:")
        for event in events
    )
    assert any(
        message.get("role") == "agent"
        and "provider could not fetch" in message.get("content", "")
        for message in runtime.chat_history
    )
