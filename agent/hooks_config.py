"""Hook configuration loader for EchoLily.

This module provides functions to load hook configuration from YAML
and register hooks into the HookRegistry.

Expected config format:
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
    - event: state_enter
      handler: hooks_builtin.log_state_transition
      priority: 50
      name: builtin_state_logger
```
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any

# Add agent directory to path for imports
agent_dir = os.path.dirname(os.path.abspath(__file__))
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

import logger

log = logger.get_logger(__name__)

from hooks import HookEvent, HookRegistry

from logger import get_logger

log = get_logger(__name__)

from hooks import HookEvent, HookRegistry


# ──────────────────────────────────────────────────────────────────────────────
# Configuration Validation
# ──────────────────────────────────────────────────────────────────────────────


def validate_hook_config(config: dict) -> list[str] | None:
    """Validate hook configuration.

    Args:
        config: Hook configuration dictionary

    Returns:
        List of error messages, or None if valid
    """
    errors = []

    if not isinstance(config.get("enabled", True), bool):
        errors.append("hooks.enabled must be boolean")

    if "default_timeout" in config:
        timeout = config["default_timeout"]
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            errors.append("hooks.default_timeout must be positive number")

    if "register" in config:
        register_list = config.get("register")
        if register_list is None:
            # Empty register list is valid
            pass
        elif not isinstance(register_list, list):
            errors.append("hooks.register must be a list")
        else:
            for i, hook_config in enumerate(register_list):
                if not isinstance(hook_config, dict):
                    errors.append(f"hooks.register[{i}] must be a dict")
                    continue

                if "event" not in hook_config:
                    errors.append(f"hooks.register[{i}] missing 'event' field")
                else:
                    event_name = hook_config["event"]
                    try:
                        HookEvent[event_name.upper()]
                    except KeyError:
                        errors.append(
                            f"hooks.register[{i}] invalid event: {event_name}"
                        )

                if "handler" not in hook_config:
                    errors.append(f"hooks.register[{i}] missing 'handler' field")

                if "priority" in hook_config:
                    priority = hook_config["priority"]
                    if not isinstance(priority, int):
                        errors.append(
                            f"hooks.register[{i}] priority must be integer"
                        )

                if "timeout" in hook_config:
                    timeout = hook_config["timeout"]
                    if not isinstance(timeout, (int, float)) or timeout <= 0:
                        errors.append(
                            f"hooks.register[{i}] timeout must be positive number"
                        )

    return errors if errors else None


# ──────────────────────────────────────────────────────────────────────────────
# Handler Loading
# ──────────────────────────────────────────────────────────────────────────────


def load_handler(handler_path: str) -> Any:
    """Load a handler function from a module path.

    Args:
        handler_path: Module.function or function_name (for builtin hooks)

    Returns:
        Handler function

    Raises:
        ImportError: If module cannot be imported
        AttributeError: If function not found in module
        ValueError: If builtin hook not found
    """
    # Check for builtin hook first
    from hooks_builtin import HOOK_BUILTIN_REGISTRY

    if handler_path in HOOK_BUILTIN_REGISTRY:
        return HOOK_BUILTIN_REGISTRY[handler_path]

    # Parse module.function
    if "." not in handler_path:
        raise ValueError(
            f"Handler '{handler_path}' not found and is not a module.function path"
        )

    module_name, func_name = handler_path.rsplit(".", 1)

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(f"Cannot import module '{module_name}': {e}")

    try:
        handler = getattr(module, func_name)
    except AttributeError:
        raise AttributeError(
            f"Module '{module_name}' has no function '{func_name}'"
        )

    # Verify it's callable
    if not callable(handler):
        raise ValueError(f"'{handler_path}' is not callable")

    return handler


# ──────────────────────────────────────────────────────────────────────────────
# Configuration Loading
# ──────────────────────────────────────────────────────────────────────────────


def load_hooks_from_config(config: dict, registry: HookRegistry) -> None:
    """Load hooks from configuration and register into registry.

    Args:
        config: Hooks configuration dictionary
        registry: HookRegistry to register hooks into
    """
    # Check if hooks are enabled
    if not config.get("enabled", True):
        log.info("Hooks disabled in config")
        return

    # Validate configuration
    errors = validate_hook_config(config)
    if errors:
        log.error("Invalid hook configuration: %s", errors)
        raise ValueError(f"Invalid hook configuration: {errors}")

    register_list = config.get("register", [])
    default_timeout = config.get("default_timeout", 5.0)

    if not register_list:
        log.debug("No hooks to register from config")
        return

    # Register each hook
    for i, hook_config in enumerate(register_list):
        try:
            # Parse event
            event_name = hook_config["event"]
            event = HookEvent[event_name.upper()]

            # Load handler
            handler_path = hook_config["handler"]
            handler = load_handler(handler_path)

            # Parse other fields
            name = hook_config.get("name", handler.__name__)
            priority = hook_config.get("priority", 100)
            timeout = hook_config.get("timeout", default_timeout)
            source = hook_config.get("source", "config")

            # Register
            registry.register(event, handler, name, priority, timeout, source)

            log.debug(
                "Registered hook from config: %s for event %s (priority=%d)",
                name,
                event.name,
                priority,
            )

        except Exception as e:
            log.warning(
                "Failed to load hook from config at index %d: %s", i, e
            )
            # Continue loading other hooks


# ──────────────────────────────────────────────────────────────────────────────
# Default Configuration
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_HOOKS_CONFIG = {
    "enabled": True,
    "default_timeout": 5.0,
    "register": [
        # State transition logging
        {
            "event": "state_enter",
            "handler": "hooks_builtin.log_state_transition",
            "priority": 50,
            "name": "builtin_state_logger",
            "timeout": 1.0,
        },
        # Tool call logging
        {
            "event": "pre_tool_use",
            "handler": "hooks_builtin.log_tool_call",
            "priority": 50,
            "name": "builtin_tool_logger",
            "timeout": 1.0,
        },
        {
            "event": "tool_error",
            "handler": "hooks_builtin.log_tool_error",
            "priority": 50,
            "name": "builtin_tool_error_logger",
            "timeout": 1.0,
        },
        # Persistence (fire-and-forget, higher timeout for db ops)
        {
            "event": "user_message",
            "handler": "hooks_builtin.persist_user_message",
            "priority": 100,
            "name": "builtin_db_user_persist",
            "timeout": 10.0,
        },
        {
            "event": "agent_response",
            "handler": "hooks_builtin.persist_agent_response",
            "priority": 100,
            "name": "builtin_db_agent_persist",
            "timeout": 10.0,
        },
        {
            "event": "post_tool_use",
            "handler": "hooks_builtin.persist_tool_result",
            "priority": 100,
            "name": "builtin_db_tool_persist",
            "timeout": 10.0,
        },
        # Usage tracking
        {
            "event": "llm_usage",
            "handler": "hooks_builtin.track_usage",
            "priority": 100,
            "name": "builtin_usage_tracker",
            "timeout": 1.0,
        },
        # Planning logging
        {
            "event": "plan_created",
            "handler": "hooks_builtin.log_plan_creation",
            "priority": 50,
            "name": "builtin_plan_logger",
            "timeout": 1.0,
        },
        {
            "event": "plan_node_complete",
            "handler": "hooks_builtin.log_plan_node_execution",
            "priority": 50,
            "name": "builtin_plan_node_logger",
            "timeout": 1.0,
        },
        # Skill logging
        {
            "event": "skill_load",
            "handler": "hooks_builtin.log_skill_load",
            "priority": 50,
            "name": "builtin_skill_load_logger",
            "timeout": 1.0,
        },
        {
            "event": "skill_unload",
            "handler": "hooks_builtin.log_skill_unload",
            "priority": 50,
            "name": "builtin_skill_unload_logger",
            "timeout": 1.0,
        },
        # Permission logging
        {
            "event": "permission_check",
            "handler": "hooks_builtin.log_permission_check",
            "priority": 50,
            "name": "builtin_permission_logger",
            "timeout": 1.0,
        },
        {
            "event": "tool_denied",
            "handler": "hooks_builtin.log_tool_denied",
            "priority": 50,
            "name": "builtin_tool_denied_logger",
            "timeout": 1.0,
        },
    ],
}