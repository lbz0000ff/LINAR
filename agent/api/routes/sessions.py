"""HTTP session CRUD endpoints."""

import logging

from fastapi import APIRouter, Request

import database as db

router = APIRouter(tags=["sessions"])
log = logging.getLogger(__name__)


@router.get("/sessions")
async def list_sessions(limit: int = 50):
    return db.get_recent_sessions(limit)


@router.post("/sessions")
async def create_session(title: str = ""):
    sid = db.create_session(title)
    return {"session_id": sid}


@router.get("/sessions/{session_id}")
async def get_session(session_id: int):
    sess = db.get_session_by_id(session_id)
    if not sess:
        return {"error": "not found"}, 404
    return sess


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int):
    return db.get_session_messages(session_id)


@router.put("/sessions/{session_id}/title")
async def rename_session(session_id: int, title: str):
    db.update_session_title(session_id, title)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, request: Request):
    sm = request.app.state.sm
    sm.remove(session_id)
    db.delete_session(session_id)
    return {"ok": True}
