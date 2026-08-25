"""Multimodal visual content resolver.

Resolves image sources (local file paths, remote URLs) into provider references:
ordinary URL/data strings or a sentinel for an uploaded DeepSeek ``file_id``.

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

MAX_INLINE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_DEEPSEEK_FILE_BYTES = 64 * 1024 * 1024
DEEPSEEK_FILE_URI_PREFIX = "deepseekfile://"
SUPPORTED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


def detect_image_mime_bytes(data: bytes) -> str | None:
    """Detect a supported image type from its signature bytes."""
    header = data[:16]
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def detect_image_mime(path: str) -> str | None:
    """Detect a DeepSeek-supported image type from file contents."""
    try:
        with open(path, "rb") as image_file:
            return detect_image_mime_bytes(image_file.read(16))
    except OSError:
        return None


def encode_image_bytes_data_uri(data: bytes) -> str:
    """Encode validated image bytes as a base64 data URI."""
    mime = detect_image_mime_bytes(data)
    if mime not in SUPPORTED_IMAGE_MIMES:
        raise ValueError("Unsupported image content; expected JPEG, PNG, GIF, or WebP.")
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def encode_image_data_uri(path: str, max_bytes: int = MAX_INLINE_IMAGE_BYTES) -> str:
    """Encode a supported local image as a validated base64 data URI."""
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError(
            f"Image is too large for inline input ({size / 1024 / 1024:.1f} MiB); "
            f"maximum is {max_bytes / 1024 / 1024:.0f} MiB."
        )
    with open(path, "rb") as image_file:
        return encode_image_bytes_data_uri(image_file.read())


class VisualResolver:
    """Turn image sources into ``image_url``-compatible URL strings.

    Usage::

        resolver = VisualResolver(provider="stepfun", api_key="...", base_url="...")
        url = resolver.resolve("/path/to/img.png")
        # → "data:image/png;base64,iVBOR..."  (universal)
        # → "deepseekfile://file-api-..."     (DeepSeek Files API)
        # → "stepfile://file-abc123"          (StepFun optimisation)
    """

    def __init__(
        self,
        provider: str = "",
        api_key: str = "",
        base_url: str = "",
        file_upload_mode: str = "auto",
        file_upload_threshold_mb: float = 8.0,
        file_upload_expires_seconds: int = 86400,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.file_upload_mode = file_upload_mode.lower()
        self.file_upload_threshold_bytes = int(file_upload_threshold_mb * 1024 * 1024)
        self.file_upload_expires_seconds = file_upload_expires_seconds
        self._upload_cache: dict[tuple[str, int, int], str] = {}

    # ── public API ────────────────────────────────────────────────

    def resolve(self, source: str) -> str | None:
        """Return a provider reference for an image content block.

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
            mime = detect_image_mime(source)
            if mime not in SUPPORTED_IMAGE_MIMES:
                log.warning("Unsupported image content: %s", source)
                return None

            size = os.path.getsize(source)
            # Try provider-specific upload when configured or required by the
            # provider's inline-image size limit.
            uploaded = self._upload_to_provider(source, size)
            if uploaded:
                return uploaded

            # Fallback: base64 (every provider accepts this)
            try:
                return encode_image_data_uri(source)
            except (OSError, ValueError) as exc:
                log.warning("Image cannot be encoded '%s': %s", source, exc)
                return None

        log.warning("Image source not found or unsupported: %s", source)
        return None

    # ── provider-specific upload optimisations ────────────────────

    def _upload_to_provider(self, path: str, size: int) -> str | None:
        """Try to upload *path* via the provider's file API.

        Returns a provider-specific URL string (e.g. ``stepfile://...``)
        or ``None`` to fall back to base64.
        """
        provider = (self.provider or "").lower()
        try:
            if provider == "deepseek" and self._should_upload_deepseek(size):
                return self._upload_deepseek(path, size)
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

    def _should_upload_deepseek(self, size: int) -> bool:
        """Choose Files API only when requested, economical, or mandatory."""
        if self.file_upload_mode == "never":
            return False
        if size > MAX_INLINE_IMAGE_BYTES:
            return True
        if self.file_upload_mode == "always":
            return True
        return (
            self.file_upload_mode == "auto"
            and size >= self.file_upload_threshold_bytes
        )

    def _upload_deepseek(self, path: str, size: int) -> str:
        """Upload a local image to DeepSeek Files API and return a sentinel URI."""
        import requests
        from urllib.parse import urlparse

        if size > MAX_DEEPSEEK_FILE_BYTES:
            raise ValueError(
                f"Image exceeds DeepSeek Files API limit "
                f"({size / 1024 / 1024:.1f} MiB > 64 MiB)."
            )

        stat = os.stat(path)
        cache_key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
        cached = self._upload_cache.get(cache_key)
        if cached:
            return cached

        parsed = urlparse(self.base_url or "https://api.deepseek.com")
        base_path = parsed.path.rstrip("/")
        if base_path.endswith("/v1"):
            base_path = base_path[:-3]
        files_url = f"{parsed.scheme or 'https'}://{parsed.netloc or 'api.deepseek.com'}{base_path}/files"
        mime = detect_image_mime(path) or "application/octet-stream"
        data: dict[str, str] = {"purpose": "user_data"}
        if self.file_upload_expires_seconds > 0:
            seconds = self.file_upload_expires_seconds
            if not 3600 <= seconds <= 2592000:
                raise ValueError("DeepSeek file expiration must be between 3600 and 2592000 seconds.")
            data["expires_after[anchor]"] = "created_at"
            data["expires_after[seconds]"] = str(seconds)

        with open(path, "rb") as image_file:
            response = requests.post(
                files_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (os.path.basename(path), image_file, mime)},
                data=data,
                timeout=600,
            )
        response.raise_for_status()
        file_id = response.json().get("id", "")
        if not isinstance(file_id, str) or not file_id.startswith("file-api-"):
            raise ValueError("DeepSeek Files API returned an invalid file_id.")
        resolved = f"{DEEPSEEK_FILE_URI_PREFIX}{file_id}"
        self._upload_cache[cache_key] = resolved
        log.info("Uploaded %s → DeepSeek file %s", path, file_id)
        return resolved

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
        """Backward-compatible wrapper around validated data URI encoding."""
        return encode_image_data_uri(path)
