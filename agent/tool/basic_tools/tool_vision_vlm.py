"""Tool for multimodal (vision-language) models.

Registers an image for direct viewing by the main model.  The image is
base64-encoded locally and returned as ``image_uri``; no external API
call is made.  ``agent.py``'s prompt builder picks the URI from the
observation store and attaches it at the request boundary.
"""

import base64
import os
import logging

from .tool import Tool

log = logging.getLogger(__name__)

_MAX_IMAGE_SIZE = 20 * 1024 * 1024
_SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
    ".bmp": "image/bmp", ".webp": "image/webp",
}


class Tool_Vision(Tool):
    name: str = "vision"
    description: str = (
        "Register an image for direct viewing. "
        "Use this when you want to examine an image file, screenshot, "
        "photo, or diagram — the image is made visible to you directly."
    )
    tool_schema: dict = {
        "name": "vision",
        "description": "Register an image for direct viewing by the multimodal model.",
        "parameters": {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": (
                        "Path or URL of the image to view. "
                        "Supported: JPEG, PNG, GIF, BMP, WebP."
                    ),
                },
            },
            "required": ["image"],
        },
    }

    def execute(self, image: str | None = None) -> dict:
        if not image:
            return {"error": "No image path provided."}

        path = str(image).strip()

        # Remote URL — pass through directly
        if path.startswith(("http://", "https://")):
            log.info("Vision (multimodal): remote URI %.80s", path)
            return {
                "image_uri": path,
                "message": "vision: image loaded",
            }

        # Local file
        ext = os.path.splitext(path)[1].lower()
        if ext not in _SUPPORTED_EXT:
            return {"error": (
                f"Unsupported format '{ext}' for: {path}. "
                f"Supported: {', '.join(sorted(_SUPPORTED_EXT))}."
            )}
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        size = os.path.getsize(path)
        if size > _MAX_IMAGE_SIZE:
            return {"error": (
                f"File too large ({size / 1024 / 1024:.1f} MB): {path}. "
                f"Maximum: {_MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB."
            )}
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
        except (OSError, PermissionError) as e:
            return {"error": f"Cannot read {path}: {e}"}
        mime = _MIME_MAP.get(ext, "image/png")
        image_uri = f"data:{mime};base64,{b64}"

        log.info("Vision (multimodal): 1 image encoded")
        return {
            "image_uri": image_uri,
            "message": "vision: image loaded",
        }
