"""Agent factory — create agent instances for DAG sub-tasks.

In a multi-agent execution, each DAG node gets its own Agent instance
with an isolated LLM, tool set, and chat history.
"""

from __future__ import annotations

import json
import os
import threading
from config import load_config
from logger import get_logger
from tool_registry import ToolRegistry
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
                 stop_event: threading.Event | None = None) -> Agent:
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
        "research": ["time", "web", "memory"],
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

    # ── set low turn limit for sub-tasks ──
    agent.max_turns = cfg.get("sub_agent_max_turns", 3)

    return agent


def run_task(agent: Agent, task: str, agent_hint: str = "any",
             predecessor_results: dict[str, str] = None) -> str:
    """Run a single task on the given agent and return the result text.

    Parameters
    ----------
    agent : Agent
        The agent to run the task on.
    task : str
        The task description / instruction.
    agent_hint : str
        Role hint for the system prompt.
    predecessor_results : dict, optional
        Results from predecessor nodes.

    Returns
    -------
    str
        The agent's final answer.
    """
    # ── inject task context into system prompt ──
    extra = _make_system_prompt_extra(task, agent_hint, predecessor_results)
    agent.llm.system_prompt = agent.llm.system_prompt + "\n\n" + extra

    # ── set up chat history ──
    agent.add_user_message(task)

    # ── run ──
    agent.process_with_llm()

    # ── extract the final agent answer ──
    for msg in reversed(agent.chat_history):
        if msg.get("role") == "agent":
            return msg.get("content", "")
    return "[no response]"
