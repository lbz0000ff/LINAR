from logger import get_logger
from basic_tools.tool_time import Tool_GetTime, Tool_GetDate

log = get_logger(__name__)
from basic_tools.tool_fileio import (
    Tool_ReadFile, Tool_WriteFile, Tool_DeleteFile,
    Tool_DeleteDir, Tool_PatchFile, Tool_SearchFiles,
)
from basic_tools.tool_cmd import Tool_CmdExecute
from basic_tools.tool_web import Tool_WebFetch, Tool_WebSearch
from basic_tools.tool_memory import Tool_Remember, Tool_Recall
from basic_tools.tool_ask_user import Tool_AskUser
from basic_tools.tool_skill import Tool_SkillView
from basic_tools.tool_plan import Tool_PlanAdvance, Tool_PlanStatus

# ── MCP support ──────────────────────────────────────────────
from config import load_config
from mcp_server import MCPServer
from basic_tools.mcp_tool import MCPTool

_mcp_servers: list[MCPServer] = []
_mcp_initialized = False
_mcp_tools_cache: dict = None
"""All running MCP server instances (for lifecycle management)."""


def _init_mcp_servers() -> dict:
    """Start MCP servers from config and return their tools (once)."""
    global _mcp_initialized, _mcp_tools_cache
    if _mcp_initialized:
        return _mcp_tools_cache or {}
    _mcp_initialized = True

    cfg = load_config()
    servers_cfg = cfg.get("mcp_servers") or {}
    tools = {}
    for name, scfg in servers_cfg.items():
        if not scfg.get("enabled", True):
            continue
        try:
            server = MCPServer(name, scfg["command"], scfg.get("args", []))
            server.start()
            for t in server.list_tools():
                full_name = f"mcp_{name}_{t['name']}"
                tools[full_name] = MCPTool(
                    server=server,
                    name=full_name,
                    original_name=t['name'],
                    description=t["description"],
                    input_schema=t["inputSchema"],
                )
            _mcp_servers.append(server)
            log.info("MCP server '%s': registered %d tools", name, len(server.list_tools()))
        except Exception as exc:
            log.error("MCP server '%s' failed: %s", name, exc)
    _mcp_tools_cache = tools
    return tools


def shutdown_mcp_servers():
    """Stop all running MCP servers."""
    for srv in _mcp_servers:
        srv.stop()
    _mcp_servers.clear()

# ── all tool instances ──────────────────────────────────────
_all_tools = {
    "get_date": Tool_GetDate(),
    "get_time": Tool_GetTime(),
    "read_file": Tool_ReadFile(),
    "write_file": Tool_WriteFile(),
    "delete_file": Tool_DeleteFile(),
    "delete_dir": Tool_DeleteDir(),
    "patch_file": Tool_PatchFile(),
    "search_files": Tool_SearchFiles(),
    "cmd_execute": Tool_CmdExecute(),
    "web_fetch": Tool_WebFetch(),
    "web_search": Tool_WebSearch(),
    "remember": Tool_Remember(),
    "recall": Tool_Recall(),
    "ask_user": Tool_AskUser(),
    "skill_view": Tool_SkillView(),
    "plan_advance": Tool_PlanAdvance(),
    "plan_status": Tool_PlanStatus(),
}

# ── toolsets ─────────────────────────────────────────────────
_toolsets = {
    "time": ["get_date", "get_time"],
    "file": [
        "read_file", "write_file", "delete_file",
        "delete_dir", "patch_file", "search_files",
    ],
    "shell": ["cmd_execute"],
    "web": ["web_fetch", "web_search"],
    "memory": ["remember", "recall"],
    "interactive": ["ask_user", "skill_view"],
    "plan": ["plan_advance", "plan_status"],
    "mcp": [],  # placeholder — MCP tools are injected dynamically
}

# ── public API ───────────────────────────────────────────────

def get_tools(enabled_sets=None):
    """Return a dict of tools filtered by enabled toolset names.

    If enabled_sets is None, returns all tools (backwards-compatible).
    Also starts MCP servers from config and appends their tools.
    """
    # Start MCP servers once
    mcp_tools = _init_mcp_servers()

    if enabled_sets is None:
        all_tools = dict(_all_tools)
        all_tools.update(mcp_tools)
        log.info("Loaded %d native + %d MCP tools", len(_all_tools), len(mcp_tools))
        return all_tools

    selected = {}
    for name in enabled_sets:
        for tool_name in _toolsets.get(name, []):
            if tool_name in _all_tools:
                selected[tool_name] = _all_tools[tool_name]
    if "mcp" in enabled_sets:
        selected.update(mcp_tools)
    log.info("Loaded %d tools from enabled sets: %s", len(selected), enabled_sets)
    return selected


def get_toolsets():
    """Return the toolset definition dict."""
    return dict(_toolsets)


# ── backwards-compatible globals ─────────────────────────────
tools = get_tools()
toolsets = get_toolsets()

if __name__ == "__main__":
    print(tools["get_date"].tool_schema)
