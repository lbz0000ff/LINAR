"""Skill system — pluggable LLM-driven capabilities.

A ``Skill`` is a named capability that replaces the agent's system prompt
and tool set while it runs.  The agent's original state is saved on entry
and restored on exit.

Supports the Claude Code SKILL.md format with bundled scripts and
``skill.json`` metadata (OpenClaw marketplace format).

Usage in ``terminal.py``::

    from skill import DocSkill

    register_skill(DocSkill())

    skill = get_skill("doc")
    orchestrator.run_skill(skill, "args")

Skills can also be defined as Markdown files::

    skills/
    └── my-skill/
        ├── SKILL.md
        ├── skill.json          (optional — OpenClaw metadata)
        └── scripts/
            └── helper.py       (optional — bundled scripts)

See ``load_skills_from_markdown()`` for the supported frontmatter fields.
"""

from __future__ import annotations

import os
import re
import sys
import json
import asyncio
import importlib.util
from typing import Any

import threading

import yaml

# Persistent event loop for async script tools.  Module-level singletons
# (e.g. aiohttp ClientSession) retain loop affinity, so we keep one loop
# alive instead of creating + closing one per call.
_async_loop: asyncio.AbstractEventLoop | None = None


def _get_async_loop() -> asyncio.AbstractEventLoop:
    global _async_loop
    if _async_loop is None or _async_loop.is_closed():
        _async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_async_loop)
    return _async_loop


# ── Hook-compatible tool name → Lily tool name mapping ──
_HOOK_TOOL_MAP = {
    "Bash": ["cmd_execute"],
    "Read": ["read_file", "search_files"],
    "Write": ["write_file"],
    "Edit": ["patch_file"],
    "Search": ["search_files"],
    "WebFetch": ["web_fetch"],
    "WebSearch": ["web_search"],
    "AskUser": ["ask_user"],
    "SkillView": ["skill_view"],
    "PlanAdvance": ["plan_advance"],
    "PlanStatus": ["plan_status"],
}


def _resolve_tool_name(raw: str) -> list[str]:
    """Resolve a granular tool name to Lily tool names.

    ``Bash(python3 *)`` → ``["cmd_execute"]`` (arg pattern ignored for now)
    ``Read`` → ``["read_file", "search_files"]``
    ``read_file`` → ``["read_file"]`` (pass-through for Lily native names)
    """
    # Strip parenthesized argument pattern: "Bash(git *)" → "Bash"
    base = raw.split("(")[0] if "(" in raw else raw
    base = base.strip()

    # Check hook-compatible names first
    if base in _HOOK_TOOL_MAP:
        return _HOOK_TOOL_MAP[base]

    # Pass-through: assume it's already a Lily tool name
    return [base]


class Skill:
    """Base class for an LLM-driven skill.

    Subclasses set ``name`` and ``system_prompt``; optionally override
    ``allowed_tools`` and ``on_load`` / ``on_unload`` hooks.
    """

    # ── identity ────────────────────────────────────────────
    name: str = ""
    description: str = ""
    when_to_use: str = ""

    # ── prompt & tools ──────────────────────────────────────
    system_prompt: str = ""
    allowed_tools: list[str] | None = None  # None = inherit all

    # ── Claude Code extended fields ─────────────────────────
    model: str = ""                          # model override
    effort: str = ""                         # low | medium | high | xhigh | max
    context: str = ""                        # "fork" → subagent isolation
    agent_type: str = ""                     # subagent type when context: fork
    arguments: list[str] | None = None       # named positional args
    argument_hint: str = ""                  # autocomplete hint
    disable_model_invocation: bool = False   # only manual /skill-name
    user_invocable: bool = True              # False = hide from / menu
    hooks: dict | None = None                # lifecycle hooks
    paths: list[str] | None = None           # glob patterns for auto-activation
    shell: str = "bash"                      # bash | powershell
    mcp_servers: list[str] | None = None     # MCP servers to start on load

    # ── bundled script support (skill.json / scripts/) ──────
    skill_file: str = ""                     # path to Python script from skill.json
    scripts_dir: str = ""                    # path to scripts/ subdirectory
    config_schema: dict | None = None        # from skill.json configSchema
    skill_dir: str = ""                      # absolute path to skill directory

    def on_load(self, agent) -> None:
        """Called when the skill gains control.

        Saves the agent's current state, swaps in the skill's prompt
        and tool set, and registers any bundled script tools.
        """
        self._saved_prompt = agent.llm.system_prompt
        self._saved_tools = dict(agent.tools)  # shallow copy
        agent._active_skill = self

        # ── register bundled script tools ──
        injected = {}
        if self.skill_file:
            script_tool = SkillScriptTool(
                name=f"{self.name}_script",
                description=f"Execute the bundled {os.path.basename(self.skill_file)} script",
                script_path=self.skill_file,
                skill_dir=self.skill_dir,
                shell=self.shell,
                agent_ref=agent,
            )
            injected[self.name + "_script"] = script_tool

        if self.scripts_dir and os.path.isdir(self.scripts_dir):
            for fname in sorted(os.listdir(self.scripts_dir)):
                if fname.endswith(".py"):
                    st = SkillScriptTool(
                        name=f"{self.name}_{fname[:-3]}",
                        description=f"Execute bundled script: {fname}",
                        script_path=os.path.join(self.scripts_dir, fname),
                        skill_dir=self.skill_dir,
                        shell=self.shell,
                        agent_ref=agent,
                    )
                    injected[f"{self.name}_{fname[:-3]}"] = st
                elif fname.endswith((".sh", ".ps1")):
                    st = SkillScriptTool(
                        name=f"{self.name}_{fname.rsplit('.', 1)[0]}",
                        description=f"Execute bundled script: {fname}",
                        script_path=os.path.join(self.scripts_dir, fname),
                        skill_dir=self.skill_dir,
                        shell=self.shell,
                        agent_ref=agent,
                    )
                    injected[f"{self.name}_{fname.rsplit('.', 1)[0]}"] = st

        # Merge injected tools before filtering
        if injected:
            agent.tools = {**agent.tools, **injected}

        # ── MCP servers are started at boot by tool_registry._init_mcp_servers() ──
        # Skill only controls which tools are visible via allowed_tools.

        agent._skill_active = True
        # Append skill prompt on top of the base prompt (identity, memory,
        # behavioural rules) instead of replacing it entirely. This way
        # the LLM keeps its persona and constraints from system_prompt_base.md,
        # SOUL.md, USER.md and MEMORY.md while running the skill.
        agent.llm.system_prompt = self._saved_prompt + "\n\n" + self.system_prompt

        if self.allowed_tools is not None:
            # Resolve both Claude Code granular names and Lily native names
            # MCP tools (prefixed with mcp_) are always visible, not filtered
            allowed = set(injected.keys())
            for raw in self.allowed_tools:
                allowed.update(_resolve_tool_name(raw))
            filtered = {}
            for k, v in agent.tools.items():
                if k.startswith("mcp_") or k in allowed:
                    filtered[k] = v
            agent.tools = filtered
            agent.llm.tools = filtered

    def on_unload(self, agent) -> None:
        """Called when the skill hands control back to the main agent.

        Restores the agent's pre-skill state (prompt + tools).
        MCP tools are boot-loaded and persist independently of skill lifecycle.
        """
        agent._skill_active = False
        agent._active_skill = None
        agent.llm.system_prompt = self._saved_prompt
        agent.tools = self._saved_tools
        agent.llm.tools = self._saved_tools


# ---------------------------------------------------------------------------
# SkillScriptTool — run a bundled Python / shell script
# ---------------------------------------------------------------------------

class SkillScriptTool:
    """Tool that executes a script bundled with a skill.

    For Python scripts, it imports the module and calls ``execute(command, args)``
    (or ``handle_command(text)`` as a fallback), handling async functions
    transparently.  For shell scripts, it runs them via ``subprocess``.

    If the script returns a dict with a ``"promise"`` key, the tool registers
    it with the agent as an async operation and returns without blocking.
    """

    stop_event: Any = None  # set by agent for interrupt support

    def __init__(self, name: str, description: str, script_path: str,
                 skill_dir: str = "", shell: str = "bash",
                 agent_ref=None):
        self.name = name
        self.description = description
        self._script_path = script_path
        self._skill_dir = skill_dir
        self._shell = shell
        self.agent_ref = agent_ref
        self._schema = {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to execute (e.g. 'generate', 'status', 'set_url')",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of arguments for the command",
                    },
                },
                "required": ["command"],
            },
        }
        # Cache loaded module so repeated calls don't re-import
        self._module = None

    @property
    def tool_schema(self) -> dict:
        return self._schema

    def execute(self, **kwargs) -> str:
        command = kwargs.get("command", "")
        args = kwargs.get("args", []) or []

        ext = os.path.splitext(self._script_path)[1].lower()

        if ext == ".py":
            return self._execute_python(command, args)
        elif ext in (".sh",):
            return self._execute_shell(command, args)
        elif ext in (".ps1",):
            return self._execute_shell(command, args, use_powershell=True)
        else:
            return self._execute_shell(command, args)

    def _execute_python(self, command: str, args: list[str]) -> str:
        """Import the Python script and call its execute/entry point."""
        try:
            if self._module is None:
                spec = importlib.util.spec_from_file_location(
                    f"_skill_{self.name}", self._script_path
                )
                if spec is None or spec.loader is None:
                    return f"Error: Could not load script: {self._script_path}"
                module = importlib.util.module_from_spec(spec)
                # Add skill_dir to sys.path so relative imports work
                if self._skill_dir:
                    sys.path.insert(0, self._skill_dir)
                try:
                    spec.loader.exec_module(module)
                finally:
                    if self._skill_dir and sys.path[0] == self._skill_dir:
                        sys.path.pop(0)
                self._module = module

            result = None

            # Try execute(command, args) first (OpenClaw convention)
            if hasattr(self._module, "execute"):
                # Inject stop_event so the script can check it during long ops
                if self.stop_event is not None:
                    self._module.stop_event = self.stop_event
                fn = self._module.execute
                result = fn(command, args)
            # Fallback: handle_command(text)
            elif hasattr(self._module, "handle_command"):
                fn = self._module.handle_command
                if command and args:
                    text = command + " " + " ".join(args)
                else:
                    text = command or ""
                result = fn(text)
            # Fallback: look for handle_<command>
            else:
                handler_name = f"handle_{command}"
                if hasattr(self._module, handler_name):
                    fn = getattr(self._module, handler_name)
                    result = fn(args)
                else:
                    return (f"Error: Script has no 'execute()' function and "
                            f"no handler for '{command}'. "
                            f"Available: {self._list_functions()}")

            # Handle async functions
            if asyncio.iscoroutine(result):
                if self.stop_event and self.stop_event.is_set():
                    return "[Interrupted by user]"

                loop = _get_async_loop()
                result = loop.run_until_complete(result)

            # ── promise detection: script returned an async operation ──
            if isinstance(result, dict) and "promise" in result:
                promise = result["promise"]
                pid = promise.get("id", "")
                if pid and self.agent_ref:
                    self.agent_ref.create_promise(pid)
                    self.agent_ref._promises[pid].update(promise)
                    return (
                        f"[PROMISE] Async operation submitted: {pid}\n"
                        f"Status: {promise.get('status', 'pending')}\n"
                        f"{promise.get('message', '')}\n\n"
                        f"Use resolve_promise promise_id=\"{pid}\" to check status."
                    )
                elif pid:
                    return (
                        f"[PROMISE] Async operation submitted: {pid}\n"
                        f"The operation is running in the background. "
                        f"(agent_ref not available for status queries)"
                    )

            # Format dict result nicely
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)

        except Exception as e:
            import traceback
            return f"Error executing script: {e}\n{traceback.format_exc()}"

    def _execute_shell(self, command: str, args: list[str],
                       use_powershell: bool = False) -> str:
        """Run the script as a shell subprocess."""
        import subprocess
        try:
            cmd_parts = []
            if use_powershell:
                cmd_parts = ["powershell", "-File", self._script_path]
            else:
                cmd_parts = ["bash", self._script_path]

            if command:
                cmd_parts.append(command)
            cmd_parts.extend(args)

            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output = f"Exit code: {result.returncode}\n{output}"
            return output.strip()

        except subprocess.TimeoutExpired:
            return "Error: Script timed out (120s)"
        except Exception as e:
            return f"Error running script: {e}"

    def _list_functions(self) -> str:
        if self._module is None:
            return "(module not loaded)"
        fns = [n for n in dir(self._module)
               if n.startswith("handle_") or n in ("execute", "handle_command")]
        return ", ".join(sorted(fns))


# ---------------------------------------------------------------------------
# Markdown skill loader  (Claude Code SKILL.md format)
# ---------------------------------------------------------------------------

_SKILL_MD = "SKILL.md"
_SKILL_JSON = "skill.json"

# Map extended frontmatter field names → Skill attribute names
_FRONTMATTER_FIELDS = {
    "name": "name",
    "description": "description",
    "when_to_use": "when_to_use",
    "allowed-tools": "allowed_tools",
    "allowed_tools": "allowed_tools",
    "model": "model",
    "effort": "effort",
    "context": "context",
    "agent": "agent_type",
    "arguments": "arguments",
    "argument-hint": "argument_hint",
    "argument_hint": "argument_hint",
    "disable-model-invocation": "disable_model_invocation",
    "disable_model_invocation": "disable_model_invocation",
    "user-invocable": "user_invocable",
    "user_invocable": "user_invocable",
    "hooks": "hooks",
    "paths": "paths",
    "shell": "shell",
    "mcp-servers": "mcp_servers",
    "mcp_servers": "mcp_servers",
}


def load_skills_from_markdown(skills_dir: str) -> int:
    """Scan *skills_dir* for ``*/SKILL.md`` and register each as a ``Skill``.

    Also reads ``skill.json`` if present in the skill directory
    (OpenClaw marketplace format) to extract ``skillFile`` and ``configSchema``.

    Supported frontmatter fields in the Markdown file:

    Basic:
      ``name`` — Skill name (used as ``/name``).  Falls back to directory name.
      ``description`` — Shown in ``/help``.
      ``allowed-tools`` / ``allowed_tools`` — Space-separated string *or* YAML
        list of permitted tool names.

    Extended:
      ``model`` — Model override for the skill's turn.
      ``effort`` — Effort level (low | medium | high | xhigh | max).
      ``context`` — ``fork`` to run in a subagent (isolated context).
      ``agent`` — Subagent type when ``context: fork``.
      ``arguments`` — Named positional args for ``$name`` substitution.
      ``argument-hint`` — Autocomplete hint (e.g. ``[filename]``).
      ``disable-model-invocation`` — Only manual ``/skill-name`` invocation.
      ``user-invocable`` — ``false`` = hide from ``/`` menu.
      ``hooks`` — Lifecycle hooks.
      ``paths`` — Glob patterns for auto-activation.
      ``shell`` — ``bash`` (default) or ``powershell``.

    The Markdown body (everything after the frontmatter) becomes the
    skill's ``system_prompt``.

    Returns the number of skills loaded.
    """
    count = 0
    if not os.path.isdir(skills_dir):
        return 0

    for entry in os.listdir(skills_dir):
        if entry.endswith(".disabled"):
            continue
        skill_dir_path = os.path.join(skills_dir, entry)
        skill_file = os.path.join(skill_dir_path, _SKILL_MD)
        if not os.path.isfile(skill_file):
            continue

        skill = _parse_skill_md(skill_file, entry)
        if skill is not None:
            # Try reading skill.json for extra metadata
            _read_skill_json(skill_dir_path, skill)
            register_skill(skill)
            count += 1

    return count


def _read_skill_json(skill_dir: str, skill: Skill) -> None:
    """Read ``skill.json`` from *skill_dir* and merge into *skill*."""
    json_path = os.path.join(skill_dir, _SKILL_JSON)
    if not os.path.isfile(json_path):
        return
    try:
        with open(json_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    # skillFile → absolute path
    sf = meta.get("skillFile") or meta.get("skill_file", "")
    if sf:
        skill.skill_file = os.path.join(skill_dir, sf)

    # configSchema
    skill.config_schema = meta.get("configSchema") or meta.get("config_schema")

    # Override description from JSON if SKILL.md has none
    json_desc = meta.get("description", "")
    if json_desc and not skill.description:
        skill.description = json_desc

    # Version info
    skill.version = meta.get("version", "")

    skill.skill_dir = skill_dir


def _parse_skill_md(path: str, default_name: str) -> Skill | None:
    """Parse a single SKILL.md and return a ``Skill`` (or ``None`` on failure)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None

    fm, body = _split_frontmatter(text)

    if fm:
        meta = yaml.safe_load(fm) or {}
    else:
        meta = {}

    skill = Skill()
    skill.skill_dir = os.path.dirname(path)
    skill.name = str(meta.get("name", default_name))
    skill.description = str(meta.get("description", ""))
    skill.system_prompt = body.strip()

    # ── allowed-tools ──
    raw_tools = meta.get("allowed-tools") or meta.get("allowed_tools")
    if raw_tools:
        skill.allowed_tools = parse_allowed_tools(raw_tools)

    # ── extended frontmatter fields ──
    for fm_key, attr in _FRONTMATTER_FIELDS.items():
        if fm_key in ("name", "description", "allowed-tools", "allowed_tools"):
            continue  # already handled above
        if fm_key in meta:
            setattr(skill, attr, meta[fm_key])

    # ── scripts/ subdirectory ──
    scripts_dir = os.path.join(skill.skill_dir, "scripts")
    if os.path.isdir(scripts_dir):
        skill.scripts_dir = scripts_dir

    return skill


def parse_allowed_tools(raw: str | list) -> list[str]:
    """Parse Claude Code granular allowed-tools format into tool names.

    Handles:
      "Bash(git *) Read" → ["Bash(git *)", "Read"]
      ["read_file", "search_files"] → ["read_file", "search_files"]
      "read_file search_files" → ["read_file", "search_files"]

    For now, returns the raw patterns; the filtering logic in ``on_load``
    matches against tool *names* only (the part before ``(``).
    """
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        # Split on whitespace but keep parenthesized groups intact
        parts = re.findall(r'\S+\([^)]*\)|\S+', raw)
        return parts
    return []


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split ``---``-delimited YAML frontmatter from body.

    Returns ``(frontmatter_string, body_string)``.  If no frontmatter is
    found the first element is ``None``.
    """
    stripped = text.lstrip()
    if stripped.startswith("---"):
        # find the closing `---`
        end = stripped.find("---", 3)
        if end != -1:
            fm = stripped[3:end].strip()
            body = stripped[end + 3:].strip()
            return (fm if fm else None, body)
    return (None, stripped.strip())


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_skills: dict[str, Skill] = {}


def register_skill(skill: Skill):
    """Register a skill so it can be dispatched by name."""
    _skills[skill.name] = skill


def get_skill(name: str) -> Skill | None:
    return _skills.get(name)


def all_skills() -> list[Skill]:
    return list(_skills.values())
