"""``/reload_mcp`` — shut down and restart all MCP servers.

Use after installing new MCP servers or tools without restarting the TUI.
"""

from . import Command


class ReloadMCPCommand(Command):
    name = "reload_mcp"
    aliases = ["reload_mcp_servers"]
    description = "Reload all MCP servers (shut down + restart)"

    def execute(self, args: str, terminal) -> bool:
        from tool_registry import reload_mcp_servers, get_tools

        terminal.console.print("\n  Reloading MCP servers...")
        try:
            tools = reload_mcp_servers()
            mcp_count = len(tools)
            if mcp_count > 0:
                terminal.console.print(f"\n  ✅ {mcp_count} MCP tools reloaded.")
            else:
                terminal.console.print("\n  ⚠️  No MCP tools loaded. Check server configurations.")
            # Rebuild agent's tool list with new MCP tools
            all_tools = get_tools()
            terminal.agent.tools = all_tools
            terminal.agent.llm.tools = all_tools
        except Exception as e:
            terminal.console.print(f"\n  ❌ Failed to reload MCP servers: {e}")
        return True
