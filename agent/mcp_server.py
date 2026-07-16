"""Manage MCP child processes with loop-independent, concurrent-safe I/O.

The subprocess pipes are synchronous and therefore survive the short event loop
used during MCP discovery.  Exactly one reader thread owns stdout and dispatches
JSON-RPC responses by request id, so concurrent tool calls cannot steal each
other's responses and a timed-out caller never leaves a blocked reader behind.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import json
import os
import shutil
import subprocess
import threading
from typing import Any

from logger import get_logger, redact_sensitive

log = get_logger(__name__)


def _resolve_cmd(command: str) -> str:
    resolved = shutil.which(command)
    return resolved or command


class MCPServer:
    """Manage one MCP server process and dispatch JSON-RPC responses by id."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict | None = None,
        request_timeout: float = 120.0,
    ) -> None:
        self.name = name
        self._command = command
        self._args = args or []
        self._env = env
        self._request_timeout = max(0.001, float(request_timeout))
        self._proc: subprocess.Popen | None = None
        self._request_id = 0
        self._tools: list[dict[str, Any]] = []
        self._started = False
        self._killed_on_timeout = False

        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, Future[dict[str, Any]]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return

        display_cmd = redact_sensitive(f"{self._command} {' '.join(self._args)}".strip())
        log.info("Starting MCP server '%s': %s", self.name, display_cmd)
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
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"mcp-stdout-{self.name}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"mcp-stderr-{self.name}",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()

        try:
            await self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "linar-agent", "version": "0.1.0"},
            })
            await self._send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })
            self._tools = await self._do_list_tools()
        except Exception:
            self.kill()
            raise

        self._started = True
        log.info("MCP server '%s' ready: %d tools", self.name, len(self._tools))

    def stop(self) -> None:
        """Gracefully stop the process and fail outstanding calls."""
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
        self._fail_pending(RuntimeError(f"MCP server '{self.name}' stopped"))
        self._started = False

    def kill(self) -> None:
        """Immediately kill the process and fail outstanding calls."""
        if self._proc is None:
            return
        if self._proc.returncode is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        self._close_pipes_sync()
        self._fail_pending(RuntimeError(f"MCP server '{self.name}' killed"))
        self._started = False

    def force_kill(self) -> None:
        """Alias used by the registry reload path."""
        self.kill()

    def _close_pipes_sync(self) -> None:
        if self._proc is None:
            return
        for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            if pipe is not None and not pipe.closed:
                try:
                    pipe.close()
                except OSError:
                    pass

    # ── public API ───────────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        if not self._started or self._proc is None:
            raise RuntimeError(f"MCP server '{self.name}' not running")

        response = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if "error" in response:
            raise RuntimeError(f"MCP tool '{name}' failed: {response['error']}")

        parts: list[str] = []
        for item in response.get("result", response).get("content", []):
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "resource":
                parts.append(item.get("resource", {}).get("text", str(item)))
        return "\n".join(parts)

    # ── JSON-RPC transport ──────────────────────────────────────────────

    async def _send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, ensure_ascii=False) + "\n"
        await asyncio.to_thread(self._write_stdin, line)

    def _write_stdin(self, data: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError(f"MCP server '{self.name}' not running")
        try:
            with self._write_lock:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"MCP server '{self.name}' write failed: {exc}") from exc

    def _next_request_id(self) -> int:
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    async def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_request_id()
        pending: Future[dict[str, Any]] = Future()
        with self._pending_lock:
            self._pending[request_id] = pending
        try:
            await self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                **({"params": params} if params is not None else {}),
            })
            return await asyncio.wait_for(
                asyncio.wrap_future(pending),
                timeout=self._request_timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"MCP request '{method}' timed out after "
                f"{self._request_timeout:.3g}s for '{self.name}'"
            ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _reader_loop(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            for raw_line in self._proc.stdout:
                raw = raw_line.rstrip()
                if not raw:
                    continue
                try:
                    response = json.loads(raw)
                except json.JSONDecodeError as exc:
                    log.warning("MCP stdout JSON error for '%s': %s", self.name, exc)
                    continue
                request_id = response.get("id")
                if not isinstance(request_id, int):
                    log.debug(
                        "MCP notification from '%s': %s",
                        self.name,
                        response.get("method"),
                    )
                    continue
                with self._pending_lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None and not pending.done():
                    pending.set_result(response)
        except (OSError, ValueError) as exc:
            log.debug("MCP stdout reader stopped for '%s': %s", self.name, exc)
        finally:
            self._fail_pending(RuntimeError(f"MCP server '{self.name}' stdout closed"))

    def _fail_pending(self, error: Exception) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)

    async def _do_list_tools(self) -> list[dict[str, Any]]:
        response = await self._request("tools/list")
        if "error" in response:
            raise RuntimeError(
                f"MCP server '{self.name}' tools/list failed: {response['error']}"
            )
        result = response.get("result", {})
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", tool.get("input_schema", {})),
            }
            for tool in result.get("tools", [])
        ]

    def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for raw_line in self._proc.stderr:
                text = raw_line.rstrip()
                if text and not self._killed_on_timeout:
                    log.debug("[MCP:%s stderr] %s", self.name, text)
        except (OSError, ValueError):
            pass
