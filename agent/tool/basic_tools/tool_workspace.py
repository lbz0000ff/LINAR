"""Workspace management tools — create and switch working directories."""

from __future__ import annotations

import os
from typing import Any

from .tool import Tool
import database as db


class Tool_CreateWorkspace(Tool):
    name: str = "create_workspace"
    description: str = (
        "Create a workspace directory for organizing research outputs, "
        "intermediate files, and session artifacts. "
        "After creation, all file operations default to this directory. "
        "PREFER using the 'path' parameter to specify exactly where the workspace "
        "should be created (e.g., 'path=workspaces/VLA'). "
        "Only use the 'name' parameter without 'path' for quick temporary workspaces."
    )
    tool_schema: dict = {
        "name": "create_workspace",
        "description": "Create a workspace directory. Use 'path' for a specific location, "
                       "or 'name' for an auto-named workspace under the default directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "RECOMMENDED. Full path where the workspace should be created (e.g., 'workspaces/VLA'). Creates directory if needed. Use this when you want the workspace in a specific location.",
                    "default": "",
                },
                "name": {
                    "type": "string",
                    "description": "Only used when 'path' is empty. Creates an auto-named workspace under workspace/session_{id}/<name>. Best for quick temporary workspaces.",
                    "default": "",
                }
            },
            "required": [],
        },
    }

    agent_ref: Any = None

    def execute(self, path: str = "", name: str = "") -> str:
        agent = self.agent_ref
        if agent is None:
            return "Error: no agent reference."

        sid = agent.session_id
        if not sid:
            return "Error: no active session."

        if path.strip():
            ws_dir = os.path.abspath(path.strip())
        else:
            ws_name = name.strip() or "default"
            ws_dir = os.path.abspath(os.path.join("workspace", f"session_{sid}", ws_name))
        os.makedirs(ws_dir, exist_ok=True)

        agent._workspace_root = ws_dir
        os.chdir(ws_dir)

        db.update_session_workspace(sid, ws_dir)

        # Notify UI
        agent.emit({"type": "workspace_updated", "data": {"path": ws_dir}})

        return f"✅ Workspace created and active: {ws_dir}"


class Tool_SwitchWorkspace(Tool):
    name: str = "switch_workspace"
    description: str = (
        "Switch the current working directory to an existing workspace path. "
        "Use this to resume work in a previously created workspace."
    )
    tool_schema: dict = {
        "name": "switch_workspace",
        "description": "Switch to an existing workspace directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the workspace directory.",
                }
            },
            "required": ["path"],
        },
    }

    agent_ref: Any = None

    def execute(self, path: str = "") -> str:
        if not path.strip():
            return "Error: path is required."

        abs_path = os.path.abspath(path.strip())
        if not os.path.isdir(abs_path):
            return f"Error: directory not found: {abs_path}"

        agent = self.agent_ref
        if agent is None:
            return "Error: no agent reference."

        agent._workspace_root = abs_path
        os.chdir(abs_path)

        sid = agent.session_id
        if sid:
            db.update_session_workspace(sid, abs_path)
            agent.emit({"type": "workspace_updated", "data": {"path": abs_path}})

        return f"✅ Switched to workspace: {abs_path}"
