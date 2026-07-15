from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tool_registry
from tool.mcp_tools.mcp_tool import MCPTool


def test_search_mcp_tools_replace_native_web_toolset(monkeypatch) -> None:
    search_tools = {
        "mcp_stepsearch_web_search": MCPTool(
            server=None,
            name="mcp_stepsearch_web_search",
            original_name="web_search",
            description="search",
            input_schema={},
            is_search_tool=True,
        ),
        "mcp_stepsearch_web_fetch": MCPTool(
            server=None,
            name="mcp_stepsearch_web_fetch",
            original_name="web_fetch",
            description="fetch",
            input_schema={},
            is_search_tool=True,
        ),
    }
    monkeypatch.setattr(tool_registry, "_init_mcp_servers", lambda: search_tools)

    tools = tool_registry.get_tools(["web"], include_mcp=True)

    assert set(search_tools).issubset(tools)
    assert "web_search" not in tools
    assert "web_fetch" not in tools


def test_non_search_mcp_does_not_replace_or_join_web_toolset(monkeypatch) -> None:
    browser = MCPTool(
        server=None,
        name="mcp_playwright_browser_navigate",
        original_name="browser_navigate",
        description="browser",
        input_schema={},
    )
    monkeypatch.setattr(
        tool_registry,
        "_init_mcp_servers",
        lambda: {browser.name: browser},
    )

    tools = tool_registry.get_tools(["web"], include_mcp=True)

    assert "web_search" in tools
    assert "web_fetch" in tools
    assert browser.name not in tools


def test_mcp_search_marker_defaults_to_false() -> None:
    tool = MCPTool(
        server=None,
        name="mcp_example_tool",
        original_name="tool",
        description="example",
        input_schema={},
    )

    assert tool.is_search_tool is False
