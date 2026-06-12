"""WebSocket endpoint — async bridge between WS clients and SessionManager.

Maintains the same protocol as the old agent_server.py.
"""

import os
import json
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import database as db

router = APIRouter()
log = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config.yaml",
)


async def _send(ws: WebSocket, data: dict):
    await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    sm = ws.app.state.sm

    sub_queue = sm.subscribe()
    active_session_id: int | None = None

    # ── Background task: drain event queue → WS ──
    async def send_events():
        while True:
            try:
                event = await sub_queue.get()
                await _send(ws, event)
            except Exception:
                break

    sender = asyncio.create_task(send_events())

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            t = data.get("type")

            if t == "message":
                text = data.get("data", "")
                if active_session_id is not None:
                    session = sm.get_or_create(active_session_id)
                    session.input_queue.put_nowait(text)

            elif t == "new_session":
                sid = db.create_session()
                sm.get_or_create(sid)
                await _send(ws, {"type": "new_session_created", "session_id": sid})

            elif t == "switch_session":
                sid = int(data.get("id", 0))
                active_session_id = sid
                sm.get_or_create(sid)
                await _send(ws, {"type": "session_switched", "session_id": sid})

            elif t == "switch_permission_mode":
                mode = data.get("mode", "safe")
                session = sm.get(active_session_id) if active_session_id else None
                if session:
                    session.agent.permissions.switch_mode(mode)
                await _send(ws, {"type": "permission_mode", "mode": mode})

            elif t == "stop":
                session = sm.get(active_session_id) if active_session_id else None
                if session:
                    session.agent.interrupt()

            elif t == "ask_user_response":
                response = data.get("response", "")
                session = sm.get(active_session_id) if active_session_id else None
                if session:
                    session.resolve_ask_user(response)
                await _send(ws, {"type": "ask_user_response_received"})

            elif t == "permission_response":
                action = data.get("action", "deny_once")
                session = sm.get(active_session_id) if active_session_id else None
                if session:
                    session.resolve_permission(action)

            elif t == "list_sessions":
                sessions = db.get_recent_sessions(50)
                await _send(ws, {"type": "sessions", "data": sessions})

            elif t == "get_session":
                sid = int(data.get("id", active_session_id or 0))
                msgs = db.get_session_messages(sid)
                sess = db.get_session_by_id(sid)
                title = sess.get("title", f"Session #{sid}") if sess else ""
                await _send(ws, {
                    "type": "session_msgs", "session_id": sid,
                    "title": title, "data": msgs,
                })

            elif t == "rename_session":
                sid = int(data.get("id", 0))
                title = data.get("title", "")
                db.update_session_title(sid, title)
                await _send(ws, {"type": "session_renamed", "session_id": sid, "title": title})

            elif t == "delete_session":
                sid = int(data.get("id", 0))
                db.delete_session(sid)
                sm.remove(sid)
                await _send(ws, {"type": "session_deleted", "session_id": sid})

            elif t == "get_config_json":
                try:
                    import yaml
                    with open(_CONFIG_PATH, encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    await _send(ws, {"type": "config_json", "data": cfg})
                except Exception as e:
                    log.error("get_config_json: %s", e)
                    await _send(ws, {"type": "config_json", "data": {"error": str(e)}})

            elif t == "get_config":
                with open(_CONFIG_PATH, encoding="utf-8") as f:
                    text = f.read()
                await _send(ws, {"type": "config", "data": text})

            elif t == "save_config":
                with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                    f.write(data.get("data", ""))
                await _send(ws, {"type": "config_saved"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("WS error: %s", e)
    finally:
        sender.cancel()
        sm.unsubscribe(sub_queue)
        # 页面关闭时打断正在运行中的 agent，避免浪费
        if active_session_id is not None:
            session = sm.get(active_session_id)
            if session:
                session.stop()
