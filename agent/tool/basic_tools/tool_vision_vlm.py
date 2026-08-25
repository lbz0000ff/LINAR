"""Tool for multimodal (vision-language) models.

Registers an image for direct viewing by the main model. Remote URLs stay
remote. Local images are either uploaded through the provider Files API or
encoded inline according to the active resolver policy.
"""

import os
import logging
from typing import Any

from .tool import Tool
from visual import MAX_DEEPSEEK_FILE_BYTES, encode_image_data_uri

log = logging.getLogger(__name__)

class Tool_Vision(Tool):
    agent_ref: Any = None
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
                        "Supported: JPEG, PNG, GIF, WebP."
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

        # Keep remote URLs remote so providers can fetch them without LINAR
        # downloading and retaining every image locally.
        if path.startswith(("http://", "https://")):
            log.info("Vision (multimodal): remote URI %.80s", path)
            return {
                "image_uri": path,
                "message": "vision: image loaded",
            }

        # Local file
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}
        size = os.path.getsize(path)
        if size > MAX_DEEPSEEK_FILE_BYTES:
            return {"error": (
                f"File too large ({size / 1024 / 1024:.1f} MB): {path}. "
                f"Maximum: {MAX_DEEPSEEK_FILE_BYTES / 1024 / 1024:.0f} MB."
            )}
        try:
            resolver = getattr(self.agent_ref, "_visual_resolver", None)
            image_uri = resolver.resolve(path) if resolver else encode_image_data_uri(path)
        except (OSError, PermissionError, ValueError) as e:
            return {"error": f"Cannot read {path}: {e}"}
        if not image_uri:
            return {"error": (
                f"Cannot prepare image for the active provider: {path}. "
                "Check the Files API configuration or use an image up to 32 MiB."
            )}

        log.info("Vision (multimodal): 1 image encoded")
        return {
            "image_uri": image_uri,
            "message": "vision: image loaded",
        }
