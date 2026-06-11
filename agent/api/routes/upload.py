"""File upload and raw-file serving endpoints."""

import os
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["upload"])
log = logging.getLogger(__name__)

_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "..", "webui", "uploads",
)
_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


def _save_file(filename: str, data: bytes) -> str:
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(filename) or "upload.bin"
    dest = os.path.join(_UPLOAD_DIR, safe_name)
    counter = 1
    while os.path.exists(dest):
        p, e = os.path.splitext(safe_name)
        dest = os.path.join(_UPLOAD_DIR, f"{p}_{counter}{e}")
        counter += 1
    with open(dest, "wb") as f:
        f.write(data)
    log.info("Uploaded: %s (%d bytes)", dest, len(data))
    return dest


@router.post("/upload")
async def upload_file(request: Request):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file: UploadFile | None = form.get("file")
        if file is None:
            raise HTTPException(400, "No file field in multipart data")
        data = await file.read()
        if len(data) > _MAX_SIZE:
            raise HTTPException(413, "File too large")
        path = _save_file(file.filename or "upload.bin", data)
        return {"path": path}

    # Legacy: raw body + X-Filename header
    filename = request.headers.get("x-filename", "upload.bin")
    data = await request.body()
    if len(data) > _MAX_SIZE:
        raise HTTPException(413, "File too large")
    path = _save_file(filename, data)
    return {"path": path}


@router.get("/raw-file/{path:path}")
async def raw_file(path: str):
    """Serve arbitrary local files (for AI-generated image references)."""
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    return FileResponse(full)


@router.get("/uploads/{filename}")
async def uploaded_file(filename: str):
    """Serve files from the uploads directory."""
    full = os.path.join(_UPLOAD_DIR, os.path.basename(filename))
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    return FileResponse(full)
