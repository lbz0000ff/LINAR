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
            lambda m: os.environ.get(m.group(1), m.group(0)),
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
    "providers": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
        },
    },
    "llm": {
        "provider": "deepseek",
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
    "logging": {
        "level": "INFO",
        "file": "logs/lily.log",
        "max_bytes": 10485760,
        "backup_count": 7,
        "console": True,
    },
    "tools": {
        "enabled_sets": ["time", "file", "shell", "web"],
    },
    "chat_history": {
        "max_chars": 10000,
        "trim_to": 5000,
        "protect_last_turns": 3,
        "strategy": "compact",  # "compact" | "compress"
    },
    "aux": {
        "provider": "deepseek",
        "model": "",
        "temperature": 0.3,
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


def _resolve_providers(config):
    """Fill base_url/api_key into llm/aux from their referenced provider."""
    providers = config.get("providers", {})
    for key in ("llm", "aux"):
        section = config.get(key)
        if not section:
            continue
        pname = section.get("provider")
        if pname and pname in providers:
            p = providers[pname]
            section.setdefault("base_url", p.get("base_url", ""))
            section.setdefault("api_key", p.get("api_key", ""))
    return config


def _deep_merge(base, override):
    """Recursively merge override into base (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _read_api_key_file() -> str:
    """Read api_key.txt from project root as fallback."""
    txt_path = os.path.join(os.path.dirname(__file__), "..", "api_key.txt")
    try:
        with open(txt_path, "r") as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def load_config(path=None):
    """Load config.yaml and merge with DEFAULTS.

    Returns a flat-or-nested dict guaranteed to have all keys from DEFAULTS.
    Missing fields in the YAML file fall back to DEFAULTS values.
    """
    config_path = path or _CONFIG_PATH

    # Auto-create config.yaml from example if missing
    if not os.path.exists(config_path):
        example_path = config_path + ".example"
        if os.path.exists(example_path):
            try:
                import shutil
                shutil.copy2(example_path, config_path)
            except Exception:
                pass

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

    config = _resolve_env(config)
    config = _resolve_providers(config)

    # ── API key fallback: env var → api_key.txt ──
    for key in ("llm", "aux"):
        ak = config.get(key, {}).get("api_key", "")
        if not ak or ak.startswith("${"):
            file_key = _read_api_key_file()
            if file_key:
                config[key]["api_key"] = file_key

    return config
