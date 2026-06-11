"""FastAPI application — unified HTTP + WebSocket entry point."""

import os
import sys
import logging
from pathlib import Path

# Ensure agent/ is on sys.path so database, config, etc. are importable
_agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from .session_manager import SessionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    sm = SessionManager()
    sm.initialize()
    app.state.sm = sm
    yield
    sm.shutdown()


app = FastAPI(title="EchoLily", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── register routers ────────────────────────────────────────

from .routes import ws, sessions, config, upload

app.include_router(ws.router)
app.include_router(sessions.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(upload.router)


# ── static files (production: serve Vue dist/) ──────────────

_DIST = Path(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "webui-vue", "dist",
))
_DIST_EXISTS = _DIST.is_dir()


def _mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".json": "application/json",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }.get(ext, "application/octet-stream")


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def _static_response(path: Path, media_type: str):
    return FileResponse(str(path), media_type=media_type, headers=_CORS_HEADERS)


@app.get("/")
async def serve_index():
    if not _DIST_EXISTS:
        return Response("Not found", status_code=404)
    index = _DIST / "index.html"
    if index.is_file():
        return _static_response(index, "text/html")
    return Response("Not found", status_code=404)


@app.get("/assets/{filepath:path}")
async def serve_asset(filepath: str):
    if not _DIST_EXISTS:
        return Response("Not found", status_code=404)
    file = _DIST / "assets" / filepath
    if file.is_file():
        return _static_response(file, _mime(filepath))
    return Response("Not found", status_code=404)


@app.get("/favicon.svg")
async def serve_favicon():
    if not _DIST_EXISTS:
        return Response("Not found", status_code=404)
    file = _DIST / "favicon.svg"
    if file.is_file():
        return _static_response(file, "image/svg+xml")
    return Response("Not found", status_code=404)


@app.get("/icons.svg")
async def serve_icons():
    if not _DIST_EXISTS:
        return Response("Not found", status_code=404)
    file = _DIST / "icons.svg"
    if file.is_file():
        return _static_response(file, "image/svg+xml")
    return Response("Not found", status_code=404)


@app.get("/{fullpath:path}")
async def serve_spa(fullpath: str):
    """SPA fallback: serve matching file or index.html."""
    if not _DIST_EXISTS:
        return Response("Not found", status_code=404)
    file = _DIST / fullpath
    if file.is_file():
        return _static_response(file, _mime(fullpath))
    index = _DIST / "index.html"
    if index.is_file():
        return _static_response(index, "text/html")
    return Response("Not found", status_code=404)
