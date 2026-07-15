from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tool_registry


def test_resolve_mcp_args_appends_bearer_header_from_provider() -> None:
    server = {
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://example.test/mcp"],
        "auth_provider": "stepfun",
    }
    config = {"providers": {"stepfun": {"api_key": "step-secret-key"}}}

    resolved = tool_registry._resolve_mcp_args(server, config)

    assert resolved == [
        "-y",
        "mcp-remote",
        "https://example.test/mcp",
        "--header",
        "Authorization: Bearer step-secret-key",
    ]
    assert server["args"] == ["-y", "mcp-remote", "https://example.test/mcp"]


def test_resolve_mcp_args_rejects_missing_provider_key() -> None:
    server = {"args": ["mcp-remote"], "auth_provider": "stepfun"}

    with pytest.raises(ValueError, match="stepfun"):
        tool_registry._resolve_mcp_args(
            server,
            {"providers": {"stepfun": {"api_key": ""}}},
        )


def test_resolve_mcp_args_reuses_effective_llm_key_for_same_provider() -> None:
    server = {"args": ["mcp-remote"], "auth_provider": "stepfun"}
    config = {
        "providers": {"stepfun": {"api_key": "${STEPFUN_API_KEY}"}},
        "llm": {"provider": "stepfun", "api_key": "api-key-file-fallback"},
    }

    resolved = tool_registry._resolve_mcp_args(server, config)

    assert resolved[-1] == "Authorization: Bearer api-key-file-fallback"
