"""Safely acquire non-HTML web resources into the active workspace."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from .tool import Tool
from .tool_web import _check_ssrf
from visual import detect_image_mime_bytes


DEFAULT_TIMEOUT = 60
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
ABSOLUTE_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_ARTIFACT_DIR = "acquired"
DEFAULT_PDF_PREVIEW_CHARS = 6000
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_DOS_RESERVED = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_CONTENT_DISPOSITION_FILENAME = re.compile(
    r"filename\*?=(?:UTF-8''|\")?([^\";]+)", re.IGNORECASE
)
_SIGNATURE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/zip": ".zip",
}


def _load_acquire_config() -> dict[str, Any]:
    try:
        from config import load_config

        return load_config().get("acquire_resource", {})
    except Exception:
        return {}


def _safe_filename(value: str) -> str:
    """Return a portable basename without traversal or device names."""
    name = os.path.basename(unquote(value).replace("\\", "/"))
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "resource"
    if _DOS_RESERVED.match(name):
        name = f"_{name}"
    stem, suffix = os.path.splitext(name[:160])
    return f"{stem[:120] or 'resource'}{suffix[:20]}"


def _response_filename(headers: httpx.Headers, url: str) -> str:
    disposition = headers.get("content-disposition", "")
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    if match:
        return _safe_filename(match.group(1).strip())
    url_name = Path(unquote(urlparse(url).path)).name
    return _safe_filename(url_name or "resource")


def _declared_content_type(headers: httpx.Headers) -> str:
    return headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()


def _detect_content_type(header: bytes, declared: str) -> str:
    image_type = detect_image_mime_bytes(header)
    if image_type:
        return image_type
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"PK\x03\x04"):
        return "application/zip"
    lowered = header.lstrip().lower()
    if declared == "text/html" or lowered.startswith((b"<!doctype html", b"<html")):
        return "text/html"
    return declared or "application/octet-stream"


def _with_hash_suffix(filename: str, digest: str, content_type: str) -> str:
    stem, suffix = os.path.splitext(filename)
    signature_suffix = _SIGNATURE_EXTENSIONS.get(content_type)
    if signature_suffix:
        suffix = signature_suffix
    elif not suffix:
        suffix = mimetypes.guess_extension(content_type) or ""
    return f"{stem or 'resource'}-{digest[:10]}{suffix.lower()}"


class Tool_AcquireResource(Tool):
    """Download one explicit asset URL with bounded, workspace-owned storage."""

    name: str = "acquire_resource"
    description: str = (
        "Download an explicit image, PDF, or other non-HTML resource URL into "
        "the active workspace. Use web_fetch for normal web pages."
    )
    stop_event: Any = None
    agent_ref: Any = None
    tool_schema: dict = {
        "name": "acquire_resource",
        "description": (
            "Safely downloads one explicit non-HTML resource URL. Images become "
            "visible automatically; PDFs return a text preview and extracted-text path."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Direct HTTP(S) URL of an image, PDF, or attachment.",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    }

    async def execute(self, url: str | None = None) -> dict[str, Any]:
        if not isinstance(url, str) or not url.strip():
            return {"error": "url is required and must be a non-empty string."}

        cfg = self._effective_config()
        current_url = url.strip()
        resolved_ip = ""

        try:
            async with self._build_client(cfg["timeout"]) as client:
                for redirect_count in range(cfg["max_redirects"] + 1):
                    checked = _check_ssrf(current_url)
                    if isinstance(checked, dict):
                        return checked
                    _parsed, resolved_ip = checked

                    async with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                return {"error": "Redirect response did not include a Location header."}
                            if redirect_count >= cfg["max_redirects"]:
                                return {
                                    "error": (
                                        "Resource exceeded the configured redirect limit "
                                        f"({cfg['max_redirects']})."
                                    )
                                }
                            current_url = urljoin(current_url, location)
                            continue

                        response.raise_for_status()
                        content_length = response.headers.get("content-length")
                        if content_length:
                            try:
                                declared_size = int(content_length)
                            except ValueError:
                                declared_size = 0
                            if declared_size > cfg["max_bytes"]:
                                return self._size_error(declared_size, cfg["max_bytes"])

                        return await self._save_response(
                            requested_url=url.strip(),
                            final_url=current_url,
                            resolved_ip=resolved_ip,
                            response=response,
                            cfg=cfg,
                        )
        except httpx.HTTPStatusError as exc:
            return {"error": f"Resource request failed with HTTP {exc.response.status_code}."}
        except httpx.TimeoutException:
            return {"error": f"Resource request timed out after {cfg['timeout']} seconds."}
        except httpx.HTTPError as exc:
            return {"error": f"Resource request failed: {exc}"}
        except OSError as exc:
            return {"error": f"Could not save resource: {exc}"}

        return {"error": "Resource acquisition ended without a response."}

    def _effective_config(self) -> dict[str, Any]:
        cfg = _load_acquire_config()
        agent_cfg = getattr(getattr(self, "agent_ref", None), "cfg", {})
        if isinstance(agent_cfg, dict):
            cfg = {**cfg, **(agent_cfg.get("acquire_resource") or {})}
        requested_max = int(cfg.get("max_bytes", DEFAULT_MAX_BYTES))
        return {
            "timeout": max(1, int(cfg.get("timeout", DEFAULT_TIMEOUT))),
            "max_bytes": min(max(1, requested_max), ABSOLUTE_MAX_BYTES),
            "max_redirects": min(max(0, int(cfg.get("max_redirects", DEFAULT_MAX_REDIRECTS))), 10),
            "artifact_dir": str(cfg.get("artifact_dir", DEFAULT_ARTIFACT_DIR)),
            "pdf_preview_chars": min(
                max(0, int(cfg.get("pdf_preview_chars", DEFAULT_PDF_PREVIEW_CHARS))),
                30000,
            ),
        }

    def _build_client(self, timeout: int) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": "LINAR/1.0 resource acquisition"},
            trust_env=False,
        )

    def _artifact_root(self, artifact_dir: str) -> Path:
        agent = getattr(self, "agent_ref", None)
        workspace_root = getattr(agent, "_workspace_root", None)
        if workspace_root:
            return Path(workspace_root) / artifact_dir
        project_root = getattr(agent, "_project_root", None)
        if project_root:
            return Path(project_root) / ".temp" / artifact_dir
        return Path(__file__).resolve().parents[2] / ".temp" / artifact_dir

    async def _save_response(
        self,
        *,
        requested_url: str,
        final_url: str,
        resolved_ip: str,
        response: httpx.Response,
        cfg: dict[str, Any],
    ) -> dict[str, Any]:
        root = self._artifact_root(cfg["artifact_dir"])
        root.mkdir(parents=True, exist_ok=True)
        partial = root / f".acquire-{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        header = bytearray()
        total = 0

        try:
            with partial.open("wb") as output:
                async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK_SIZE):
                    if self.stop_event is not None and self.stop_event.is_set():
                        raise InterruptedError("Resource acquisition interrupted by user.")
                    total += len(chunk)
                    if total > cfg["max_bytes"]:
                        return self._size_error(total, cfg["max_bytes"])
                    digest.update(chunk)
                    if len(header) < 512:
                        header.extend(chunk[: 512 - len(header)])
                    output.write(chunk)

            declared_type = _declared_content_type(response.headers)
            detected_type = _detect_content_type(bytes(header), declared_type)
            if detected_type == "text/html":
                return {
                    "error": (
                        "acquire_resource received an HTML page. Use web_fetch to read "
                        "pages and pass acquire_resource a direct image, PDF, or attachment URL."
                    )
                }

            sha256 = digest.hexdigest()
            filename = _with_hash_suffix(
                _response_filename(response.headers, final_url),
                sha256,
                detected_type,
            )
            destination = root / filename
            os.replace(partial, destination)
            result: dict[str, Any] = {
                "requested_url": requested_url,
                "final_url": final_url,
                "status_code": response.status_code,
                "path": str(destination),
                "filename": destination.name,
                "declared_content_type": declared_type,
                "detected_content_type": detected_type,
                "bytes": total,
                "sha256": sha256,
                "resolved_ip": resolved_ip,
            }

            details = [
                "acquire_resource downloaded a resource.",
                f"URL: {final_url}",
                f"Path: {destination}",
                f"Type: {detected_type}",
                f"Size: {total} bytes",
                f"SHA-256: {sha256}",
            ]
            if detected_type.startswith("image/") and detect_image_mime_bytes(bytes(header)):
                result["image_uri"] = f"file://{destination}"

            if detected_type == "application/pdf":
                await self._add_pdf_extraction(result, destination, cfg, details)

            if declared_type not in {detected_type, "application/octet-stream"}:
                warning = (
                    f"Declared type {declared_type} did not match detected type {detected_type}."
                )
                result["warning"] = warning
                details.append(f"Warning: {warning}")

            if result.get("content_preview"):
                details.extend(["PDF text preview:", result["content_preview"]])
            result["message"] = "\n".join(details)
            return result
        except InterruptedError as exc:
            return {"error": str(exc)}
        finally:
            if partial.exists():
                try:
                    partial.unlink()
                except OSError:
                    pass

    async def _add_pdf_extraction(
        self,
        result: dict[str, Any],
        pdf_path: Path,
        cfg: dict[str, Any],
        details: list[str],
    ) -> None:
        try:
            text, page_count = await asyncio.to_thread(self._extract_pdf_text, pdf_path)
            result["page_count"] = page_count
            if not text.strip():
                result["extraction_warning"] = "PDF contains no extractable text."
                details.append("PDF text extraction: no extractable text found.")
                return
            text_path = pdf_path.with_suffix(pdf_path.suffix + ".md")
            text_path.write_text(text, encoding="utf-8")
            result["extracted_text_file"] = str(text_path)
            result["text_chars"] = len(text)
            result["content_preview"] = text[: cfg["pdf_preview_chars"]]
            details.append(
                f"Extracted PDF text: {text_path} ({page_count} pages, {len(text)} chars)"
            )
        except Exception as exc:
            result["extraction_warning"] = f"PDF text extraction failed: {exc}"
            details.append(f"PDF text extraction failed; original PDF was retained: {exc}")

    @staticmethod
    def _extract_pdf_text(path: Path) -> tuple[str, int]:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(text.strip() for text in pages if text.strip()), len(reader.pages)

    @staticmethod
    def _size_error(actual: int, maximum: int) -> dict[str, str]:
        return {
            "error": (
                f"Resource size ({actual} bytes) exceeds the maximum allowed size "
                f"({maximum} bytes)."
            )
        }
