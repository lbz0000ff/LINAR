"""Regression tests for concurrent MCP JSON-RPC response handling."""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server import MCPServer


_FAKE_MCP_SERVER = textwrap.dedent(
    r"""
    import json
    import sys
    import threading
    import time

    output_lock = threading.Lock()

    def send(message, delay=0.0):
        time.sleep(delay)
        with output_lock:
            sys.stdout.write(json.dumps(message) + "\n")
            sys.stdout.flush()

    for raw_line in sys.stdin:
        request = json.loads(raw_line)
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [{
                        "name": "echo",
                        "description": "echo",
                        "inputSchema": {"type": "object", "properties": {}},
                    }],
                },
            })
        elif method == "tools/call":
            arguments = request["params"]["arguments"]
            value = arguments["value"]
            if value == "drop":
                continue
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": value}]},
            }
            threading.Thread(
                target=send,
                args=(response, float(arguments.get("delay", 0.0))),
                daemon=True,
            ).start()
    """
)


def _server(*, request_timeout: float | None = None) -> MCPServer:
    kwargs = {}
    if request_timeout is not None:
        kwargs["request_timeout"] = request_timeout
    return MCPServer("fake", sys.executable, ["-u", "-c", _FAKE_MCP_SERVER], **kwargs)


def test_concurrent_calls_match_out_of_order_responses_by_request_id() -> None:
    async def scenario() -> None:
        server = _server()
        await server.start()
        try:
            slow = asyncio.create_task(
                server.call_tool("echo", {"value": "slow", "delay": 0.15})
            )
            await asyncio.sleep(0.02)
            fast = asyncio.create_task(
                server.call_tool("echo", {"value": "fast", "delay": 0.0})
            )

            assert await fast == "fast"
            assert await slow == "slow"
        finally:
            server.stop()

    asyncio.run(scenario())


def test_timed_out_call_does_not_consume_the_next_response() -> None:
    async def scenario() -> None:
        server = _server(request_timeout=0.2)
        await server.start()
        try:
            with pytest.raises(TimeoutError, match="timed out"):
                await server.call_tool("echo", {"value": "drop"})

            assert await server.call_tool(
                "echo", {"value": "after-timeout", "delay": 0.0}
            ) == "after-timeout"
        finally:
            server.stop()

    asyncio.run(scenario())
