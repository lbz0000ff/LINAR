"""Centralized logging configuration for Lily Agent.

Provides a ``setup_logging()`` function that configures Python's ``logging``
module with both file and console handlers.  Call ``setup_logging()`` once
at startup; use ``get_logger(__name__)`` in every module to get a logger.

Log files are written to ``logs/lily.log`` with daily rotation, keeping
7 days of history.

Quick usage::

    from logger import get_logger

    log = get_logger(__name__)
    log.info("hello world")
    log.error("something went wrong", exc_info=True)
"""

import logging
import logging.handlers
import os
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "lily.log")

# ---------------------------------------------------------------------------
# Module-level state (avoids repeated setup)
# ---------------------------------------------------------------------------

_initialized = False
_console_handler: logging.Handler | None = None


def set_console_logging(enable: bool) -> bool:
    """Show or hide console log output at runtime.

    Returns the new state (``True`` = visible).
    """
    global _console_handler
    root = logging.getLogger()
    if enable:
        if _console_handler is not None and _console_handler not in root.handlers:
            root.addHandler(_console_handler)
    else:
        if _console_handler is not None and _console_handler in root.handlers:
            root.removeHandler(_console_handler)
    return enable


def console_logging_enabled() -> bool:
    """Return whether console log output is currently visible."""
    global _console_handler
    return _console_handler is not None and _console_handler in logging.getLogger().handlers


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,   # 10 MB per file
    backup_count: int = 7,
    console: bool = True,
) -> None:
    """Configure the root logger once.

    Parameters
    ----------
    level : str
        One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.
    log_file : str or None
        Path to the log file.  ``None`` → ``logs/lily.log`` under the project
        root.
    max_bytes : int
        Maximum size of a single log file before rotation.
    backup_count : int
        Number of rotated log files to retain.
    console : bool
        Whether to also emit log records to stderr.
    """
    global _initialized, _console_handler

    _level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()

    # ── clear any previous setup so reconfig works ──
    if _initialized:
        for h in list(root.handlers):
            root.removeHandler(h)
        _console_handler = None

    root.setLevel(_level)

    # ── formatter ────────────────────────────────────────────────
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── file handler (rotating) ──────────────────────────────────
    log_path = log_file or _LOG_FILE
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    fh.setLevel(_level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # ── console handler (stderr) ─────────────────────────────────
    if console:
        _console_handler = logging.StreamHandler(sys.stderr)
        _console_handler.setLevel(_level)
        _console_handler.setFormatter(fmt)
        root.addHandler(_console_handler)

    _initialized = True

    logging.getLogger(__name__).info(
        "Logging initialized: level=%s file=%s", level, log_path
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for *name* (typically ``__name__``).

    Ensures ``setup_logging()`` has been called at least once with
    defaults, so that ``get_logger`` is safe to use at module level.
    """
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)
