"""Tool that describes images via an external vision API.

Fallback tool for when the main model is NOT multimodal
(``llm.multimodal`` is false or absent).  Calls the dedicated
``vision`` provider (e.g. 智谱 GLM-5V-Turbo) and returns a text
description.

When the main model IS multimodal, use ``Tool_Vision`` from
``tool_vision_vlm.py`` instead.
"""

from .tool import Tool
from config import load_config
from openai import OpenAI
import base64
import os
import logging

log = logging.getLogger(__name__)

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


class Tool_ImgToText(Tool):
    name: str = "img_to_text"
    description: str = (
        "Describe image contents via an external vision API. "
        "Use this when you need a text description of an image — "
        "it returns a detailed analysis of what the image shows."
    )
    tool_schema: dict = {
        "name": "img_to_text",
        "description": (
            "Describe image contents via an external vision API. "
            "Use this when you need a text description of an image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "File paths or URLs of the images to analyze. "
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
        is_multimodal = cfg.get("llm", {}).get("multimodal", False)

        if is_multimodal:
            return self._execute_multimodal(images, prompt, cfg)
        else:
            return self._execute_fallback(images, prompt, cfg)

    # ── multimodal: return image_uri for boundary attachment ───────

    def _execute_multimodal(self, images: list[str], prompt: str,
                            cfg: dict) -> dict:
        """Return ``image_uri`` for the prompt-builder to attach.

        The image is base64-encoded (or passed as URL) and returned as
        ``image_uri``.  ``agent.py``'s ``_build_llm_messages`` reads this
        from the observation store and attaches the image at the request
        boundary — no text-summary bottleneck, no message injection.
        """
        max_images = 99
        if len(images) > max_images:
            return {"error": f"Too many images ({len(images)}). Maximum: {max_images}."}

        image_uri: str | None = None

        for path in images:
            path = path.strip()
            if path.startswith(("http://", "https://")):
                image_uri = path
                break
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
            break  # single image per call

        if not image_uri:
            return {"error": "No valid image sources found."}

        log.info("Vision query (multimodal): 1 image URI resolved")
        return {
            "image_uri": image_uri,
            "message": "vision_query: image loaded",
        }

    # ── non-multimodal: call external vision API ────────────────────

    def _execute_fallback(self, images: list[str], prompt: str,
                          cfg: dict) -> dict:
        """Encode images and call the dedicated vision provider API."""
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

        # ── read & encode ──
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
        content: list = [{"type": "text", "text": prompt}]
        for mime, b64 in encoded:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })

        # ── call external vision API ──
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
                "Vision query (fallback): model=%s, images=%d, tokens=%s",
                model, len(images),
                getattr(response, "usage", None),
            )
            return {"analysis": text}
        except Exception as e:
            log.error("Vision API call failed (fallback): %s", e)
            return {"error": f"Vision API error: {e}"}
