#!/usr/bin/env python3
"""LINAR — bootstrap launcher.

Auto-installs dependencies on first run, then starts the agent.
Usage:
    python linar.py                  # TUI (default)
    python linar.py --gui            # Electron GUI (backend + Vite/Electron)
    python linar.py --web            # Production web server
"""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_REQUIREMENTS = os.path.join(_project_root, "requirements.txt")

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
        print(f"[linar] requirements.txt not found at {_REQUIREMENTS}, skipping auto-install")
        return

    # 优先使用 uv（更快，全局缓存），回退 pip
    try:
        subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=10)
        installer = ["uv", "pip", "install", "-r", _REQUIREMENTS]
        label = "uv"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        installer = [sys.executable, "-m", "pip", "install", "-r", _REQUIREMENTS]
        label = "pip"

    print(f"[linar] Installing Python dependencies via {label} ({len(missing)} packages missing)...")
    try:
        subprocess.check_call(installer, stdout=subprocess.DEVNULL)
        print(f"[linar] Dependencies installed successfully ({label})")
    except subprocess.CalledProcessError as e:
        print(f"[linar] {label} install failed (exit {e.returncode}), continuing anyway...")
    except FileNotFoundError:
        print(f"[linar] {label} not found, continuing anyway...")


def _launch_tui() -> None:
    """Launch TUI with proper working directory."""
    os.chdir(_project_root)
    subprocess.run([sys.executable, "-m", "agent.cli.terminal"])


def _backend_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, "main.py", "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    return cmd


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Terminate a process and its children on Windows/macOS/Linux."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return


def _popen(
    cmd: list[str],
    cwd: str,
    *,
    pipe: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    kwargs = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
    }
    if pipe:
        kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT})
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _select_backend_port(host: str, requested_port: int | None) -> int:
    """Return an available backend port, preserving explicitly requested ports."""
    if requested_port is not None:
        return requested_port

    for candidate in (8080, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, candidate))
                return int(sock.getsockname()[1])
        except OSError as exc:
            if candidate == 8080:
                print(f"[linar] Port 8080 unavailable ({exc}); selecting another port")
                continue
            raise

    raise RuntimeError("Unable to select a backend port")


def _select_gui_port(requested_port: int | None) -> int:
    """Return an available IPv4 loopback port for the Vite dev server."""
    if requested_port is not None:
        return requested_port

    for candidate in (5173, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", candidate))
                return int(sock.getsockname()[1])
        except OSError as exc:
            if candidate == 5173:
                print(f"[linar] Port 5173 unavailable ({exc}); selecting another GUI port")
                continue
            raise

    raise RuntimeError("Unable to select a GUI port")


def _backend_origin(host: str, port: int) -> str:
    client_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{client_host}:{port}"


def _gui_origin(port: int) -> str:
    """Return the browser-visible origin for the local Vite server."""
    return f"http://127.0.0.1:{port}"


def _stream_output(proc: subprocess.Popen, prefix: str) -> None:
    if proc.stdout is None:
        return
    for line in proc.stdout:
        print(f"{prefix} {line}", end="")


def _launch_web(args: argparse.Namespace) -> None:
    """Launch the FastAPI server in a subprocess (keeps terminal clean)."""
    agent_dir = os.path.join(_project_root, "agent")
    proc = _popen(_backend_cmd(args), agent_dir)
    print(f"[linar] Web UI started at http://{args.host}:{args.port}")
    print("[linar] Press Ctrl+C to stop")
    try:
        proc.wait()
    except KeyboardInterrupt:
        _terminate_tree(proc)


def _launch_gui(args: argparse.Namespace) -> None:
    """Launch FastAPI backend plus the Electron/Vite development GUI."""
    gui_dir = os.path.join(_project_root, "gui")
    node_modules = os.path.join(gui_dir, "node_modules")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        print("[linar] npm not found. Install Node.js 18+ and run: cd gui && npm install")
        raise SystemExit(1)
    if not os.path.isdir(node_modules):
        print("[linar] gui/node_modules not found. Run: cd gui && npm install")
        raise SystemExit(1)

    agent_dir = os.path.join(_project_root, "agent")
    gui_env = os.environ.copy()
    gui_env["LINAR_BACKEND_ORIGIN"] = _backend_origin(args.host, args.port)
    gui_env["LINAR_GUI_HOST"] = "127.0.0.1"
    gui_env["LINAR_GUI_PORT"] = str(args.gui_port)
    gui_env["LINAR_GUI_ORIGIN"] = _gui_origin(args.gui_port)
    api_proc = _popen(_backend_cmd(args), agent_dir, pipe=True)
    gui_proc = _popen([npm, "run", "dev"], gui_dir, pipe=True, env=gui_env)

    print(f"[linar] Backend started at http://{args.host}:{args.port}")
    print(f"[linar] Vite frontend starting at {_gui_origin(args.gui_port)}")
    print("[linar] Electron GUI starting via npm run dev")
    print("[linar] Press Ctrl+C to stop both processes")

    threads = [
        threading.Thread(target=_stream_output, args=(api_proc, "[api]"), daemon=True),
        threading.Thread(target=_stream_output, args=(gui_proc, "[gui]"), daemon=True),
    ]
    for thread in threads:
        thread.start()

    processes = [api_proc, gui_proc]
    exit_code = 0
    try:
        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    exit_code = code
                    raise SystemExit
            time.sleep(0.2)
    except KeyboardInterrupt:
        exit_code = 130
    except SystemExit:
        pass
    finally:
        for proc in processes:
            _terminate_tree(proc)
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if exit_code not in (0, 130):
            raise SystemExit(exit_code)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LINAR launcher")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web", action="store_true", help="Start production web server")
    mode.add_argument("--gui", action="store_true", help="Start backend and Electron GUI")
    parser.add_argument("--host", default="127.0.0.1", help="Backend bind address")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Backend port (default: 8080 when available, otherwise an available port)",
    )
    parser.add_argument(
        "--gui-port",
        type=int,
        default=None,
        help="Vite GUI port (default: 5173 when available, otherwise an available port)",
    )
    parser.add_argument("--reload", action="store_true", help="Enable backend auto-reload")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # 1. Bootstrap: install deps if missing
    _ensure_deps()

    if args.web or args.gui:
        args.port = _select_backend_port(args.host, args.port)
    if args.gui:
        args.gui_port = _select_gui_port(args.gui_port)

    # 2. Launch
    if args.web:
        _launch_web(args)
    elif args.gui:
        _launch_gui(args)
    else:
        _launch_tui()


if __name__ == "__main__":
    main()
