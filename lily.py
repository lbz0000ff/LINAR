#!/usr/bin/env python3
"""EchoLily — bootstrap launcher.

Auto-installs dependencies on first run, then starts the agent.
Usage:
    python lily.py                  # TUI (default)
    python lily.py --web            # Web interface
"""

import sys
import os
import subprocess

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_REQUIREMENTS = os.path.join(_project_root, "agent", "requirements.txt")

# ── packages checked for "is it installed?" ──────────────────────
_CORE_DEPS = ("yaml", "openai", "prompt_toolkit", "fastapi")


def _ensure_deps() -> None:
    """Auto-install Python dependencies if missing."""
    missing = []
    for mod in _CORE_DEPS:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        return

    if not os.path.exists(_REQUIREMENTS):
        print(f"[lily] requirements.txt not found at {_REQUIREMENTS}, skipping auto-install")
        return

    # 优先使用 uv（更快，全局缓存），回退 pip
    try:
        subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=10)
        installer = ["uv", "pip", "install", "-r", _REQUIREMENTS]
        label = "uv"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        installer = [sys.executable, "-m", "pip", "install", "-r", _REQUIREMENTS]
        label = "pip"

    print(f"[lily] Installing Python dependencies via {label} ({len(missing)} packages missing)...")
    try:
        subprocess.check_call(installer, stdout=subprocess.DEVNULL)
        print(f"[lily] Dependencies installed successfully ({label})")
    except subprocess.CalledProcessError as e:
        print(f"[lily] {label} install failed (exit {e.returncode}), continuing anyway...")
    except FileNotFoundError:
        print(f"[lily] {label} not found, continuing anyway...")


def _launch_tui() -> None:
    """Launch TUI with proper working directory."""
    os.chdir(_project_root)
    subprocess.run([sys.executable, "-m", "agent.cli.terminal"])


def _launch_web() -> None:
    """Launch the FastAPI HTTP + WebSocket server."""
    os.chdir(_project_root)
    sys.path.insert(0, os.path.join(_project_root, "agent"))
    import uvicorn
    uvicorn.run("api.app:app", host="127.0.0.1", port=8080, log_level="info")


def main() -> None:
    # 1. Bootstrap: install deps if missing
    _ensure_deps()

    # 2. Launch
    if "--web" in sys.argv:
        _launch_web()
    else:
        _launch_tui()


if __name__ == "__main__":
    main()
