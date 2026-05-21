"""Tool permission manager — allow / ask / deny with mode support."""

from __future__ import annotations

import fnmatch


class PermissionManager:
    """Per-tool permission control with mode switching.

    Supports three modes (Safe / Auto / Review) switchable at runtime
    via ``switch_mode()``.  Auto mode hardcodes ``"allow"`` for every
    tool; Safe and Review read their rules from config.

    Priority (highest to lowest)::

        1. Runtime override (set by user via always / never)
        2. Auto mode — everything ``"allow"``
        3. Active mode's exact rule match  (``rules``)
        4. Active mode's glob rule match   (``rules`` with wildcards)
        5. Active mode's default level     (or ``"ask"``)
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.default: str = cfg.get("default", "ask")
        self.rules: dict[str, str] = cfg.get("rules", {})
        self._overrides: dict[str, str] = {}

        # ── mode support ─────────────────────────────────────
        self._modes: dict[str, dict] = {}
        self._active_mode: str = "safe"
        self._mode_default_override: str = "ask"
        self._mode_rules: dict[str, str] = {}

    # ── mode public API ───────────────────────────────────────

    def load_modes(self, modes_config: dict) -> None:
        """Load mode definitions from config.

        *modes_config* is the ``permission_modes`` section (with
        ``active`` and ``modes`` keys).
        """
        modes_cfg = modes_config.get("modes", {})
        if not modes_cfg:
            return
        self._modes = modes_cfg
        initial = modes_config.get("active", "safe")
        self.switch_mode(initial)

    def switch_mode(self, name: str) -> None:
        """Switch to a named mode (safe / auto / review)."""
        self.clear_all_overrides()
        self._active_mode = name

        if name == "auto":
            self._mode_rules = {}
            self._mode_default_override = "allow"
            return

        mode_cfg = self._modes.get(name, {})
        self._mode_default_override = mode_cfg.get("default", "ask")
        self._mode_rules = mode_cfg.get("rules", {})

    @property
    def mode(self) -> str:
        """Return the active mode name (safe / auto / review)."""
        return self._active_mode

    # ── original public API ───────────────────────────────────

    def check(self, tool_name: str) -> str:
        """Return the effective permission level for *tool_name*.

        Returns one of ``"allow"``, ``"ask"``, ``"deny"``.
        """
        # 1. Runtime override (user-picked always / never)
        if tool_name in self._overrides:
            return self._overrides[tool_name]

        # 2. Auto mode — everything allowed
        if self._active_mode == "auto":
            return "allow"

        # 3. Active mode's exact rule match
        if tool_name in self._mode_rules:
            return self._mode_rules[tool_name]

        # 4. Active mode's glob rule match
        for pattern, level in self._mode_rules.items():
            if "*" in pattern or "?" in pattern:
                if fnmatch.fnmatch(tool_name, pattern):
                    return level

        # 5. Active mode's default (or "ask")
        return self._mode_default_override

    def set_override(self, tool_name: str, level: str) -> None:
        """Set a runtime override (e.g. after user picks 'always')."""
        self._overrides[tool_name] = level

    def clear_override(self, tool_name: str) -> None:
        """Remove a runtime override, reverting to config rules."""
        self._overrides.pop(tool_name, None)

    def clear_all_overrides(self) -> None:
        """Reset all runtime overrides (e.g. on mode switch)."""
        self._overrides.clear()
