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
import platform

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


def _find_git_bash() -> str | None:
    """Locate Git Bash on Windows."""
    for base in (
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    ):
        git = os.path.join(base, "Git", "bin", "bash.exe")
        if os.path.isfile(git):
            return git
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(os.path.dirname(path) if path else "", "bash.exe")
        if os.path.isfile(candidate):
            return candidate
        git_exe = os.path.join(path, "git.exe")
        if os.path.isfile(git_exe):
            bash = os.path.join(os.path.dirname(path), "bin", "bash.exe")
            if os.path.isfile(bash):
                return bash
    return None


def _is_running_in_bash() -> bool:
    return bool(os.environ.get("BASH")) or "bash" in (os.environ.get("SHELL", "") or "").lower()


def _launch_tui() -> None:
    """Launch TUI with proper working directory."""
    os.chdir(_project_root)
    if platform.system() != "Windows" or _is_running_in_bash():
        subprocess.run([sys.executable, "-m", "agent.cli.terminal"])
        return
    # Windows outside Bash → try Git Bash for better terminal UX
    bash = _find_git_bash()
    if bash:
        print("Launching via Git Bash…")
        subprocess.run([bash, "--login", "-i", "-c", f'cd "{_project_root}" && python -m agent.cli.terminal'])
        return
    subprocess.run([sys.executable, "-m", "agent.cli.terminal"])


def _launch_web() -> None:
    """Launch the WebSocket + HTTP server."""
    os.chdir(_project_root)
    sys.path.insert(0, os.path.join(_project_root, "webui"))
    import agent_server
    agent_server.main()


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
