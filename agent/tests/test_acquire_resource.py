import asyncio
import hashlib
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from pypdf import PdfWriter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tool.basic_tools import tool_web
from tool.basic_tools.tool_acquire import Tool_AcquireResource
from tool_registry import _TOOL_CLASSES, _TOOLSETS


PUBLIC_IP = "93.184.216.34"


def _allow_public(monkeypatch) -> None:
    monkeypatch.setattr(
        "tool.basic_tools.tool_acquire._check_ssrf",
        lambda url: (urlparse(url), PUBLIC_IP),
    )


def _tool(tmp_path: Path, **config) -> Tool_AcquireResource:
    tool = Tool_AcquireResource()
    tool.agent_ref = SimpleNamespace(
        _workspace_root=str(tmp_path),
        cfg={"acquire_resource": config},
    )
    return tool


def test_ssrf_rejects_hostname_when_any_resolved_address_is_private(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ],
    )

    result = tool_web._check_ssrf("https://mixed.example/file.pdf")

    assert result["error"].startswith("Blocked SSRF target")
    assert "127.0.0.1" in result["error"]


def test_ssrf_rejects_urls_with_embedded_credentials():
    result = tool_web._check_ssrf("https://user:password@example.com/file.pdf")

    assert "credentials" in result["error"]


def test_acquire_image_sanitizes_filename_and_registers_local_image(monkeypatch, tmp_path):
    _allow_public(monkeypatch)
    payload = b"\x89PNG\r\n\x1a\n" + b"image-payload"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "image/png",
                "content-disposition": 'attachment; filename="../../chart.png"',
            },
            content=payload,
            request=request,
        )

    tool = _tool(tmp_path)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = asyncio.run(tool.execute(url="https://example.com/files/chart"))

    path = Path(result["path"])
    assert path.parent == tmp_path / "acquired"
    assert path.name.startswith("chart-")
    assert path.suffix == ".png"
    assert path.read_bytes() == payload
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["detected_content_type"] == "image/png"
    assert result["image_uri"] == f"file://{path}"
    assert str(path) in result["message"]


def test_acquire_revalidates_every_redirect_target(monkeypatch, tmp_path):
    checked = []

    def check(url: str):
        checked.append(url)
        if "127.0.0.1" in url:
            return {"error": "Blocked SSRF target: private redirect."}
        return (urlparse(url), PUBLIC_IP)

    monkeypatch.setattr("tool.basic_tools.tool_acquire._check_ssrf", check)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private.pdf"},
            request=request,
        )

    tool = _tool(tmp_path)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = asyncio.run(tool.execute(url="https://example.com/paper"))

    assert result["error"].startswith("Blocked SSRF target")
    assert checked == [
        "https://example.com/paper",
        "http://127.0.0.1/private.pdf",
    ]
    assert not (tmp_path / "acquired").exists()


def test_acquire_enforces_streaming_size_limit_and_removes_partial_file(
    monkeypatch, tmp_path
):
    _allow_public(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"123456789",
            request=request,
        )

    tool = _tool(tmp_path, max_bytes=4)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = asyncio.run(tool.execute(url="https://example.com/data.bin"))

    assert "maximum allowed size" in result["error"]
    acquired = tmp_path / "acquired"
    assert not acquired.exists() or not list(acquired.iterdir())


def test_acquire_pdf_keeps_original_and_returns_extracted_text_preview(
    monkeypatch, tmp_path
):
    _allow_public(monkeypatch)
    payload = b"%PDF-1.7\nfixture"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=payload,
            request=request,
        )

    tool = _tool(tmp_path, pdf_preview_chars=12)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    def fake_extract(path: Path) -> tuple[str, int]:
        assert path.read_bytes() == payload
        return "A research paper body", 7

    monkeypatch.setattr(tool, "_extract_pdf_text", fake_extract)

    result = asyncio.run(tool.execute(url="https://example.com/paper.pdf"))

    assert Path(result["path"]).read_bytes() == payload
    assert Path(result["extracted_text_file"]).read_text(encoding="utf-8") == (
        "A research paper body"
    )
    assert result["page_count"] == 7
    assert result["content_preview"] == "A research p"
    assert "PDF text preview" in result["message"]


def test_acquire_rejects_html_pages_and_removes_download(monkeypatch, tmp_path):
    _allow_public(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<!doctype html><html></html>",
            request=request,
        )

    tool = _tool(tmp_path)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = asyncio.run(tool.execute(url="https://example.com/page"))

    assert "web_fetch" in result["error"]
    acquired = tmp_path / "acquired"
    assert not acquired.exists() or not list(acquired.iterdir())


def test_detected_signature_replaces_a_misleading_extension(monkeypatch, tmp_path):
    _allow_public(monkeypatch)
    payload = b"%PDF-1.7\nfixture"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=payload,
            request=request,
        )

    tool = _tool(tmp_path)
    monkeypatch.setattr(
        tool,
        "_build_client",
        lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(tool, "_extract_pdf_text", lambda _path: ("", 1))

    result = asyncio.run(tool.execute(url="https://example.com/report.exe"))

    assert Path(result["path"]).suffix == ".pdf"
    assert result["detected_content_type"] == "application/pdf"
    assert "did not match" in result["warning"]


def test_acquire_resource_is_registered_in_web_and_research_toolsets():
    assert _TOOL_CLASSES["acquire_resource"] is Tool_AcquireResource
    assert "acquire_resource" in _TOOLSETS["web"]
    assert "acquire_resource" in _TOOLSETS["research"]


def test_parallel_acquisition_of_same_url_does_not_share_partial_file(
    monkeypatch, tmp_path
):
    _allow_public(monkeypatch)
    payload = b"parallel payload"

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=payload,
            request=request,
        )

    first = _tool(tmp_path)
    second = _tool(tmp_path)
    for tool in (first, second):
        monkeypatch.setattr(
            tool,
            "_build_client",
            lambda _timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    async def acquire_both():
        return await asyncio.gather(
            first.execute(url="https://example.com/shared.bin"),
            second.execute(url="https://example.com/shared.bin"),
        )

    results = asyncio.run(acquire_both())

    assert all("error" not in result for result in results)
    assert results[0]["path"] == results[1]["path"]
    assert Path(results[0]["path"]).read_bytes() == payload
    assert not list((tmp_path / "acquired").glob("*.part"))


def test_pdf_extractor_reads_a_real_pdf(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as output:
        writer.write(output)

    text, page_count = Tool_AcquireResource._extract_pdf_text(pdf_path)

    assert text == ""
    assert page_count == 1
