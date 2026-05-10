from basic_tools.tool_time import Tool_GetTime, Tool_GetDate
from basic_tools.tool_fileio import (
    Tool_ReadFile, Tool_WriteFile, Tool_DeleteFile,
    Tool_DeleteDir, Tool_PatchFile, Tool_SearchFiles,
)
from basic_tools.tool_cmd import Tool_CmdExecute
from basic_tools.tool_web import Tool_WebFetch

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
}

# ── toolsets ─────────────────────────────────────────────────
_toolsets = {
    "time": ["get_date", "get_time"],
    "file": [
        "read_file", "write_file", "delete_file",
        "delete_dir", "patch_file", "search_files",
    ],
    "shell": ["cmd_execute"],
    "web": ["web_fetch"],
}

# ── public API ───────────────────────────────────────────────

def get_tools(enabled_sets=None):
    """Return a dict of tools filtered by enabled toolset names.

    If enabled_sets is None, returns all tools (backwards-compatible).
    """
    if enabled_sets is None:
        return dict(_all_tools)

    selected = {}
    for name in enabled_sets:
        for tool_name in _toolsets.get(name, []):
            if tool_name in _all_tools:
                selected[tool_name] = _all_tools[tool_name]
    return selected


def get_toolsets():
    """Return the toolset definition dict."""
    return dict(_toolsets)


# ── backwards-compatible globals ─────────────────────────────
tools = get_tools()
toolsets = get_toolsets()

if __name__ == "__main__":
    print(tools["get_date"].tool_schema)
