"""Content Block utilities for multimodal messages.

Content blocks are plain dicts compatible with the OpenAI Chat Completions
format.  No custom classes — just dictionaries that look like what the API
already expects::

    {"type": "text", "text": "hello"}
    {"type": "image_url", "image_url": {"url": "https://...", "detail": "high"}}

This keeps the module dependency-free and trivially composable.
"""

import json
import logging

log = logging.getLogger(__name__)


# ── type checks ──────────────────────────────────────────────────

def is_blocks(content) -> bool:
    """Return ``True`` when *content* is a list of Content Block dicts."""
    return (
        isinstance(content, list)
        and len(content) > 0
        and all(isinstance(b, dict) and "type" in b for b in content)
    )


def is_string_content(content) -> bool:
    """Return ``True`` when *content* is a plain string (legacy format)."""
    return isinstance(content, str)


# ── builders ─────────────────────────────────────────────────────

def text_block(text: str) -> dict:
    """Create a ``text`` Content Block."""
    return {"type": "text", "text": text}


def image_url_block(url: str, detail: str = "high") -> dict:
    """Create an ``image_url`` Content Block."""
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}


def from_string(text: str) -> list[dict]:
    """Convert a plain string to a single-element Content Block list."""
    return [text_block(text)] if text else []


# ── extraction ───────────────────────────────────────────────────

def extract_text(blocks: list[dict]) -> str:
    """Extract readable text from Content Blocks (for DB fallback / display)."""
    parts = []
    for b in blocks:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
    return " ".join(parts)


def extract_image_urls(blocks: list[dict]) -> list[str]:
    """Extract all image URLs from Content Blocks."""
    urls: list[str] = []
    for b in blocks:
        if b.get("type") == "image_url":
            u = (b.get("image_url") or {}).get("url", "")
            if u:
                urls.append(u)
    return urls


# ── serialisation for DB ─────────────────────────────────────────

def blocks_to_json(content: str | list[dict]) -> str:
    """Serialize *content* for DB storage.

    - Content Block lists → JSON string
    - Plain strings → returned as-is (backwards compatible)
    """
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return content


def blocks_from_json(raw: str) -> list[dict] | None:
    """Try to parse a DB *raw* string as a Content Block list.

    Returns ``None`` when *raw* is not a JSON array of blocks (legacy text).
    """
    if not isinstance(raw, str) or not raw.startswith("["):
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if is_blocks(parsed):
        return parsed
    return None


# ── validation ───────────────────────────────────────────────────

def has_image_blocks(blocks: list[dict]) -> bool:
    """Return ``True`` if any block is an ``image_url``."""
    return any(b.get("type") == "image_url" for b in blocks)
