"""Tool permission manager — allow / ask / deny."""

from __future__ import annotations

import fnmatch


class PermissionManager:
    """Per-tool permission control with glob patterns and runtime overrides.

    Priority (highest to lowest)::

        1. Runtime override (set by user via always / never)
        2. Exact rule match  (config ``rules``)
        3. Glob rule match   (config ``rules`` with wildcards)
        4. Default level     (config ``default``)
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self.default: str = cfg.get("default", "ask")
        self.rules: dict[str, str] = cfg.get("rules", {})
        self._overrides: dict[str, str] = {}

    # ── public API ────────────────────────────────────────────

    def check(self, tool_name: str) -> str:
        """Return the effective permission level for *tool_name*.

        Returns one of ``"allow"``, ``"ask"``, ``"deny"``.
        """
        # 1. Runtime override
        if tool_name in self._overrides:
            return self._overrides[tool_name]

        # 2. Exact rule match
        if tool_name in self.rules:
            return self.rules[tool_name]

        # 3. Glob rule match
        for pattern, level in self.rules.items():
            if "*" in pattern or "?" in pattern:
                if fnmatch.fnmatch(tool_name, pattern):
                    return level

        # 4. Default
        return self.default

    def set_override(self, tool_name: str, level: str) -> None:
        """Set a runtime override (e.g. after user picks 'always')."""
        self._overrides[tool_name] = level

    def clear_override(self, tool_name: str) -> None:
        """Remove a runtime override, reverting to config rules."""
        self._overrides.pop(tool_name, None)

    def clear_all_overrides(self) -> None:
        """Reset all runtime overrides (e.g. on session reset)."""
        self._overrides.clear()
