"""Built-in hook handlers for EchoLily.

This module provides default hook implementations for common cross-cutting
concerns: logging, persistence, metrics, etc.

Built-in hooks are registered by default but can be disabled via config.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

# Add agent directory to path for imports
agent_dir = os.path.dirname(os.path.abspath(__file__))
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

import logger

from hooks import HookContext

log = logger.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Builtin Hook Registry
# ──────────────────────────────────────────────────────────────────────────────

# Global registry of builtin hooks (for config-based loading)
HOOK_BUILTIN_REGISTRY: dict[str, any] = {}


def register_builtin(name: str, func: any) -> None:
    """Register a builtin hook by name.

    Args:
        name: Hook name
        func: Hook function
    """
    HOOK_BUILTIN_REGISTRY[name] = func


# ──────────────────────────────────────────────────────────────────────────────
# Logging Hooks
# ──────────────────────────────────────────────────────────────────────────────


def log_state_transition(context: HookContext) -> None:
    """Log FSM state transitions.

    Replaces manual log calls in orchestrator._transition().
    """
    if context.previous_stage and context.stage:
        log.info(
            "State transition: %s -> %s (session=%s)",
            context.previous_stage,
            context.stage,
            context.agent.session_id,
        )
    else:
        log.info(
            "State: %s (session=%s)",
            context.stage or context.previous_stage,
            context.agent.session_id,
        )


register_builtin("log_state_transition", log_state_transition)


def log_tool_call(context: HookContext) -> None:
    """Log tool invocations.

    Replaces manual log.info calls in agent.py tool execution.
    """
    if context.tool_name:
        log.info(
            "[session=%s round=%s] Tool: %s",
            context.agent.session_id,
            context.agent._conversation_round,
            context.tool_name,
        )


register_builtin("log_tool_call", log_tool_call)


# ──────────────────────────────────────────────────────────────────────────────
# Persistence Hooks
# ──────────────────────────────────────────────────────────────────────────────


async def persist_user_message(context: HookContext) -> None:
    """Persist user message to database.

    Replaces inline db.save_message() calls in agent.py.
    """
    import database as db
    import json

    if context.user_input:
        await asyncio.to_thread(
            db.save_message,
            context.agent.session_id,
            "user",
            context.user_input,
            conversation_round=context.agent._conversation_round,
        )


register_builtin("persist_user_message", persist_user_message)


async def persist_agent_response(context: HookContext) -> None:
    """Persist agent response to database.

    Replaces inline db.save_message() calls in agent.py.
    """
    import database as db
    import json

    if context.agent_text:
        # Get metadata (reasoning, tool_calls, prompt_tokens)
        metadata = context.metadata
        reasoning = metadata.get("reasoning", "")
        tool_calls = metadata.get("tool_calls", [])
        prompt_tokens = metadata.get("prompt_tokens", 0)

        # Build tool_calls JSON
        tool_calls_json = ""
        if tool_calls:
            tool_calls_json = json.dumps([
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"]
                    }
                }
                for tc in tool_calls
            ], ensure_ascii=False)

        await asyncio.to_thread(
            db.save_message,
            context.agent.session_id,
            "agent",
            context.agent_text,
            conversation_round=context.agent._conversation_round,
            reasoning=reasoning,
            tool_calls=tool_calls_json,
            prompt_tokens=prompt_tokens,
        )


register_builtin("persist_agent_response", persist_agent_response)


async def persist_tool_result(context: HookContext) -> None:
    """Persist tool result to database.

    Replaces inline db.save_message() calls in agent.py.
    """
    import database as db
    import json

    if context.tool_name and context.tool_result:
        await asyncio.to_thread(
            db.save_message,
            context.agent.session_id,
            "tool",
            json.dumps(
                {
                    "args": context.tool_arguments,
                    "result": context.tool_result,
                },
                ensure_ascii=False,
            ),
            tool_name=context.tool_name,
            conversation_round=context.agent._conversation_round,
            tool_call_id=context.metadata.get("tool_call_id", ""),
        )


register_builtin("persist_tool_result", persist_tool_result)


# ──────────────────────────────────────────────────────────────────────────────
# Usage/Metrics Hooks
# ──────────────────────────────────────────────────────────────────────────────


def track_usage(context: HookContext) -> None:
    """Track token usage.

    Adds secondary processing (billing aggregation, custom metrics) to the
    existing usage emission logic in agent.py.
    """
    if context.usage_data:
        log.debug(
            "Token usage: %s (session=%s round=%s)",
            context.usage_data,
            context.agent.session_id,
            context.agent._conversation_round,
        )
        # TODO: Add custom metrics, billing aggregation, etc.


register_builtin("track_usage", track_usage)


# ──────────────────────────────────────────────────────────────────────────────
# Error Hooks
# ──────────────────────────────────────────────────────────────────────────────


def log_tool_error(context: HookContext) -> None:
    """Log tool execution errors.

    Replaces manual error logging in agent.py tool execution.
    """
    if context.tool_error:
        log.warning(
            "Tool error: %s - %s (session=%s)",
            context.tool_name,
            context.tool_error,
            context.agent.session_id,
        )


register_builtin("log_tool_error", log_tool_error)


# ──────────────────────────────────────────────────────────────────────────────
# Planning Hooks
# ──────────────────────────────────────────────────────────────────────────────


def log_plan_creation(context: HookContext) -> None:
    """Log plan creation.

    Adds logging to orchestrator plan generation.
    """
    if context.plan_data:
        log.debug(
            "Plan created: %d tasks (session=%s)",
            len(context.plan_data.get("tasks", [])),
            context.agent.session_id,
        )


register_builtin("log_plan_creation", log_plan_creation)


def log_plan_node_execution(context: HookContext) -> None:
    """Log plan node execution.

    Adds logging to orchestrator DAG execution.
    """
    if context.node_id:
        status = "completed" if context.node_result else "failed"
        log.debug(
            "Plan node %s: %s (session=%s)",
            status,
            context.node_id,
            context.agent.session_id,
        )


register_builtin("log_plan_node_execution", log_plan_node_execution)


# ──────────────────────────────────────────────────────────────────────────────
# Skill Hooks
# ──────────────────────────────────────────────────────────────────────────────


def log_skill_load(context: HookContext) -> None:
    """Log skill loading.

    Replaces manual log calls in skill.py.
    """
    if context.skill_name:
        log.info("Skill loaded: %s", context.skill_name)


register_builtin("log_skill_load", log_skill_load)


def log_skill_unload(context: HookContext) -> None:
    """Log skill unloading.

    Replaces manual log calls in skill.py.
    """
    if context.skill_name:
        log.info("Skill unloaded: %s", context.skill_name)


register_builtin("log_skill_unload", log_skill_unload)


# ──────────────────────────────────────────────────────────────────────────────
# Permission Hooks
# ──────────────────────────────────────────────────────────────────────────────


def log_permission_check(context: HookContext) -> None:
    """Log permission checks.

    Adds visibility into which tools are being permission-checked.
    """
    if context.tool_name:
        log.debug(
            "Permission check: %s (session=%s)",
            context.tool_name,
            context.agent.session_id,
        )


register_builtin("log_permission_check", log_permission_check)


def log_tool_denied(context: HookContext) -> None:
    """Log tool denials.

    Records when a tool is denied due to permissions or user rejection.
    """
    if context.tool_name:
        reason = context.metadata.get("reason", "unknown")
        log.warning(
            "Tool denied: %s (reason=%s, session=%s)",
            context.tool_name,
            reason,
            context.agent.session_id,
        )


register_builtin("log_tool_denied", log_tool_denied)