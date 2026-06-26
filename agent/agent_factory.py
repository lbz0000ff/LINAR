"""Agent factory — create agent instances for DAG sub-tasks."""

from __future__ import annotations

import asyncio
import json
import os
from config import load_config
from logger import get_logger
from tool_registry import ToolRegistry
from hooks import HookRegistry
from agent import Agent

log = get_logger(__name__)


def _make_system_prompt_extra(task: str,
                              agent_hint: str = "any",
                              predecessor_results: dict[str, str] = None) -> str:
    """Build extra context appended to the base system prompt."""
    parts = [f"## Current task\n{task}"]

    if agent_hint and agent_hint != "any":
        parts.append(f"Your role: {agent_hint}")

    if predecessor_results:
        ctx = "\n".join(
            f"  [{nid}] {result[:200]}"
            for nid, result in predecessor_results.items()
        )
        parts.append(f"## Results from predecessor tasks\n{ctx}")

    return "\n\n".join(parts)


def create_agent(agent_hint: str = "any",
                 predecessor_results: dict[str, str] = None,
                 stop_event: asyncio.Event | None = None,
                 workspace_root: str | None = None) -> Agent:
    """Create an Agent instance for a DAG sub-task.

    Parameters
    ----------
    agent_hint : str
        Hint for tool selection and system prompt tuning.
    predecessor_results : dict, optional
        Results from predecessor DAG nodes, keyed by node id.

    Returns
    -------
    Agent
        A fresh agent with isolated tools and LLM.
    """
    cfg = load_config()

    # ── select tool set based on agent_hint ──
    hint_to_tools = {
        "code":     ["time", "file", "shell", "interactive"],
        "analysis": ["time", "file", "web", "memory"],
        "shell":    ["time", "shell"],
        "research": ["web", "file"],
    }
    enabled = hint_to_tools.get(agent_hint,
                                cfg.get("tools", {}).get("enabled_sets", None))

    registry = ToolRegistry(enabled_sets=enabled)
    tools = registry.get_tools()

    agent = Agent(tools=tools)

    # ── share parent stop_event so Ctrl+C propagates ──
    if stop_event is not None:
        agent.stop_event = stop_event
    # Re-wire stop_event to tools (Agent.__init__ wired a fresh Event)
    for t in agent.tools.values():
        if hasattr(t, 'stop_event'):
            t.stop_event = agent.stop_event

    # ── suppress stdout events for sub-agent (would confuse TUI) ──
    agent.emit = lambda event: None
    agent._confirm_callback = None
    # ── suppress DB persistence for sub-agent (no session_id) ──
    agent.hooks = HookRegistry()
    agent.session_id = 0  # prevents add_user_message from auto-creating a session

    # ── set turn limit for sub-tasks (higher for research) ──
    agent.max_llm_calls = cfg.get("sub_agent_max_llm_calls", 6)

    # ── inherit parent workspace ──
    if workspace_root:
        agent._workspace_root = workspace_root
        os.chdir(workspace_root)

    # ── Use a minimal prompt for sub-agents (skip full base prompt noise) ──
    _RESEARCH_PROMPT = (
        "You are a focused research assistant. Your task is to search the web "
        "for specific information, extract key findings, and report them clearly. "
        "Always cite your sources. Be concise and factual. "
        "Do NOT use memory tools — they are not available.\n\n"
    )
    agent.llm.system_prompt = _RESEARCH_PROMPT

    return agent


async def run_task(agent: Agent, task: str, agent_hint: str = "any",
                   predecessor_results: dict[str, str] = None) -> str:
    extra = _make_system_prompt_extra(task, agent_hint, predecessor_results)
    agent.llm.system_prompt = agent.llm.system_prompt + "\n\n" + extra
    # ── inject task and run ──
    await agent.add_user_message(task)
    await agent.process_with_llm()
    for msg in reversed(agent.chat_history):
        if msg.get("role") == "agent":
            return msg.get("content", "")
    return "[no response]"
