"""Style configuration loader for Lily Terminal.

Reads cli/style.yaml and merges with hardcoded defaults so every
key is guaranteed to exist even if the YAML file is missing.
"""

import os
import yaml

_STYLE_DIR = os.path.dirname(os.path.abspath(__file__))
_STYLE_PATH = os.path.join(_STYLE_DIR, "style.yaml")

DEFAULTS = {
    "banner": {
        "border": "grey",
        "lily": "grey85",
        "i": "red",
        "shadow": "grey",
        "title": "yellow",
        "hint": "grey62",
    },
    "console": {
        "header": "rgb(253, 96, 64)",
        "header_user": "bold cyan",
        "reasoning": "italic",
        "tool_name": "grey85",
        "tool_detail": "grey62",
        "error": "red",
        "stats_dim": "dim",
        "stats_good": "bold green",
        "stats_warn": "bold yellow",
        "stats_bad": "red",
        "new_session": "dim",
        "goodbye": "red",
    },
    "mode_colors": {
        "reasoning": {
            "hide": "red",
            "full": "yellow",
        },
        "tool_calls": {
            "hide": "red",
            "show_tools": "cyan",
            "detailed": "yellow",
        },
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


def load_style(path=None):
    """Load style.yaml and merge with DEFAULTS.

    Returns a nested dict guaranteed to have all keys from DEFAULTS.
    Missing fields in the YAML file fall back to DEFAULTS values.
    """
    style_path = path or _STYLE_PATH
    config = DEFAULTS.copy()

    if not os.path.exists(style_path):
        return config

    try:
        with open(style_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            _deep_merge(config, raw)
    except Exception:
        pass

    return config
