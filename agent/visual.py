"""Multimodal visual content resolver.

Resolves image sources (local file paths, remote URLs) into URL strings
compatible with any OpenAI-compatible LLM provider's ``image_url`` field.

Resolution priority (high → low):

1. Remote URL — passed through directly.
2. Provider-specific file upload — uploaded to the provider's file server
   (e.g. StepFun ``stepfile://``) to avoid base64 overhead.
3. Base64 data URI — universal fallback that every provider accepts.

Add new providers by adding ``_upload_{provider}()`` methods.
"""

import base64
import os
import logging

log = logging.getLogger(__name__)

_SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


class VisualResolver:
    """Turn image sources into ``image_url``-compatible URL strings.

    Usage::

        resolver = VisualResolver(provider="stepfun", api_key="...", base_url="...")
        url = resolver.resolve("/path/to/img.png")
        # → "data:image/png;base64,iVBOR..."  (universal)
        # → "stepfile://file-abc123"          (StepFun optimisation)
    """

    def __init__(self, provider: str = "", api_key: str = "", base_url: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    # ── public API ────────────────────────────────────────────────

    def resolve(self, source: str) -> str | None:
        """Return a URL string usable in ``image_url.url``.

        Returns ``None`` when the source cannot be resolved (not found,
        unsupported type, upload failure, etc.)
        """
        if not source or not isinstance(source, str):
            return None

        # 1. Remote URL — pass through directly (all providers accept it)
        if source.startswith(("http://", "https://")):
            return source

        # 2. Local file
        if os.path.isfile(source):
            ext = os.path.splitext(source)[1].lower()
            if ext not in _SUPPORTED_EXT:
                log.warning("Unsupported image extension '%s': %s", ext, source)
                return None

            # Try provider-specific upload (avoids base64 overhead)
            uploaded = self._upload_to_provider(source)
            if uploaded:
                return uploaded

            # Fallback: base64 (every provider accepts this)
            return self._base64_encode(source, ext)

        log.warning("Image source not found or unsupported: %s", source)
        return None

    # ── provider-specific upload optimisations ────────────────────

    def _upload_to_provider(self, path: str) -> str | None:
        """Try to upload *path* via the provider's file API.

        Returns a provider-specific URL string (e.g. ``stepfile://...``)
        or ``None`` to fall back to base64.
        """
        provider = (self.provider or "").lower()
        try:
            if provider == "stepfun":
                return self._upload_stepfun(path)
            # Add other providers here:
            # if provider == "zhipu":
            #     return self._upload_zhipu(path)
            # if provider == "openai":
            #     ...
        except Exception as exc:
            log.warning(
                "Provider file upload failed for '%s': %s — falling back to base64",
                path, exc,
            )
        return None

    def _upload_stepfun(self, path: str) -> str:
        """Upload to StepFun ``purpose=storage`` → ``stepfile://`` URL.

        Uses the standard ``https://api.stepfun.com/v1/files`` endpoint
        regardless of which chat plan (e.g. ``step_plan``) the user is on,
        because StepFun's file service lives under the standard v1 path.
        """
        import requests
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        files_url = f"{parsed.scheme}://{parsed.hostname}/v1/files"
        with open(path, "rb") as f:
            resp = requests.post(
                files_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": f},
                data={"purpose": "storage"},
                timeout=120,
            )
        resp.raise_for_status()
        file_id = resp.json()["id"]
        log.info("Uploaded %s → StepFun file %s", path, file_id)
        return f"stepfile://{file_id}"

    # ── universal fallback ────────────────────────────────────────

    def _base64_encode(self, path: str, ext: str | None = None) -> str:
        """Encode a local image as a ``data:`` URI (base64)."""
        if ext is None:
            ext = os.path.splitext(path)[1].lower()
        mime = _MIME_MAP.get(ext, "image/png")
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"
