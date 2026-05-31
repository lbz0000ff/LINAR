"""MCPServer — manage an MCP server subprocess.

Starts a child process, speaks JSON-RPC over its stdin/stdout,
and exposes its tools as a list of dicts.

Usage::

    server = MCPServer("github", "npx", ["-y", "@modelcontextprotocol/server-github"])
    server.start()
    print(server.list_tools())
    result = server.call_tool("search_repos", {"query": "mcp"})
    server.stop()
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from logger import get_logger

log = get_logger(__name__)


def _resolve_cmd(command: str) -> str:
    """Resolve a command name to its full path (Windows PATH workaround)."""
    resolved = shutil.which(command)
    if resolved:
        return resolved
    return command


class MCPServer:
    """Synchronous wrapper around an MCP server child process."""

    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict | None = None):
        self.name = name
        self._command = command
        self._args = args or []
        self._env = env
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list[dict] = []
        self._started = False
        self._killed_on_timeout = False  # set by tool_registry when startup timed out

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        """Launch the subprocess, perform the initialize handshake,
        and fetch the tool list."""
        if self._started:
            return

        log.info("Starting MCP server '%s': %s %s", self.name, self._command, " ".join(self._args))
        proc_env = None
        if self._env:
            proc_env = os.environ.copy()
            proc_env.update(self._env)
        self._proc = subprocess.Popen(
            [_resolve_cmd(self._command)] + self._args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
        )

        # ── initialize ──
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "lily-agent", "version": "0.1.0"},
        }})
        init_resp = self._recv()
        if init_resp is None:
            self._dump_stderr()
            raise RuntimeError(f"MCP server '{self.name}' failed to initialize (stderr above)")

        # ── initialized notification (no response expected) ──
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # ── list tools ──
        self._tools = self._do_list_tools()
        log.info("MCP server '%s' ready: %d tools", self.name, len(self._tools))
        self._started = True

    def stop(self):
        """Terminate the subprocess and close pipes."""
        if not self._started or self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        # Close pipes so any blocked readline() in background threads
        # wakes up immediately instead of hanging until the 300s _recv timeout.
        for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            if pipe and not pipe.closed:
                try:
                    pipe.close()
                except OSError:
                    pass
        self._started = False
        log.info("MCP server '%s' stopped", self.name)

    def kill(self):
        """Kill the subprocess immediately — no graceful wait."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=3)
        for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            if pipe and not pipe.closed:
                try:
                    pipe.close()
                except OSError:
                    pass
        self._started = False
        log.info("MCP server '%s' killed", self.name)

    # ── public interface ─────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Return cached tool list [{name, description, inputSchema}, ...]."""
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the server and return the text result."""
        if not self._started or self._proc is None:
            raise RuntimeError(f"MCP server '{self.name}' not running")

        self._request_id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        resp = self._recv()
        if resp is None:
            self._dump_stderr()
            raise RuntimeError(f"MCP tool '{name}' returned no response (stderr above)")

        # content is [{type: "text", text: "..."}, ...]
        parts = []
        for item in resp.get("result", resp).get("content", []):
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "resource":
                resource = item.get("resource", {})
                parts.append(resource.get("text", str(resource)))
        return "\n".join(parts)

    # ── internals ────────────────────────────────────────────────────────

    def _do_list_tools(self):
        self._request_id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
        })
        resp = self._recv()
        if resp is None:
            self._dump_stderr()
            raise RuntimeError(f"MCP server '{self.name}' tools/list failed (stderr above)")
        result = resp.get("result", {})
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in result.get("tools", [])
        ]

    def _send(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(line.encode("utf-8"))
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                log.warning("MCP _send failed for '%s': %s", self.name, e)
                raise RuntimeError(f"MCP server '{self.name}' write failed: {e}")

    def _recv(self, timeout: float = 300.0) -> dict | None:
        """Read one JSON-RPC response line from stdout with a timeout.

        Skips non-JSON lines (e.g. startup banners printed by the server
        before it enters stdio protocol mode).

        Uses a daemon thread to read from the pipe so the agent never hangs
        indefinitely if the subprocess stops responding.
        """
        if self._proc is None or self._proc.stdout is None:
            return None

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("MCP _recv timed out (%.1fs) for '%s'", timeout, self.name)
                return None

            q: queue.Queue = queue.Queue()

            def _reader():
                try:
                    line = self._proc.stdout.readline()
                    q.put(line)
                except Exception as e:
                    q.put(e)

            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            t.join(max(remaining, 0.1))

            if t.is_alive():
                log.warning("MCP _recv timed out (%.1fs) for '%s'", timeout, self.name)
                return None

            result = q.get_nowait()
            if isinstance(result, Exception):
                raise result
            if not result:
                return None

            raw = result.decode("utf-8", errors="replace").strip()
            if not raw:
                continue  # skip empty lines

            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                log.debug("MCP _recv skipping non-JSON line: %.100s", raw)
                continue  # skip banner / debug output

    def _dump_stderr(self):
        """Print whatever the subprocess wrote to stderr (for debugging)."""
        if self._proc is None or self._proc.stderr is None:
            return
        # Suppress stderr when the server was killed on startup timeout —
        # the retry noise (e.g. "ComfyUI availability check attempt 1/5...")
        # is not useful.
        if self._killed_on_timeout:
            return
        if not self._proc.stderr.closed:
            try:
                err = self._proc.stderr.read().decode("utf-8", errors="replace")
                if err.strip():
                    print(f"[MCP:{self.name} stderr]\n{err}", file=sys.stderr)
            except (OSError, ValueError):
                pass  # pipe already closed or broken
