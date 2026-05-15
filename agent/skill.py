"""Skill system — pluggable LLM-driven capabilities.

A ``Skill`` is a named capability that replaces the agent's system prompt
and tool set while it runs.  The agent's original state is saved on entry
and restored on exit.

Usage in ``terminal.py``::

    from skills.doc import DocSkill

    register_skill(DocSkill())

    skill = get_skill("doc")
    orchestrator.run_skill(skill, "args")

Skills can also be defined as Markdown files (Claude Code format)::

    skills/
    └── my-skill/
        └── SKILL.md

See ``load_skills_from_markdown()`` for the supported frontmatter fields.
"""

from __future__ import annotations

import os

import yaml


class Skill:
    """Base class for an LLM-driven skill.

    Subclasses set ``name`` and ``system_prompt``; optionally override
    ``allowed_tools`` and ``on_load`` / ``on_unload`` hooks.
    """

    name: str = ""
    description: str = ""
    system_prompt: str = ""
    allowed_tools: list[str] | None = None  # None = inherit all

    def on_load(self, agent) -> None:
        """Called when the skill gains control.

        Saves the agent's current state and swaps in the skill's prompt
        and tool set.
        """
        self._saved_prompt = agent.llm.system_prompt
        self._saved_tools = agent.tools
        agent._skill_active = True
        agent.llm.system_prompt = self.system_prompt
        if self.allowed_tools is not None:
            filtered = {k: v for k, v in agent.tools.items()
                        if k in self.allowed_tools}
            agent.tools = filtered
            agent.llm.tools = filtered

    def on_unload(self, agent) -> None:
        """Called when the skill hands control back to the main agent.

        Restores the agent's pre-skill state.
        """
        agent._skill_active = False
        agent.llm.system_prompt = self._saved_prompt
        agent.tools = self._saved_tools
        agent.llm.tools = self._saved_tools


# ---------------------------------------------------------------------------
# Markdown skill loader  (Claude Code SKILL.md format)
# ---------------------------------------------------------------------------

_SKILL_MD = "SKILL.md"


def load_skills_from_markdown(skills_dir: str) -> int:
    """Scan *skills_dir* for ``*/SKILL.md`` and register each as a ``Skill``.

    Supported frontmatter fields in the Markdown file:

    ``name``
        Skill name (used as ``/name``).  Falls back to the directory name.
    ``description``
        Shown in ``/help``.
    ``allowed-tools`` / ``allowed_tools``
        Space-separated string *or* YAML list of permitted tool names.
    (all other frontmatter fields are silently ignored)

    The Markdown body (everything after the frontmatter) becomes the
    skill's ``system_prompt``.

    Returns the number of skills loaded.
    """
    import os

    count = 0
    if not os.path.isdir(skills_dir):
        return 0

    for entry in os.listdir(skills_dir):
        skill_dir = os.path.join(skills_dir, entry)
        skill_file = os.path.join(skill_dir, _SKILL_MD)
        if not os.path.isfile(skill_file):
            continue

        skill = _parse_skill_md(skill_file, entry)
        if skill is not None:
            register_skill(skill)
            count += 1

    return count


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
    skill.name = str(meta.get("name", default_name))
    skill.description = str(meta.get("description", ""))
    skill.system_prompt = body.strip()

    raw_tools = meta.get("allowed-tools") or meta.get("allowed_tools")
    if raw_tools:
        if isinstance(raw_tools, str):
            skill.allowed_tools = raw_tools.split()
        elif isinstance(raw_tools, list):
            skill.allowed_tools = [str(t) for t in raw_tools]

    return skill


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
