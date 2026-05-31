"""Tool that lets the agent analyze images using a vision-capable model.

Reads the ``vision`` section from config.yaml to determine which model/provider
to use.  The vision model is called via its OpenAI-compatible API endpoint.
"""

from .tool import Tool
from config import load_config
from openai import OpenAI
import base64
import os
import mimetypes
import logging

log = logging.getLogger(__name__)

# Some vision APIs (e.g. GLM-4V) may have stricter limits — 20 MB is a safe
# upper bound for most providers.
_MAX_IMAGE_SIZE = 20 * 1024 * 1024

_SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


class Tool_VisionQuery(Tool):
    name: str = "vision_query"
    description: str = (
        "Analyze images using a vision-capable model. "
        "Use this when the user asks about the content of image files, "
        "screenshots, photos, diagrams, or any visual data."
    )
    tool_schema: dict = {
        "name": "vision_query",
        "description": (
            "Analyze images using a vision-capable model. "
            "Use this when the user asks about the content of image files, "
            "screenshots, photos, diagrams, or any visual data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "File paths of the images to analyze. "
                        "Supported: JPEG, PNG, GIF, BMP, WebP."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Question or instruction about the image(s). "
                        "Defaults to 'Describe this image in detail.'"
                    ),
                },
            },
            "required": ["images"],
        },
    }

    def execute(self, images: list[str] | None = None,
                prompt: str = "Describe this image in detail.") -> dict:
        if not images:
            return {"error": "No image paths provided."}

        cfg = load_config()
        vision = cfg.get("vision", {})
        if not vision.get("enabled"):
            return {"error": (
                "Vision capability is not enabled. "
                "Set vision.enabled: true in config.yaml and configure a vision provider."
            )}

        base_url = vision.get("base_url", "")
        api_key = vision.get("api_key", "")
        model = vision.get("model", "")
        temperature = vision.get("temperature", 0.7)
        max_images = vision.get("max_images", 5)

        if not api_key or not model:
            return {"error": (
                "Vision model not configured. "
                "Set vision.provider and vision.model in config.yaml."
            )}

        if len(images) > max_images:
            return {"error": f"Too many images ({len(images)}). Maximum: {max_images}."}

        # ── read & encode images ──
        encoded = []
        for path in images:
            path = path.strip()
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
            encoded.append((mime, b64))

        # ── build multimodal content ──
        content = [{"type": "text", "text": prompt}]
        for mime, b64 in encoded:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })

        # ── call vision model API ──
        try:
            client = OpenAI(base_url=base_url, api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=2048,
            )
            text = response.choices[0].message.content or ""
            log.info(
                "Vision query: model=%s, images=%d, tokens=%s",
                model, len(images),
                getattr(response, "usage", None),
            )
            return {"analysis": text}
        except Exception as e:
            log.error("Vision API call failed: %s", e)
            return {"error": f"Vision API error: {e}"}
