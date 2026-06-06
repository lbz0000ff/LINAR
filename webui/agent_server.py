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
            if data.get("type") == "message":
                text = data.get("data", "")
                _input_queue.put(text)
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
    web_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(web_dir)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

    server = HTTPServer((_HTTP_HOST, _HTTP_PORT), Handler)
    log.info("HTTP server: http://%s:%d", _HTTP_HOST, _HTTP_PORT)
    server.serve_forever()


async def _ws_main():
    async with websockets.serve(ws_handler, _HTTP_HOST, _WS_PORT):
        log.info("WS server: ws://%s:%d", _HTTP_HOST, _WS_PORT)
        global _ws_loop
        _ws_loop = asyncio.get_running_loop()
        await asyncio.Future()  # run forever


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
