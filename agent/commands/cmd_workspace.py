"""``/workspace`` family — manage workspace directories."""

import os

from . import Command
import database as db


class WorkspaceCommand(Command):
    """``/workspace`` — show current workspace info."""

    name = "workspace"
    description = "Show current workspace path"

    def execute(self, args: str, terminal) -> bool:
        ws = getattr(terminal.agent, '_workspace_root', None)
        if ws:
            h = terminal.s("header") or "bold"
            terminal.console.print(f"\n  [{h}]Current workspace:[/{h}] {ws}")
            # Show files in workspace
            try:
                files = os.listdir(ws)
                if files:
                    terminal.console.print(f"  [{h}]Files:[/{h}]")
                    for f in files[:20]:
                        terminal.console.print(f"    {f}")
                    if len(files) > 20:
                        terminal.console.print(f"    ... and {len(files) - 20} more")
            except OSError:
                terminal.console.print("  (unable to list workspace files)")
        else:
            terminal.console.print("\n  No active workspace. Use /workspace-create to create one.")
        return True


class CreateWorkspaceCommand(Command):
    """``/workspace-create [name]`` — create a new workspace."""

    name = "workspace-create"
    description = "Create a workspace: /workspace-create [name]"

    def execute(self, args: str, terminal) -> bool:
        agent = terminal.agent
        ws_name = args.strip() or "default"
        sid = agent.session_id
        if not sid:
            terminal.console.print("\n  Error: no active session.")
            return True

        ws_dir = os.path.abspath(os.path.join("workspace", f"session_{sid}", ws_name))
        os.makedirs(ws_dir, exist_ok=True)

        agent._workspace_root = ws_dir
        os.chdir(ws_dir)
        db.update_session_workspace(sid, ws_dir)

        h = terminal.s("header") or "bold"
        terminal.console.print(f"\n  [{h}]Workspace created:[/{h}] {ws_dir}")
        return True


class SwitchWorkspaceCommand(Command):
    """``/workspace-switch <path>`` — switch to an existing workspace."""

    name = "workspace-switch"
    description = "Switch workspace: /workspace-switch <path>"

    def execute(self, args: str, terminal) -> bool:
        path = args.strip()
        if not path:
            terminal.console.print("\n  Usage: /workspace-switch <path>")
            return True

        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            terminal.console.print(f"\n  Error: directory not found: {abs_path}")
            return True

        agent = terminal.agent
        agent._workspace_root = abs_path
        os.chdir(abs_path)

        sid = agent.session_id
        if sid:
            db.update_session_workspace(sid, abs_path)

        h = terminal.s("header") or "bold"
        terminal.console.print(f"\n  [{h}]Switched to workspace:[/{h}] {abs_path}")
        return True
