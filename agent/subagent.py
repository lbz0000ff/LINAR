"""Subagent loader — predefined subagent types from ``agent_types/*.md`` files.

Mimics Claude Code's agent-type pattern: each ``.md`` file declares
metadata in YAML frontmatter and the system-prompt body in Markdown.
The main agent selects a type and fills in per-task ``params``.

Usage::

    from subagent import load_subagent, render_prompt

    agent_def = load_subagent("web_researcher")
    prompt = render_prompt(agent_def, {"task_description": "...", "angles": [...]})
"""

from __future__ import annotations

import os
import yaml

from logger import get_logger

log = get_logger(__name__)

# ── frontmatter parsing (same format as skill.py) ────────────────


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split ``---`` YAML frontmatter from body.

    Returns ``(frontmatter_str_or_None, body_str)``.
    """
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            fm = stripped[3:end].strip()
            body = stripped[end + 3:].strip()
            return (fm if fm else None, body)
    return (None, stripped.strip())


def _resolve_agents_dir() -> str:
    """Resolve the ``agents/`` directory relative to the project root."""
    # The project root is two levels above this file: agent/subagent.py → <root>
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "agent_types")


def load_subagent(name: str) -> dict | None:
    """Load a subagent definition from ``agents/{name}.md``.

    Returns a dict with keys ``name``, ``description``, ``hint``,
    ``model``, ``system_prompt``, or ``None`` if the file doesn't exist.
    """
    path = os.path.join(_resolve_agents_dir(), f"{name}.md")
    if not os.path.isfile(path):
        log.warning("Subagent file not found: %s", path)
        return None

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        log.warning("Subagent file unreadable: %s", path)
        return None

    fm, body = _split_frontmatter(text)

    if fm:
        meta = yaml.safe_load(fm) or {}
    else:
        meta = {}

    return {
        "name": str(meta.get("name", name)),
        "description": str(meta.get("description", "")),
        "hint": str(meta.get("hint", "")),
        "model": meta.get("model"),              # None = inherit from main agent
        "provider": meta.get("provider"),         # None = inherit from main agent
        "allowed_tools": _parse_allowed_tools(meta),  # tool whitelist
        "system_prompt": body.strip(),
    }


def _parse_allowed_tools(meta: dict) -> list[str] | None:
    """Extract allowed-tools from frontmatter meta.

    Returns ``None`` when no restriction is specified (all tools
    from the hint's toolset are available).  Returns a list when
    the subagent should only see a subset of tools.
    """
    raw = meta.get("allowed-tools") or meta.get("allowed_tools")
    if raw is None:
        return None
    if isinstance(raw, str):
        return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    if isinstance(raw, list):
        return [str(t) for t in raw if isinstance(t, str)]
    return None


def render_prompt(agent_def: dict, params: dict | None = None) -> str:
    """Render a subagent's system prompt by filling in ``{placeholders}``.

    ``params`` should be a flat dict (no nesting) whose keys match
    the ``{{key}}`` placeholders in the prompt body.  Uses Python's
    ``str.format_map`` — only keys present in the prompt are consumed.

    Missing keys are left as literal ``{key}`` in the output
    (no KeyError).  This is intentional: if the template has a
    placeholder the main agent forgot to fill, it stays visible.
    """
    body = agent_def["system_prompt"]

    if params:
        try:
            # format_map doesn't throw on missing keys — leftover
            # placeholders pass through untouched.  This is a safe
            # default: the sub-agent will see a raw "{angles}" and
            # can ask what angles to use.
            body = body.format_map(_SafeDict(params))
        except Exception as exc:
            log.warning("Prompt rendering error: %s", exc)

    return body


class _SafeDict(dict):
    """A dict that returns ``{key}`` unchanged when ``key`` is missing.

    Used with ``str.format_map`` so that unfilled placeholders are
    preserved in the prompt rather than raising ``KeyError``.
    """
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def list_subagents() -> list[str]:
    """Return the names of all available subagent definitions."""
    agents_dir = _resolve_agents_dir()
    if not os.path.isdir(agents_dir):
        return []
    names = []
    for entry in sorted(os.listdir(agents_dir)):
        if entry.endswith(".md"):
            names.append(entry[:-3])   # strip ".md"
    return names
