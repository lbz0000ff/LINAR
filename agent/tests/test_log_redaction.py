import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logger import redact_sensitive, setup_logging


def test_redact_sensitive_common_secret_shapes():
    text = (
        "Authorization: Bearer as_sk_98fb4d0d5350043ef0902460d931b1d8 "
        "api_key: sk-live-1234567890 token=abc123456789XYZ "
        "'password': 'hunter2'"
    )

    redacted = redact_sensitive(text)

    assert "as_sk_98fb4d0d5350043ef0902460d931b1d8" not in redacted
    assert "sk-live-1234567890" not in redacted
    assert "abc123456789XYZ" not in redacted
    assert "hunter2" not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_logging_filter_redacts_formatted_args(tmp_path):
    log_file = tmp_path / "linar.log"
    setup_logging(log_file=str(log_file), console=False)

    logging.getLogger("test").info(
        "Starting MCP server: %s --header Authorization: Bearer %s",
        "npx",
        "as_sk_98fb4d0d5350043ef0902460d931b1d8",
    )

    content = log_file.read_text(encoding="utf-8")
    assert "as_sk_98fb4d0d5350043ef0902460d931b1d8" not in content
    assert "Bearer [REDACTED]" in content
