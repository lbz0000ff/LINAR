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
import shutil
import subprocess
import sys
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

    def __init__(self, name: str, command: str, args: list[str] | None = None):
        self.name = name
        self._command = command
        self._args = args or []
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list[dict] = []
        self._started = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        """Launch the subprocess, perform the initialize handshake,
        and fetch the tool list."""
        if self._started:
            return

        log.info("Starting MCP server '%s': %s %s", self.name, self._command, " ".join(self._args))
        self._proc = subprocess.Popen(
            [_resolve_cmd(self._command)] + self._args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
        """Terminate the subprocess."""
        if not self._started or self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._started = False
        log.info("MCP server '%s' stopped", self.name)

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
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()

    def _recv(self) -> dict | None:
        """Read one JSON-RPC response line from stdout."""
        if self._proc is None or self._proc.stdout is None:
            return None
        line = self._proc.stdout.readline()
        if not line:
            return None
        return json.loads(line.decode("utf-8"))

    def _dump_stderr(self):
        """Print whatever the subprocess wrote to stderr (for debugging)."""
        if self._proc and self._proc.stderr:
            err = self._proc.stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                print(f"[MCP:{self.name} stderr]\n{err}", file=sys.stderr)
