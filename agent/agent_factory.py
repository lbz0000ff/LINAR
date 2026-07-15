"""Agent factory — create agent instances for DAG sub-tasks."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from openai import AsyncOpenAI
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
                 workspace_root: str | None = None,
                 model: str | None = None,
                 system_prompt: str | None = None,
                 use_aux: bool = False,
                 permission_mode: str | None = "auto",
                 tool_factory: Callable[[list[str] | None], dict] | None = None) -> Agent:
    """Create an Agent instance for a DAG sub-task.

    Parameters
    ----------
    agent_hint : str
        Hint for tool selection and system prompt tuning.
    predecessor_results : dict, optional
        Results from predecessor DAG nodes, keyed by node id.
    model : str, optional
        Override the LLM model for this agent.  When ``None`` the
        model is inherited from the main agent's config.
    system_prompt : str, optional
        Custom system prompt.  When set, it replaces the default
        ``_RESEARCH_PROMPT`` entirely.
    use_aux : bool
        Resolve provider credentials and the default model exclusively from
        the auxiliary runtime. Predefined DAG subagents set this to ``True``.
    tool_factory : callable, optional
        Build tools for the resolved tool sets. Benchmark runtimes use this to
        preserve workspace confinement across DAG subagents.

    Returns
    -------
    Agent
        A fresh agent with isolated tools and LLM.
    """
    cfg = load_config()

    # ── select tool set based on agent_hint ──
    hint_to_tools = {
        "code":     ["time", "file", "shell", "interactive"],
        "analysis": ["time", "file", "web", "memory", "vision"],
        "shell":    ["time", "shell"],
        "research": ["time","web", "file", "vision"],
    }
    enabled = hint_to_tools.get(agent_hint,
                                cfg.get("tools", {}).get("enabled_sets", None))

    if tool_factory is not None:
        tools = tool_factory(enabled)
    else:
        registry = ToolRegistry(enabled_sets=enabled)
        tools = registry.get_tools()

    agent = Agent(tools=tools)
    if permission_mode:
        agent.permissions.switch_mode(permission_mode)

    if use_aux:
        aux = cfg.get("aux") or {}
        provider = str(aux.get("provider") or "").strip()
        resolved_model = str(model or aux.get("model") or "").strip()
        base_url = str(aux.get("base_url") or "").strip()
        api_key = str(aux.get("api_key") or "").strip()
        if not provider:
            raise ValueError("aux.provider is required for predefined subagents")
        if provider not in (cfg.get("providers") or {}):
            raise ValueError(
                f"aux.provider '{provider}' is not configured in providers"
            )
        if not resolved_model:
            raise ValueError("aux.model is required when the subagent template has no model")
        if not base_url:
            raise ValueError("aux.base_url is required for predefined subagents")
        if not api_key:
            raise ValueError("aux.api_key is required for predefined subagents")
        agent.llm.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        agent.llm.provider = provider
        agent.llm.model = resolved_model
        log.info(
            "Sub-agent aux runtime: %s → %s/%s (%s)",
            agent_hint, provider, resolved_model, base_url,
        )
    elif model:
        agent.llm.model = model
        log.info("Sub-agent model override: %s → %s", agent_hint, model)

    # ── share parent stop_event so Ctrl+C propagates ──
    if stop_event is not None:
        agent.stop_event = stop_event
        agent._owns_stop_event = False
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
    # When a predefined subagent template provides its own system_prompt,
    # use that instead of the generic _RESEARCH_PROMPT.
    if system_prompt is not None:
        agent.llm.system_prompt = system_prompt
        agent._custom_system_prompt = True
    else:
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
