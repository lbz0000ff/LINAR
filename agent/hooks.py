"""Hooks system for EchoLily.

This module provides a comprehensive hook system that allows cross-cutting
concerns (logging, metrics, persistence, etc.) to be registered as event
handlers throughout the agent lifecycle.

Design principles:
- Non-breaking: Existing behavior preserved when no hooks are registered
- Zero overhead: Fast-path skip when no hooks registered for an event
- Type-safe: Full type annotations, dataclasses for context
- Error isolation: Single hook failure doesn't affect others
- Priority-based: Hooks execute in priority order (lower = first)
- Async-first: Support both sync and async handlers
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Coroutine

# Add agent directory to path for imports
agent_dir = os.path.dirname(os.path.abspath(__file__))
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

import logger

if TYPE_CHECKING:
    # Agent is defined in agent.py, avoid circular import
    pass

log = logger.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Hook Events
# ──────────────────────────────────────────────────────────────────────────────


class HookEvent(Enum):
    """All hook events supported by EchoLily.

    Events are grouped by lifecycle category. Each event receives a HookContext
    with relevant fields populated.
    """

    # ── Agent lifecycle ───────────────────────────────────────────────────────
    AGENT_INIT = auto()  # After Agent.__init__ completes
    AGENT_READY = auto()  # Agent enters ready state (emit "ready")
    AGENT_SHUTDOWN = auto()  # Agent is shutting down

    # ── Conversation lifecycle ───────────────────────────────────────────────
    USER_MESSAGE = auto()  # User message received (before processing)
    AGENT_RESPONSE = auto()  # Agent response generated (after LLM call)
    CONVERSATION_ROUND_END = auto()  # One round of conversation completed

    # ── FSM state transitions ────────────────────────────────────────────────
    STATE_ENTER = auto()  # Entering any FSM stage
    STATE_EXIT = auto()  # Exiting any FSM stage

    # ── LLM interaction ─────────────────────────────────────────────────────
    LLM_START = auto()  # Before LLM streaming begins
    LLM_DONE = auto()  # After LLM streaming completes
    LLM_ERROR = auto()  # LLM call fails
    LLM_USAGE = auto()  # Token usage received

    # ── Tool lifecycle ───────────────────────────────────────────────────────
    PRE_TOOL_USE = auto()  # Before tool execution (existing)
    POST_TOOL_USE = auto()  # After tool execution (existing)
    TOOL_ERROR = auto()  # Tool execution fails
    TOOL_DENIED = auto()  # Tool denied by permission system

    # ── Permission ───────────────────────────────────────────────────────────
    PERMISSION_CHECK = auto()  # Permission being checked
    PERMISSION_PROMPT = auto()  # User being asked for permission

    # ── Planning / DAG ───────────────────────────────────────────────────────
    PLAN_CREATED = auto()  # Plan generated
    PLAN_NODE_START = auto()  # DAG node execution starts
    PLAN_NODE_COMPLETE = auto()  # DAG node execution completes
    PLAN_COMPLETE = auto()  # All plan nodes done

    # ── Skill lifecycle ─────────────────────────────────────────────────────
    SKILL_LOAD = auto()  # Skill loading
    SKILL_UNLOAD = auto()  # Skill unloading


# ──────────────────────────────────────────────────────────────────────────────
# Hook Types
# ──────────────────────────────────────────────────────────────────────────────

# Both sync and async handlers supported
# Use string reference to avoid forward reference issues
HookCallback = (
    Callable[["HookContext"], None | str | dict]
    | Callable[["HookContext"], Coroutine[Any, Any, None | str | dict]]
)

# Gate events: hooks can block execution
_GATE_EVENTS = {HookEvent.PRE_TOOL_USE, HookEvent.PERMISSION_CHECK}


# ──────────────────────────────────────────────────────────────────────────────
# Hook Context
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class HookContext:
    """Immutable context passed to every hook handler.

    Hooks receive read-only access to agent state via the agent field.
    Control flags (blocked, block_reason) can be set by gate hooks to
    influence execution flow.
    """

    event: HookEvent
    agent: Any  # Avoid circular import with agent.Agent
    timestamp: float

    # ── Optional fields populated per event ─────────────────────────────────────
    tool_name: str = ""
    tool_arguments: dict | str = ""
    tool_result: str = ""
    tool_error: str = ""

    stage: str = ""  # FSM stage name (for STATE_ENTER/EXIT)
    previous_stage: str = ""

    user_input: str = ""
    agent_text: str = ""

    usage_data: dict = field(default_factory=dict)

    plan_data: dict = field(default_factory=dict)
    node_id: str = ""
    node_result: str = ""

    skill_name: str = ""

    # ── Control flags (hooks can set these) ───────────────────────────────────
    blocked: bool = False
    block_reason: str = ""

    # ── Metadata ───────────────────────────────────────────────────────────────
    metadata: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Hook Entry
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class HookEntry:
    """A registered hook with metadata.

    Attributes:
        name: Human-readable identifier
        callback: Hook handler function
        event: Event type this hook responds to
        priority: Lower = runs first (0-99=system, 100-199=config, 200+=user)
        is_async: Detected from callback signature
        timeout: Per-hook timeout in seconds
        enabled: Whether this hook is active
        source: Origin identifier ("builtin", "config", "skill:<name>", "plugin:<name>")
    """

    name: str
    callback: HookCallback
    event: HookEvent
    priority: int = 100
    is_async: bool = False
    timeout: float = 5.0
    enabled: bool = True
    source: str = ""

    def __post_init__(self) -> None:
        """Detect if callback is async."""
        self.is_async = inspect.iscoroutinefunction(self.callback)


# ──────────────────────────────────────────────────────────────────────────────
# Hook Registry
# ──────────────────────────────────────────────────────────────────────────────


class HookRegistry:
    """Central registry and executor for all hook handlers.

    Features:
    - Thread-safe: Lock for registration mutations
    - Priority-based: Hooks execute in priority order (lower = first)
    - Error isolation: Single hook failure doesn't affect others
    - Gate events: PRE_TOOL_USE, PERMISSION_CHECK can block execution
    - Zero overhead: Fast-path skip when no hooks registered
    - Async-first: Support both sync and async handlers
    - Fire-and-forget: Non-blocking dispatch for observation events

    Example:
        registry = HookRegistry()

        # Register a sync hook
        def log_tool_call(ctx: HookContext) -> None:
            log.info("Tool: %s", ctx.tool_name)
        registry.register(HookEvent.PRE_TOOL_USE, log_tool_call, priority=50)

        # Register an async hook
        async def persist_result(ctx: HookContext) -> None:
            await db.save(ctx.tool_result)
        registry.register(HookEvent.POST_TOOL_USE, persist_result, priority=100)

        # Dispatch
        context = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            agent=agent,
            timestamp=time.time(),
            tool_name="search",
            tool_arguments={"query": "test"},
        )
        await registry.dispatch(context)
    """

    def __init__(self) -> None:
        """Initialize hook registry."""
        self._hooks: dict[HookEvent, list[HookEntry]] = {
            event: [] for event in HookEvent
        }
        self._lock = asyncio.Lock()

    # ── Registration ───────────────────────────────────────────────────────────

    def register(
        self,
        event: HookEvent,
        callback: HookCallback,
        name: str = "",
        priority: int = 100,
        timeout: float = 5.0,
        source: str = "",
    ) -> None:
        """Register a hook handler for a specific event.

        Args:
            event: Event type to respond to
            callback: Hook handler function (sync or async)
            name: Human-readable identifier (defaults to function name)
            priority: Lower = runs first (0-99=system, 100-199=config, 200+=user)
            timeout: Per-hook timeout in seconds
            source: Origin identifier
        """
        if not name:
            name = callback.__name__

        entry = HookEntry(
            name=name,
            callback=callback,
            event=event,
            priority=priority,
            timeout=timeout,
            source=source,
        )

        # Get or create hook list for this event
        hooks = self._hooks.get(event, [])
        hooks.append(entry)

        # Sort by priority (lower = first)
        hooks.sort(key=lambda e: e.priority)
        self._hooks[event] = hooks

        log.debug(
            "Hook registered: %s for event %s (priority=%d, source=%s)",
            name,
            event.name,
            priority,
            source,
        )

    def unregister(self, name: str) -> None:
        """Remove a hook by name.

        Args:
            name: Hook name to remove
        """
        for event, hooks in self._hooks.items():
            self._hooks[event] = [h for h in hooks if h.name != name]

        log.debug("Hook unregistered: %s", name)

    def unregister_by_source(self, source_prefix: str) -> None:
        """Remove all hooks with a given source prefix.

        Args:
            source_prefix: Source prefix to match (e.g., "skill:", "plugin:")
        """
        for event, hooks in self._hooks.items():
            self._hooks[event] = [
                h for h in hooks if not h.source.startswith(source_prefix)
            ]

        log.debug("Hooks unregistered for source: %s", source_prefix)

    def register_from_config(self, config: dict) -> None:
        """Load hooks from YAML config section.

        Expected format:
        ```yaml
        hooks:
          enabled: true
          default_timeout: 5.0
          register:
            - event: pre_tool_use
              handler: hooks_builtin.log_tool_call
              priority: 50
              name: builtin_tool_logger
              timeout: 2.0
        ```

        Args:
            config: Hooks configuration dictionary
        """
        if not config.get("enabled", True):
            return

        register_list = config.get("register", [])
        default_timeout = config.get("default_timeout", 5.0)

        for hook_config in register_list:
            try:
                # Parse event
                event_name = hook_config["event"]
                event = HookEvent[event_name.upper()]

                # Parse handler (module.function or function_name)
                handler_path = hook_config["handler"]
                if "." in handler_path:
                    module_name, func_name = handler_path.rsplit(".", 1)
                    module = __import__(module_name, fromlist=[func_name])
                    callback = getattr(module, func_name)
                else:
                    # For builtin hooks from hooks_builtin module
                    from hooks_builtin import HOOK_BUILTIN_REGISTRY

                    callback = HOOK_BUILTIN_REGISTRY.get(handler_path)
                    if callback is None:
                        log.warning("Builtin hook not found: %s", handler_path)
                        continue

                # Parse other fields
                name = hook_config.get("name", callback.__name__)
                priority = hook_config.get("priority", 100)
                timeout = hook_config.get("timeout", default_timeout)
                source = hook_config.get("source", "config")

                self.register(event, callback, name, priority, timeout, source)

            except Exception as e:
                log.warning("Failed to load hook from config: %s", e)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _invoke_callback(
        self, entry: HookEntry, context: HookContext
    ) -> None | str | dict:
        """Invoke a hook callback (sync or async)."""
        if entry.is_async:
            result = await entry.callback(context)
        else:
            result = await asyncio.to_thread(entry.callback, context)
        return result

    async def dispatch(self, context: HookContext) -> HookContext:
        """Dispatch an event to all registered hooks, in priority order.

        For gate events (PRE_TOOL_USE, PERMISSION_CHECK):
        - Hooks run sequentially, blocking
        - If any hook sets context.blocked = True, remaining hooks are skipped
        - Caller receives the (possibly blocked) context

        For observation events (all others):
        - Hooks run sequentially but should not block execution
        - Errors are logged but don't stop other hooks
        - Returns the (possibly modified) context

        Args:
            context: Hook context to pass to handlers

        Returns:
            The (possibly modified) context
        """
        entries = self._hooks.get(context.event, [])

        # Fast-path: no hooks registered
        if not entries:
            return context

        is_gate = context.event in _GATE_EVENTS

        for entry in entries:
            if not entry.enabled:
                continue

            try:
                result = await asyncio.wait_for(
                    self._invoke_callback(entry, context),
                    timeout=entry.timeout,
                )

                # Gate events: check if hook wants to block
                if is_gate and result:
                    if isinstance(result, dict) and result.get("block"):
                        context.blocked = True
                        context.block_reason = result.get("reason", "blocked")
                        log.debug(
                            "Gate hook '%s' blocked execution: %s",
                            entry.name,
                            context.block_reason,
                        )
                        break
                    elif isinstance(result, str):
                        # Legacy string return (for backward compat with _run_hook)
                        context.blocked = True
                        context.block_reason = result
                        break

            except asyncio.TimeoutError:
                log.warning(
                    "Hook '%s' timed out (%.1fs) on event %s",
                    entry.name,
                    entry.timeout,
                    context.event.name,
                )
            except Exception as e:
                log.warning(
                    "Hook '%s' failed on event %s: %s",
                    entry.name,
                    context.event.name,
                    e,
                )

        return context

    async def dispatch_fire_and_forget(self, context: HookContext) -> None:
        """Dispatch without waiting for completion.

        Used for observation events (logging, metrics) where latency matters
        more than ordering. Hooks are gathered as concurrent tasks but still
        run in priority order.

        Args:
            context: Hook context to pass to handlers
        """
        entries = self._hooks.get(context.event, [])

        # Fast-path: no hooks registered
        if not entries:
            return

        # Create tasks for each enabled hook
        tasks = []
        for entry in entries:
            if not entry.enabled:
                continue

            async def safe_invoke(entry: HookEntry, ctx: HookContext) -> None:
                try:
                    await asyncio.wait_for(
                        self._invoke_callback(entry, ctx),
                        timeout=entry.timeout,
                    )
                except asyncio.TimeoutError:
                    log.warning(
                        "Hook '%s' timed out (%.1fs) on event %s",
                        entry.name,
                        entry.timeout,
                        ctx.event.name,
                    )
                except Exception as e:
                    log.warning(
                        "Hook '%s' failed on event %s: %s",
                        entry.name,
                        ctx.event.name,
                        e,
                    )

            tasks.append(safe_invoke(entry, context))

        # Run all hooks concurrently (fire-and-forget) - create tasks but don't await them
        if tasks:
            # Create background tasks that will run independently
            for task in tasks:
                asyncio.create_task(task)
            # Return immediately, don't wait for tasks to complete

    # ── Introspection ─────────────────────────────────────────────────────────

    def list_hooks(self, event: HookEvent | None = None) -> list[HookEntry]:
        """Return registered hooks, optionally filtered by event.

        Args:
            event: Optional event filter

        Returns:
            List of registered hooks
        """
        if event:
            return self._hooks.get(event, []).copy()
        else:
            return [h for hooks in self._hooks.values() for h in hooks]

    def enable_hook(self, name: str) -> None:
        """Enable a hook by name.

        Args:
            name: Hook name to enable
        """
        for hooks in self._hooks.values():
            for entry in hooks:
                if entry.name == name:
                    entry.enabled = True

    def disable_hook(self, name: str) -> None:
        """Disable a hook by name.

        Args:
            name: Hook name to disable
        """
        for hooks in self._hooks.values():
            for entry in hooks:
                if entry.name == name:
                    entry.enabled = False


# ──────────────────────────────────────────────────────────────────────────────
# Legacy Event Name Mapping (for backward compatibility)
# ──────────────────────────────────────────────────────────────────────────────

# Map legacy event names (used in skill hooks) to new HookEvent
_LEGACY_HOOK_EVENT = {
    "PreToolUse": HookEvent.PRE_TOOL_USE,
    "PostToolUse": HookEvent.POST_TOOL_USE,
}

# Map new HookEvent back to legacy names
_HOOK_EVENT_TO_LEGACY = {v: k for k, v in _LEGACY_HOOK_EVENT.items()}