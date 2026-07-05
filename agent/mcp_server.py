"""MCPServer — manage an MCP server child process (thread-based I/O).

Uses ``subprocess.Popen`` + synchronous pipe I/O so the server
can be initialised in *any* event loop and safely called from
another (the TUI's agent loop).  I/O is dispatched to a thread
pool via ``asyncio.to_thread()`` to remain async-friendly.

The asyncio-subprocess approach was the root cause of
"coroutine was never awaited" at startup and
"'NoneType' object has no attribute 'send'" on tool calls —
child-process pipes created by ``asyncio.create_subprocess_exec``
are bound to the creating event loop and break after that loop
closes.

Usage::

    server = MCPServer("github", "npx", ["-y", "@modelcontextprotocol/server-github"])
    await server.start()
    print(server.list_tools())
    result = await server.call_tool("search_repos", {"query": "mcp"})
    await server.stop()
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from logger import get_logger

log = get_logger(__name__)


def _resolve_cmd(command: str) -> str:
    resolved = shutil.which(command)
    return resolved or command


class MCPServer:
    """Manages an MCP server child process via ``subprocess.Popen`` + thread I/O."""

    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict | None = None):
        self.name = name
        self._command = command
        self._args = args or []
        self._env = env
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list[dict] = []
        self._started = False
        self._killed_on_timeout = False

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self):
        if self._started:
            return

        log.info("Starting MCP server '%s': %s %s", self.name, self._command, " ".join(self._args))
        proc_env = None
        if self._env:
            proc_env = os.environ.copy()
            proc_env.update(self._env)

        self._proc = subprocess.Popen(
            [_resolve_cmd(self._command), *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
            text=True,
            encoding="utf-8",
        )

        # ── initialize handshake ──
        await self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "linar-agent", "version": "0.1.0"},
        }})
        init_resp = await self._recv()
        if init_resp is None:
            raise RuntimeError(f"MCP server '{self.name}' failed to initialize")

        # ── initialized notification ──
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # ── list tools ──
        self._tools = await self._do_list_tools()
        log.info("MCP server '%s' ready: %d tools", self.name, len(self._tools))
        self._started = True

        # background: drain stderr (fire-and-forget thread)
        import threading
        threading.Thread(
            target=self._drain_stderr, name=f"mcp-stderr-{self.name}", daemon=True,
        ).start()

    def stop(self):
        """Graceful stop — terminate, wait, close pipes."""
        if self._proc is None:
            return
        if self._proc.returncode is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
                self._proc.wait(timeout=3)
        self._close_pipes_sync()
        self._started = False

    def kill(self):
        """Immediate kill."""
        if self._proc is None:
            return
        if self._proc.returncode is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        self._close_pipes_sync()
        self._started = False

    def force_kill(self):
        """Alias for kill()."""
        self.kill()

    def _close_pipes_sync(self):
        if self._proc is None:
            return
        for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            if pipe is not None and not pipe.closed:
                try:
                    pipe.close()
                except OSError:
                    pass

    # ── public API ───────────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        if not self._started or self._proc is None:
            raise RuntimeError(f"MCP server '{self.name}' not running")

        self._request_id += 1
        await self._send({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        resp = await self._recv()
        if resp is None:
            raise RuntimeError(f"MCP tool '{name}' returned no response")

        parts = []
        for item in resp.get("result", resp).get("content", []):
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "resource":
                parts.append(item.get("resource", {}).get("text", str(item)))
        return "\n".join(parts)

    # ── I/O (dispatched to thread pool via asyncio.to_thread) ────────────

    async def _send(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        await asyncio.to_thread(self._write_stdin, line)

    def _write_stdin(self, data: str):
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError(f"MCP server '{self.name}' not running")
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"MCP server '{self.name}' write failed: {e}")

    async def _recv(self, timeout: float = 120.0) -> dict | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._read_stdout),
                timeout=timeout,
            )
            return json.loads(raw) if raw else None
        except asyncio.TimeoutError:
            log.warning("MCP _recv timed out (%.1fs) for '%s'", timeout, self.name)
            return None
        except json.JSONDecodeError as e:
            log.warning("MCP _recv JSON error for '%s': %s", self.name, e)
            return None

    def _read_stdout(self) -> str | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        try:
            line = self._proc.stdout.readline()
            return line.rstrip() if line else None
        except (OSError, ValueError):
            return None

    async def _do_list_tools(self):
        self._request_id += 1
        await self._send({
            "jsonrpc": "2.0", "id": self._request_id,
            "method": "tools/list",
        })
        resp = await self._recv()
        if resp is None:
            raise RuntimeError(f"MCP server '{self.name}' tools/list failed")
        result = resp.get("result", {})
        return [
            {"name": t["name"], "description": t.get("description", ""),
             "inputSchema": t.get("inputSchema", t.get("input_schema", {}))}
            for t in result.get("tools", [])
        ]

    def _drain_stderr(self):
        """Background thread: read stderr and log it."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for raw_line in iter(self._proc.stderr.readline, b""):
                if not raw_line:
                    break
                text = raw_line.rstrip()
                if text and not self._killed_on_timeout:
                    log.debug("[MCP:%s stderr] %s", self.name, text)
        except (OSError, ValueError):
            pass
