from .tool import Tool
import os
import platform
import subprocess
import re
import threading
import time
import string

# ── safety ──
_BLOCKED_COMMANDS = [
    "shutdown", "reboot", "halt", "poweroff",
    "init 0", "init 6",
    "mkfs", "dd", "fdisk", "parted", "format",
]
_BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r"rm\s+-rf\s+[/\\][a-zA-Z]",
    r">\s+/dev/sd",
    r"chmod\s+0\s+/",
    r"chown\s+[^ ]+\s+/",
    r":\(\)\s*\{",
    r"mv\s+/[/~]\s+/dev/null",
]

CMD_TIMEOUT = 60
CMD_MAX_OUTPUT = 100_000

# ── sudo support ──
_SUDO_PASSWORD_ENV = "SUDO_PASSWORD"
# Cache: True = NOPASSWD, False = needs password, None = untested
_SUDO_NOPASSWD_CACHE: bool | None = None
_SUDO_NOPASSWD_CACHE_LOCK = threading.Lock()

# ── background process storage ──
_bg_lock = threading.Lock()
_bg_counter = 0
_bg_processes: dict[str, dict] = {}

# ── exit code interpretation ──
_EXIT_CODE_NOTES: dict[str, dict[int, str]] = {
    "grep": {1: "no matches found"},
    "rg": {1: "no matches found"},
    "ag": {1: "no matches found"},
    "ack": {1: "no matches found"},
    "diff": {1: "files differ"},
    "find": {1: "inaccessible directories or no matches"},
    "test": {1: "condition evaluated to false"},
    "curl": {6: "could not resolve host",
             7: "failed to connect",
             28: "timeout"},
    "ssh": {255: "connection error"},
    "ping": {1: "host unreachable or ping timed out"},
    "rsync": {23: "partial transfer due to error",
              24: "partial transfer due to vanished source files"},
}


def _get_base_command(command: str) -> str:
    """Extract the base command name from a command string."""
    # Strip env vars at the start: VAR=value cmd
    stripped = command.lstrip()
    while "=" in stripped.split(None, 1)[0] if stripped.split() else False:
        parts = stripped.split(None, 1)
        if len(parts) > 1:
            stripped = parts[1]
        else:
            break
    # Get the first real token
    base = stripped.split(None, 1)[0] if stripped else ""
    # Return just the command name (no path)
    return os.path.basename(base).lower()


def _interpret_exit_code(command: str, exit_code: int) -> str | None:
    """Return a human-readable note for known exit codes."""
    if exit_code == 0:
        return None
    base = _get_base_command(command)
    notes = _EXIT_CODE_NOTES.get(base)
    if notes and exit_code in notes:
        return notes[exit_code]
    return None


def _check_sudo_nopasswd() -> bool:
    """Check if the current user has passwordless sudo."""
    global _SUDO_NOPASSWD_CACHE
    with _SUDO_NOPASSWD_CACHE_LOCK:
        if _SUDO_NOPASSWD_CACHE is not None:
            return _SUDO_NOPASSWD_CACHE
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                capture_output=True,
                timeout=10,
            )
            _SUDO_NOPASSWD_CACHE = result.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            _SUDO_NOPASSWD_CACHE = True  # no sudo at all → skip handling
        return _SUDO_NOPASSWD_CACHE


def _handle_sudo(command: str, env: dict) -> tuple[str, str | None]:
    """
    Rewrite sudo commands for non-interactive password input.
    Returns (modified_command, stdin_password_or_None).
    """
    stripped = command.strip()
    if not stripped.startswith("sudo "):
        return command, None

    # Not on Unix-like? skip.
    if platform.system() == "Windows":
        return command, None

    password = env.get(_SUDO_PASSWORD_ENV, "")
    if password:
        # Pass via stdin with sudo -S
        # Strip the env var so child processes don't see it
        env.pop(_SUDO_PASSWORD_ENV, None)
        rest = stripped[5:]  # remove "sudo "
        return f"sudo -S -p '' {rest}", password + "\n"

    # No password in env — check NOPASSWD
    if _check_sudo_nopasswd():
        return command, None

    # Needs password but none provided
    return command, None


def _truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep head and tail, truncate middle."""
    if len(text) <= max_chars:
        return text, False

    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]

    # Count truncated lines for better messaging
    truncated_text = text[half:-half]
    lines_truncated = truncated_text.count("\n") + 1

    return (
        f"{head}\n... (truncated {lines_truncated} lines) ...\n{tail}",
        True,
    )


def _bg_worker(session_id: str, command: str, cwd: str | None, env, stdin_data: str | None = None):
    """Run a command in background thread and store result."""
    shell_cmd = ["cmd", "/c", command] if platform.system() == "Windows" else ["sh", "-c", command]
    try:
        result = subprocess.run(
            shell_cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=None,
            env=env,
            input=stdin_data,
        )
        with _bg_lock:
            _bg_processes[session_id] = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "done": True,
                "done_at": time.time(),
            }
    except Exception as e:
        with _bg_lock:
            _bg_processes[session_id] = {
                "error": str(e),
                "done": True,
                "done_at": time.time(),
            }


class Tool_CmdExecute(Tool):
    name: str = "cmd_execute"
    description: str = "Execute a shell command and return its output."
    tool_schema: dict = {
        "name": "cmd_execute",
        "description": "Executes a shell command and returns its output. "
                       "Timeout is 60s for foreground commands. "
                       "Use background=True for long-running tasks. "
                       "Pass a session_id (without command) to check on a background task. "
                       "Set env var SUDO_PASSWORD for non-interactive sudo password input.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute. "
                                   "Leave empty when checking background status."
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background and return immediately. "
                                   "Default: False.",
                    "default": False,
                },
                "session_id": {
                    "type": "string",
                    "description": "Check status of a background task by session_id."
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command. "
                                   "Optional, defaults to agent's current directory."
                }
            },
            "required": []
        }
    }

    def _is_safe(self, command):
        cmd_lower = command.strip().lower()
        for blocked in _BLOCKED_COMMANDS:
            if cmd_lower.startswith(blocked) or cmd_lower.startswith(blocked + " "):
                return False, f"Command '{blocked}' is blocked for safety."
        for pat in _BLOCKED_PATTERNS:
            if re.search(pat, cmd_lower):
                return False, "Command matches a blocked dangerous pattern."
        return True, ""

    def execute(self, *args, **kwargs):
        command = kwargs.get("command")
        background = kwargs.get("background", False)
        session_id = kwargs.get("session_id")
        cwd = kwargs.get("cwd")

        # ── if session_id provided: check background status ──
        if session_id:
            with _bg_lock:
                proc = _bg_processes.get(session_id)
            if proc is None:
                return {"error": f"Unknown session_id: {session_id}"}
            if not proc.get("done"):
                return {"status": "running", "session_id": session_id}
            # Clean up completed process
            with _bg_lock:
                _bg_processes.pop(session_id, None)
            result = {k: v for k, v in proc.items() if k != "done"}
            result["session_id"] = session_id
            return result

        # ── validate command ──
        if not command or not isinstance(command, str):
            return {"error": "command is required and must be a non-empty string."}

        # ── safety ──
        safe, reason = self._is_safe(command)
        if not safe:
            return {"error": reason}

        # ── build env (pass through current env) ──
        env = os.environ.copy()
        shell_env = env

        # ── sudo handling ──
        command, stdin_data = _handle_sudo(command, shell_env)
        if stdin_data is None and command.startswith("sudo ") and platform.system() != "Windows":
            if not _check_sudo_nopasswd():
                # Try interactive password input
                if self.interactive_input:
                    password = self.interactive_input("sudo password: ", password=True)
                    if password:
                        shell_env["SUDO_PASSWORD"] = password
                        command, stdin_data = _handle_sudo(command, shell_env)
                    else:
                        return {"error": "sudo password input cancelled."}
                else:
                    return {"error": "sudo requires a password. Set SUDO_PASSWORD env var or "
                                     "run from the TUI for interactive input."}
        shell_cmd = ["cmd", "/c", command] if platform.system() == "Windows" else ["sh", "-c", command]

        # ── background mode ──
        if background:
            global _bg_counter
            with _bg_lock:
                _bg_counter += 1
                sid = f"bg_{_bg_counter:04d}"
                _bg_processes[sid] = {"done": False}

            t = threading.Thread(
                target=_bg_worker,
                args=(sid, command, cwd, shell_env, stdin_data),
                daemon=True,
            )
            t.start()
            return {
                "session_id": sid,
                "pid": "started",
                "message": "Command started in background. "
                           f"Use cmd_execute(session_id='{sid}') to check status.",
            }

        # ── foreground mode ──
        try:
            result = subprocess.run(
                shell_cmd,
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT,
                cwd=cwd,
                env=shell_env,
                input=stdin_data,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {CMD_TIMEOUT}s. "
                             "Try background=True for long-running commands."}
        except OSError as e:
            return {"error": f"Failed to execute command: {e}"}

        output = result.stdout or ""

        # ── truncate ──
        output, truncated = _truncate_output(output, CMD_MAX_OUTPUT)

        # ── interpret exit code ──
        note = _interpret_exit_code(command, result.returncode)

        return {
            "stdout": output.strip(),
            "stderr": (result.stderr or "").strip() or None,
            "exit_code": result.returncode,
            "note": note,
            "truncated": truncated,
        }
