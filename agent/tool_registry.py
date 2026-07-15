from logger import get_logger
import asyncio
import concurrent.futures
import os
import json
from tool.basic_tools.tool_time import Tool_GetTime, Tool_GetDate

log = get_logger(__name__)
from tool.basic_tools.tool_fileio import (
    Tool_ReadFile, Tool_WriteFile, Tool_DeleteFile,
    Tool_DeleteDir, Tool_PatchFile, Tool_SearchFiles,
)
from tool.basic_tools.tool_cmd import Tool_CmdExecute
from tool.basic_tools.tool_web import Tool_WebFetch, Tool_WebSearch
from tool.basic_tools.tool_memory import Tool_Remember, Tool_RecallFact, Tool_RecallTopic, Tool_GetTopicList
from tool.basic_tools.tool_ask_user import Tool_AskUser
from tool.basic_tools.tool_skill import Tool_Skill
from tool.basic_tools.tool_plan import Tool_PlanAdvance, Tool_PlanStatus, Tool_CreatePlan
from tool.basic_tools.tool_vision import Tool_ImgToText
from tool.basic_tools.tool_vision_vlm import Tool_Vision
from tool.basic_tools.tool_promise import Tool_ResolvePromise
from tool.basic_tools.tool_cancel_promise import Tool_CancelPromise
from tool.basic_tools.tool_workspace import Tool_CreateWorkspace, Tool_SwitchWorkspace

# ── MCP support ──────────────────────────────────────────────
from config import load_config
from mcp_server import MCPServer
from tool.mcp_tools.mcp_tool import MCPTool

_MCP_START_TIMEOUT = 8  # seconds per server

_mcp_servers: list[MCPServer] = []
_mcp_initialized = False
_mcp_tools_cache: dict = {}
"""All running MCP server instances (for lifecycle management)."""


def _discover_local_servers() -> dict:
    """Auto-discover MCP servers from agent/tool/mcp_tools/server/.

    Each subdirectory containing a ``server.py`` or ``mcp_server.json``
    is registered as a server.

    Config.yaml entries always take precedence over discovered ones.
    """
    discovered = {}
    servers_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "tool", "mcp_tools", "server")
    if not os.path.isdir(servers_dir):
        return discovered

    for entry in sorted(os.listdir(servers_dir)):
        srv_dir = os.path.join(servers_dir, entry)
        if not os.path.isdir(srv_dir):
            continue

        # Check for manifest
        manifest = os.path.join(srv_dir, "mcp_server.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, encoding="utf-8") as f:
                    meta = json.load(f)
                args_raw = meta.get("args", [os.path.join(srv_dir, "server.py")])
                args_resolved = [
                    os.path.join(srv_dir, a) if not a.startswith("-") and not os.path.isabs(a)
                    and "/" not in a and "\\" not in a
                    else a
                    for a in args_raw
                ]
                env_raw = meta.get("env") or {}
                env_resolved = {
                    k: os.path.join(srv_dir, v) if not v.startswith("-") and not os.path.isabs(v)
                    and "/" not in v and "\\" not in v
                    else v
                    for k, v in env_raw.items()
                }
                discovered[entry] = {
                    "enabled": True,
                    "command": meta.get("command", "python"),
                    "args": args_resolved,
                    "env": env_resolved or None,
                }
                continue
            except (OSError, json.JSONDecodeError) as e:
                log.warning("MCP discover: skipping %s manifest: %s", entry, e)

        # Convention: python server.py --stdio
        server_py = os.path.join(srv_dir, "server.py")
        if os.path.isfile(server_py):
            discovered[entry] = {
                "enabled": True,
                "command": "python",
                "args": [server_py, "--stdio"],
                "env": None,
            }

    return discovered


def _load_mcp_config() -> dict:
    """Merge config.yaml MCP servers with auto-discovered local servers.

    Returns a dict of ``{name: config_dict}``.  Config.yaml entries
    take precedence over discovered ones.
    """
    cfg = load_config()
    merged = dict(cfg.get("mcp_servers") or {})
    for name, scfg in _discover_local_servers().items():
        merged.setdefault(name, scfg)
    return merged


def _resolve_mcp_args(scfg: dict, config: dict) -> list[str]:
    """Return MCP process args, optionally adding provider-backed bearer auth."""
    args = [str(arg) for arg in (scfg.get("args") or [])]
    provider_name = str(scfg.get("auth_provider") or "").strip()
    if not provider_name:
        return args

    providers = config.get("providers") or {}
    provider = providers.get(provider_name) or {}
    api_key = str(provider.get("api_key") or "").strip()
    if not api_key or api_key.startswith("${"):
        for section_name in ("llm", "aux", "vision"):
            section = config.get(section_name) or {}
            candidate = str(section.get("api_key") or "").strip()
            if (
                section.get("provider") == provider_name
                and candidate
                and not candidate.startswith("${")
            ):
                api_key = candidate
                break
    if not api_key or api_key.startswith("${"):
        raise ValueError(
            f"MCP auth provider '{provider_name}' has no configured API key"
        )
    return [*args, "--header", f"Authorization: Bearer {api_key}"]


def _start_one_mcp(name: str, scfg: dict) -> tuple[str, object, list[dict]] | None:
    """Start a single MCP server with its own timeout — runs in a worker thread."""
    import asyncio
    timeout = scfg.get("start_timeout", _MCP_START_TIMEOUT)
    try:
        config = load_config()
        args = _resolve_mcp_args(scfg, config)
        server = MCPServer(name, scfg["command"], args, env=scfg.get("env"))
        asyncio.run(asyncio.wait_for(server.start(), timeout=timeout))
        return name, server, server.list_tools()
    except asyncio.TimeoutError:
        log.warning("MCP server '%s' timed out (%ds) — stopping", name, timeout)
        server.stop()
        return None
    except Exception as exc:
        log.error("MCP server '%s' failed: %s", name, exc)
        return None


def _init_mcp_servers() -> dict:
    """Start all MCP servers in parallel and return their tools (once)."""
    global _mcp_initialized, _mcp_tools_cache
    if _mcp_initialized:
        return _mcp_tools_cache
    _mcp_initialized = True

    servers_cfg = _load_mcp_config()
    tools = {}

    enabled = {name: scfg for name, scfg in servers_cfg.items() if scfg.get("enabled", True)}
    if not enabled:
        _mcp_tools_cache = tools
        return tools

    # Parallel start — each server runs in its own thread with independent timeout
    results: list[tuple[str, object, list[dict]]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(enabled)) as pool:
        fut_map = {pool.submit(_start_one_mcp, name, scfg): name
                   for name, scfg in enabled.items()}
        for fut in concurrent.futures.as_completed(fut_map):
            name = fut_map[fut]
            try:
                result = fut.result()
                if result is not None:
                    results.append(result)
            except Exception as exc:
                log.error("MCP server '%s' unhandled error: %s", name, exc)

    # Collect tools from servers that started successfully
    for name, server, tools_list in results:
        for t in tools_list:
            full_name = f"mcp_{name}_{t['name']}"
            tools[full_name] = MCPTool(
                server=server,
                name=full_name,
                original_name=t['name'],
                description=t["description"],
                input_schema=t["inputSchema"],
                is_search_tool=bool(
                    (servers_cfg.get(name) or {}).get("is_search_tool", False)
                ),
            )
        _mcp_servers.append(server)
        log.info("MCP server '%s': registered %d tools", name, len(tools_list))

    _mcp_tools_cache = tools
    return tools


def reload_mcp_servers() -> dict:
    """Shut down all MCP servers and restart them.

    Call this after installing new MCP servers or tools.
    Returns the new tool dict.
    """
    global _mcp_initialized, _mcp_tools_cache, _mcp_servers

    # Shut down existing — kill immediately, no graceful 5s wait
    for srv in _mcp_servers:
        try:
            srv.force_kill()
        except Exception:
            pass
    _mcp_servers.clear()
    _mcp_tools_cache = {}
    _mcp_initialized = False

    # Re-init
    return _init_mcp_servers()


def shutdown_mcp_servers():
    """Stop all running MCP servers immediately."""
    for srv in _mcp_servers:
        try:
            srv.force_kill()
        except Exception:
            pass
    _mcp_servers.clear()


# ── tool definitions (building blocks for registries) ─────────
_TOOL_CLASSES = {
    "get_date": Tool_GetDate,
    "get_time": Tool_GetTime,
    "read_file": Tool_ReadFile,
    "write_file": Tool_WriteFile,
    "delete_file": Tool_DeleteFile,
    "delete_dir": Tool_DeleteDir,
    "patch_file": Tool_PatchFile,
    "search_files": Tool_SearchFiles,
    "cmd_execute": Tool_CmdExecute,
    "web_fetch": Tool_WebFetch,
    "web_search": Tool_WebSearch,
    "remember": Tool_Remember,
    "recall_fact": Tool_RecallFact,
    "recall_topic": Tool_RecallTopic,
    "get_topic_list": Tool_GetTopicList,
    "ask_user": Tool_AskUser,
    "skill": Tool_Skill,
    "plan_advance": Tool_PlanAdvance,
    "plan_status": Tool_PlanStatus,
    "create_plan": Tool_CreatePlan,
    "img_to_text": Tool_ImgToText,
    # "vision" is added dynamically by _add_multimodal_tools()
    "resolve_promise": Tool_ResolvePromise,
    "cancel_promise": Tool_CancelPromise,
    "create_workspace": Tool_CreateWorkspace,
    "switch_workspace": Tool_SwitchWorkspace,
}

# ── toolsets ─────────────────────────────────────────────────
_TOOLSETS = {
    "time": ["get_date", "get_time"],
    "file": [
        "read_file", "write_file", "delete_file",
        "delete_dir", "patch_file", "search_files",
        "create_workspace", "switch_workspace",
    ],
    "shell": ["cmd_execute", "cancel_promise"],
    "web": ["web_fetch", "web_search"],
    "memory": ["remember", "recall_fact", "recall_topic", "get_topic_list"],
    "interactive": ["ask_user", "skill", "resolve_promise"],
    "plan": ["plan_advance", "plan_status", "create_plan"],
    "vision": ["img_to_text"],
    "research": [
        "web_search", "web_fetch",
        "read_file", "write_file", "search_files",
        "create_workspace", "switch_workspace",
        "create_plan",
    ],
    "mcp": [],  # placeholder — MCP tools are injected dynamically
}


class ToolRegistry:
    """Instantiable tool registry — each agent gets its own instance.

    Usage::

        registry = ToolRegistry(enabled_sets=["time", "file", "shell"])
        tools = registry.get_tools()
        agent = Agent(tools=tools)
    """

    def __init__(self, enabled_sets: list[str] | None = None):
        self._enabled_sets = enabled_sets

    def get_tools(self) -> dict:
        """Return a dict of tool instances filtered by enabled sets."""
        selected = {}
        mcp_tools = {}
        if self._enabled_sets is None:
            for name, cls in _TOOL_CLASSES.items():
                selected[name] = cls()
            mcp_tools = _init_mcp_servers()
            selected.update(mcp_tools)
        else:
            for name in self._enabled_sets:
                for tool_name in _TOOLSETS.get(name, []):
                    if tool_name in _TOOL_CLASSES:
                        selected[tool_name] = _TOOL_CLASSES[tool_name]()
            # Enable MCP servers when "mcp" or "research" toolset is selected
            if any(
                name in self._enabled_sets for name in ("web", "mcp", "research")
            ):
                mcp_tools = _init_mcp_servers()
            if "mcp" in self._enabled_sets or "research" in self._enabled_sets:
                selected.update(mcp_tools)
        if self._enabled_sets is None or any(
            name in self._enabled_sets for name in ("web", "research")
        ):
            _replace_native_web_tools(selected, mcp_tools)
        _add_vision_tools(selected)
        return selected


# ── global singleton (backwards compatibility) ────────────────
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
    "recall_fact": Tool_RecallFact(),
    "recall_topic": Tool_RecallTopic(),
    "get_topic_list": Tool_GetTopicList(),
    "ask_user": Tool_AskUser(),
    "skill": Tool_Skill(),
    "plan_advance": Tool_PlanAdvance(),
    "plan_status": Tool_PlanStatus(),
    "create_plan": Tool_CreatePlan(),
    "img_to_text": Tool_ImgToText(),
    "resolve_promise": Tool_ResolvePromise(),
    "cancel_promise": Tool_CancelPromise(),
    "create_workspace": Tool_CreateWorkspace(),
    "switch_workspace": Tool_SwitchWorkspace(),
}

# ── helpers for conditional tool registration ─────────────────

def _add_vision_tools(tools: dict) -> None:
    """Conditionally register ``vision`` / ``img_to_text`` based on config."""
    cfg = load_config()
    multimodal = cfg.get("llm", {}).get("multimodal", False)
    vision_enabled = cfg.get("vision", {}).get("enabled", False)

    if multimodal:
        tools["vision"] = Tool_Vision()
    if vision_enabled:
        tools["img_to_text"] = Tool_ImgToText()


def _replace_native_web_tools(tools: dict, mcp_tools: dict) -> None:
    """Hide native web tools when a successful search MCP can replace them."""
    search_mcp_tools = {
        name: tool
        for name, tool in mcp_tools.items()
        if bool(getattr(tool, "is_search_tool", False))
    }
    if not search_mcp_tools:
        return
    tools.pop("web_search", None)
    tools.pop("web_fetch", None)
    tools.update(search_mcp_tools)

# ── public API ───────────────────────────────────────────────

def get_tools(enabled_sets=None, include_mcp=True):
    """Return a dict of tools filtered by enabled toolset names.

    If enabled_sets is None, returns all tools (backwards-compatible).
    When include_mcp=True (default), also starts MCP servers.
    """
    mcp_tools = _init_mcp_servers() if include_mcp else {}

    if enabled_sets is None:
        all_tools = dict(_all_tools)
        all_tools.update(mcp_tools)
        _replace_native_web_tools(all_tools, mcp_tools)
        _add_vision_tools(all_tools)
        log.info("Loaded %d native + %d MCP tools", len(_all_tools), len(mcp_tools))
        return all_tools

    selected = {}
    for name in enabled_sets:
        for tool_name in _TOOLSETS.get(name, []):
            if tool_name in _all_tools:
                selected[tool_name] = _all_tools[tool_name]
    if include_mcp and ("mcp" in enabled_sets or "research" in enabled_sets):
        selected.update(mcp_tools)
    if include_mcp and ("web" in enabled_sets or "research" in enabled_sets):
        _replace_native_web_tools(selected, mcp_tools)
    _add_vision_tools(selected)
    log.info("Loaded %d tools from enabled sets: %s", len(selected), enabled_sets)
    return selected


def get_toolsets():
    """Return the toolset definition dict."""
    return dict(_TOOLSETS)


# ── lazy globals (don't block module import with MCP startup) ──
_tools_cache = None
_toolsets_cache = None

def __getattr__(name):
    global _tools_cache, _toolsets_cache
    if name == 'tools':
        if _tools_cache is None:
            _tools_cache = get_tools()
        return _tools_cache
    if name == 'toolsets':
        if _toolsets_cache is None:
            _toolsets_cache = get_toolsets()
        return _toolsets_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

if __name__ == "__main__":
    print(get_tools()["get_date"].tool_schema)
