"""Per-session Agent lifecycle (pure async).

Each session gets its own async Agent task with isolated queues.
Events from all sessions are broadcast to subscriber queues,
which WS sender tasks drain and forward to browser clients.
"""

import os
import sys
import json
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import load_config
from logger import get_logger
from orchestrator import Orchestrator
from skill import load_skills_from_markdown
from tool_registry import get_tools
from agent import Agent
import database as db

log = get_logger(__name__)


class Session:
    """A single chat session with its own Agent + async task."""

    def __init__(self, session_id: int, tools: dict, broadcast_fn):
        self.session_id = session_id
        self.status = "idle"
        self.input_queue: asyncio.Queue = asyncio.Queue()

        self.agent = Agent(tools=tools)
        self.agent.session_id = session_id
        self.agent.emit = lambda e: broadcast_fn(e)

        # Permission / ask_user — resolved via asyncio.Future from the WS handler
        self._perm_future: asyncio.Future | None = None
        self._ask_future: asyncio.Future | None = None

        async def _on_confirm(tool_name: str, arguments: dict | str) -> bool | None:
            if tool_name == "ask_user":
                return True
            broadcast_fn({
                "type": "permission_request",
                "tool_name": tool_name,
                "arguments": arguments,
            })
            self._perm_future = asyncio.Future()
            try:
                result = await asyncio.wait_for(self._perm_future, timeout=120)
                if result is True:
                    return True
                if result == "always":
                    self.agent.permissions.set_override(tool_name, "allow")
                    return True
                if result == "never":
                    self.agent.permissions.set_override(tool_name, "deny")
                    return f"[REJECTED_BY_USER] Tool '{tool_name}' was blocked."
                return f"[REJECTED_BY_USER] Tool '{tool_name}' was not approved."
            except asyncio.TimeoutError:
                return None
            finally:
                self._perm_future = None

        async def _on_ask_user(prompt: str, password: bool = False, choices: list | None = None) -> str:
            broadcast_fn({
                "type": "ask_user_request",
                "prompt": prompt,
                "choices": choices or [],
            })
            self._ask_future = asyncio.Future()
            try:
                result = await asyncio.wait_for(self._ask_future, timeout=300)
                return result or ""
            except asyncio.TimeoutError:
                return ""
            finally:
                self._ask_future = None

        self.agent._confirm_callback = _on_confirm
        for t in tools.values():
            t.interactive_input = _on_ask_user

        self.orchestrator = Orchestrator(self.agent)

        # Load history from DB
        self.agent.switch_session(session_id)

        # Start processing task
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name=f"session-{session_id}")

        log.info("Session #%s created with async task", session_id)

    def resolve_permission(self, action: str):
        if self._perm_future and not self._perm_future.done():
            self._perm_future.set_result({
                "deny_once": False, "allow_once": True,
                "allow_session": "always", "deny_session": "never",
            }.get(action, False))

    def resolve_ask_user(self, response: str):
        if self._ask_future and not self._ask_future.done():
            self._ask_future.set_result(response)

    async def _run(self):
        """Agent async task: reads from input_queue, processes via Orchestrator."""
        while not self._stop.is_set():
            try:
                text = await asyncio.wait_for(self.input_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if text is None:
                break
            self.status = "processing"
            try:
                await self.orchestrator.start(text)
            except Exception as e:
                log.exception("Session #%s error", self.session_id)
                self.agent.emit({"type": "error", "data": str(e)})
                self.status = "error"
            else:
                self.status = "idle"

    def stop(self):
        self._stop.set()
        self.agent.interrupt()


class SessionManager:
    """Manages all active sessions. Routes events to WS subscriber queues."""

    def __init__(self):
        self.tools: dict = {}
        self._sessions: dict[int, Session] = {}
        self._broadcast_queues: list[asyncio.Queue] = []
        self._session_lock = asyncio.Lock()

    def init_light(self):
        """Fast init: native tools only, no MCP startup."""
        _agent_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        _project_root = os.path.dirname(_agent_dir)
        sys.path.insert(0, _agent_dir)

        cfg = load_config()
        enabled = cfg.get("tools", {}).get("enabled_sets", None)
        self._enabled = enabled
        # Native tools only — MCP starts later in background
        native = [s for s in (enabled or []) if s != "mcp"]
        self.tools = get_tools(native or None, include_mcp=False)

        skills_dir = os.path.join(_project_root, "skills")
        if os.path.isdir(skills_dir):
            load_skills_from_markdown(skills_dir)

        log.info("SessionManager initialized (native tools=%d)", len(self.tools))

    async def init_mcp_background(self):
        """Start MCP servers in background, update all sessions when ready."""
        log.info("Starting MCP servers in background...")
        from tool_registry import reload_mcp_servers
        try:
            full_tools = await asyncio.to_thread(reload_mcp_servers)
            self.tools = full_tools
            # Update all existing sessions with the full toolset
            for session in self._sessions.values():
                session.agent.tools = full_tools
                session.agent.llm.tools = full_tools
            log.info("MCP tools ready: %d total tools", len(full_tools))
        except Exception as e:
            log.warning("MCP background init failed: %s", e)

    def _broadcast_event(self, event: dict):
        """Put event into all subscriber queues."""
        dead = []
        for q in self._broadcast_queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._broadcast_queues.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._broadcast_queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._broadcast_queues:
            self._broadcast_queues.remove(q)

    def get_or_create(self, session_id: int) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(
                session_id, self.tools,
                broadcast_fn=self._broadcast_event,
            )
        return self._sessions[session_id]

    def get(self, session_id: int) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: int):
        session = self._sessions.pop(session_id, None)
        if session:
            session.stop()

    def shutdown(self):
        for sid in list(self._sessions.keys()):
            self.remove(sid)
        log.info("SessionManager shut down")
