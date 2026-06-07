"""EchoLily WebSocket server — bridges Agent to browser via WS + HTTP."""
import os
import sys
import json
import queue
import threading
import asyncio

import websockets
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ── Agent init ───────────────────────────────────────────────
_AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
sys.path.insert(0, _AGENT_DIR)

from config import load_config
from logger import get_logger
from orchestrator import Orchestrator
from skill import load_skills_from_markdown
from tool_registry import get_tools
from agent import Agent
import database as db

_AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent")
_CONFIG_PATH = os.path.join(_AGENT_DIR, "config.yaml")

log = get_logger(__name__)

# ── Global state ─────────────────────────────────────────────
_ws_clients: set[websockets.WebSocketServerProtocol] = set()
_input_queue: queue.Queue[str] = queue.Queue()


def _broadcast(event: dict):
    """Send a JSON event to all connected WS clients."""
    msg = json.dumps(event, ensure_ascii=False)
    for ws in _ws_clients.copy():
        try:
            asyncio.run_coroutine_threadsafe(ws.send(msg), _ws_loop)
        except Exception:
            pass


def _run_agent():
    """Agent background thread."""
    cfg = load_config()
    enabled = cfg.get("tools", {}).get("enabled_sets", None)
    tools = get_tools(enabled)

    skills_dir = os.path.join(os.path.dirname(_AGENT_DIR), "skills")
    if os.path.isdir(skills_dir):
        load_skills_from_markdown(skills_dir)

    agent = Agent(tools=tools)
    orchestrator = Orchestrator(agent)

    # Wire emit → broadcast
    agent.emit = lambda e: _broadcast(e)

    log.info("Agent ready")
    _broadcast({"type": "ready"})

    while True:
        text = _input_queue.get()
        if text is None:
            break
        orchestrator.start(text)
        _broadcast({"type": "ready"})


# ── WS handler ───────────────────────────────────────────────

async def ws_handler(ws):
    _ws_clients.add(ws)
    log.info("WS client connected (%d total)", len(_ws_clients))
    try:
        async for raw in ws:
            data = json.loads(raw)
            t = data.get("type")
            if t == "message":
                text = data.get("data", "")
                files = data.get("files", [])
                files = data.get("files", [])
                if files:
                    text += " [附件] " + ", ".join(files)
                _input_queue.put(text)


            elif t == "list_sessions":
                sessions = db.get_recent_sessions(50)
                await ws.send(json.dumps({"type": "sessions", "data": sessions}, ensure_ascii=False, default=str))
            elif t == "get_session":
                sid = int(data.get("id", 0))
                msgs = db.get_session_messages(sid)
                sess = db.get_session_by_id(sid)
                title = sess.get("title", f"Session #{sid}") if sess else ""
                await ws.send(json.dumps({"type": "session_msgs", "session_id": sid, "title": title, "data": msgs}, ensure_ascii=False, default=str))
            elif t == "get_config":
                cfg_path = _CONFIG_PATH
                with open(cfg_path, "r", encoding="utf-8") as f:
                    text = f.read()
                await ws.send(json.dumps({"type": "config", "data": text}, ensure_ascii=False))
            elif t == "save_config":
                cfg_path = _CONFIG_PATH
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(data.get("data", ""))
                await ws.send(json.dumps({"type": "config_saved"}, ensure_ascii=False))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _ws_clients.discard(ws)
        log.info("WS client disconnected (%d remaining)", len(_ws_clients))


# ── HTTP server (serves static files) ─────────────────────────

_HTTP_HOST = "127.0.0.1"
_HTTP_PORT = 8080
_WS_PORT = 8081


def _start_http():
    import cgi, io, urllib.parse
    web_dir = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(os.path.dirname(_AGENT_DIR), ".temp", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    os.chdir(web_dir)

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            # Serve uploaded files from .temp/uploads/
            if self.path.startswith("/uploads/"):
                fname = os.path.basename(self.path)
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    self.send_response(200)
                    mt = self.guess_type(fpath)
                    self.send_header("Content-Type", mt or "application/octet-stream")
                    self.send_header("Content-Length", os.path.getsize(fpath))
                    self.end_headers()
                    with open(fpath, "rb") as f:
                        self.wfile.write(f.read())
                    return
                self.send_response(404)
                self.end_headers()
                return
            super().do_GET()

        def do_POST(self):
            if self.path == "/upload":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                # Expect multipart or raw file data
                content_type = self.headers.get("Content-Type", "")
                if "multipart" in content_type:
                    import cgi
                    fs = cgi.FieldStorage(fp=io.BytesIO(body), headers=self.headers, environ={"REQUEST_METHOD": "POST"})
                    fitem = fs.getfirst("file")
                    if fitem and fitem.filename:
                        import mimetypes
                        safe_name = os.path.basename(fitem.filename)
                        dest = os.path.join(upload_dir, safe_name)
                        with open(dest, "wb") as f:
                            f.write(fitem.file.read())
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"path": dest}).encode())
                        return
                else:
                    # Raw file upload—filename in X-Filename header
                    fname = self.headers.get("X-Filename", "upload.bin")
                    safe_name = os.path.basename(fname)
                    dest = os.path.join(upload_dir, safe_name)
                    with open(dest, "wb") as f:
                        f.write(body)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"path": dest}).encode())
                    return
            self.send_response(405)
            self.end_headers()

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

    server = HTTPServer((_HTTP_HOST, _HTTP_PORT), Handler)
    log.info("HTTP server: http://%s:%d", _HTTP_HOST, _HTTP_PORT)
    server.serve_forever()


async def _ws_main():
    try:
        async with websockets.serve(ws_handler, _HTTP_HOST, _WS_PORT):
            log.info("WS server: ws://%s:%d", _HTTP_HOST, _WS_PORT)
            global _ws_loop
            _ws_loop = asyncio.get_running_loop()
            await asyncio.Future()
    except Exception as e:
        log.error("WS server failed: %s", e)
        raise


def main():
    # Start Agent thread
    t = threading.Thread(target=_run_agent, daemon=True, name="agent")
    t.start()

    # Start HTTP server thread
    threading.Thread(target=_start_http, daemon=True, name="http").start()

    # Start WebSocket server (main thread)
    asyncio.run(_ws_main())


if __name__ == "__main__":
    main()
