#!/usr/bin/env python3
"""Lily — multi-platform unified launcher.

Usage:
    python lily.py
"""

import sys
import os
import subprocess
import platform

# Add project root to sys.path so `agent` is a top-level package
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _find_git_bash() -> str | None:
    """Locate Git Bash on Windows."""
    # 1) from git.exe
    git = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Git", "bin", "bash.exe")
    if os.path.isfile(git):
        return git
    git = os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Git", "bin", "bash.exe")
    if os.path.isfile(git):
        return git
    # 2) from PATH
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
    """Check if we're already running inside a Bash shell."""
    return bool(os.environ.get("BASH")) or "bash" in (os.environ.get("SHELL", "") or "").lower()


def _launch_windows() -> None:
    """Windows: prefer Git Bash, fallback to current shell."""
    if _is_running_in_bash():
        _run_tui()
        return

    bash = _find_git_bash()
    if bash:
        entry = f'cd "{_project_root}" && python -m agent.cli.terminal'
        print(f"Launching via Git Bash ({bash})…")
        subprocess.run([bash, "--login", "-i", "-c", entry])
        return

    _run_tui()


def _run_tui() -> None:
    """Run the TUI in a subprocess (avoids import/path issues)."""
    os.chdir(_project_root)
    subprocess.run([sys.executable, "-m", "agent.cli.terminal"])


def main() -> None:
    if platform.system() == "Windows":
        _launch_windows()
    else:
        _run_tui()


if __name__ == "__main__":
    main()
