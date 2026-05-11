"""Configuration loader — reads config.yaml with fallback defaults."""

import os
import re
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def _resolve_env(value):
    """Replace ${VAR_NAME} with the corresponding environment variable.

    Works on strings and walks dicts/lists recursively.
    """
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), ""),
            value,
        )
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value

# ---------------------------------------------------------------------------
# Schema-like defaults so every caller gets a valid dict
# ---------------------------------------------------------------------------
DEFAULTS = {
    "project_name": "Lily",
    "version": "1.0.0",
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-v4-flash",
        "temperature": 0.7,
        "max_tokens": 1000000,
        "top_p": 1.0,
    },
    "max_turns": 5,
    "max_memory_length": 2200,
    "max_user_preferences_length": 500,
    "show_reasoning": "hide",
    "show_tool_calls": "show_tools",  # "hide" | "show_tools" | "detailed"
    "confirmation_wait_time": 0,
    "terminal_max_tokens": 1000000,
    "tools": {
        "enabled_sets": ["time", "file", "shell", "web"],
    },
    "chat_history": {
        "max_chars": 10000,
        "trim_to": 5000,
        "protect_last_turns": 3,
        "strategy": "compact",  # "compact" | "compress"
    },
    "prompt": {
        "files": [
            "system_prompt_base.md",
            "SOUL.md",
            "USER.md",
            "MEMORY.md",
        ],
    },
}


def _deep_merge(base, override):
    """Recursively merge override into base (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=None):
    """Load config.yaml and merge with DEFAULTS.

    Returns a flat-or-nested dict guaranteed to have all keys from DEFAULTS.
    Missing fields in the YAML file fall back to DEFAULTS values.
    """
    config_path = path or _CONFIG_PATH
    config = DEFAULTS.copy()

    if not os.path.exists(config_path):
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            _deep_merge(config, raw)
    except Exception:
        pass

    return _resolve_env(config)
