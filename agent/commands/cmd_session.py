"""``/session`` / ``/sessions`` — manage conversation sessions."""

from . import Command

import database as db


class SessionCommand(Command):
    name = "session"
    description = "Show / switch / rename / delete sessions"

    def execute(self, args: str, terminal) -> bool:
        parts = args.strip().split(maxsplit=2)
        sub = parts[0] if parts else ""

        # /session — show current session info
        if not sub:
            info = terminal.agent.get_current_session_info()
            terminal.console.print(
                f"\n  Session #{info['session_id']}"
                f"  |  Turn {info['turn']}"
                f"  |  {info.get('title', 'untitled')[:60]}"
            )
            return True

        # /session <id> — switch to a session
        if sub.isdigit():
            sid = int(sub)
            if terminal.agent.switch_session(sid):
                ns = terminal.s("new_session")
                terminal.console.print(f"\n  [{ns}]Switched to session #{sid}[/{ns}]")
            else:
                e = terminal.s("error")
                terminal.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
            return True

        # /session rename <id> <title>
        if sub == "rename" and len(parts) >= 3:
            sid_str, title = parts[1], parts[2]
            try:
                sid = int(sid_str)
            except ValueError:
                terminal.console.print("\n  Usage: /session rename <id> <title>")
                return True
            sess = db.get_session_by_id(sid)
            if sess:
                db.update_session_title(sid, title)
                terminal.console.print(f'\n  Session #{sid} renamed to "{title}"')
            else:
                e = terminal.s("error")
                terminal.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
            return True

        # /session delete <id>
        if sub == "delete" and len(parts) >= 2:
            try:
                sid = int(parts[1])
            except (ValueError, IndexError):
                terminal.console.print("\n  Usage: /session delete <id>")
                return True
            if sid <= 0:
                terminal.console.print("\n  Usage: /session delete <id>")
                return True
            count = db.get_session_count()
            if count <= 1:
                terminal.console.print("\n  Cannot delete the only session.")
                return True
            sess = db.get_session_by_id(sid)
            if not sess:
                e = terminal.s("error")
                terminal.console.print(f"\n  [{e}]Session #{sid} not found[/{e}]")
                return True
            db.delete_session(sid)
            if sid == terminal.agent.session_id:
                terminal.agent.reset_session()
                ns = terminal.s("new_session")
                terminal.console.print(
                    f"\n  Session #{sid} deleted. "
                    f"[{ns}]Started new session #{terminal.agent.session_id}[/{ns}]"
                )
            else:
                terminal.console.print(f"\n  Session #{sid} deleted.")
            return True

        terminal.console.print(
            "\n  Usage:"
            "\n    /session              Show current session info"
            "\n    /session <id>         Switch to a session"
            "\n    /session rename <id> <title>"
            "\n    /session delete <id>  Delete a session"
        )
        return True


class SessionsCommand(Command):
    """``/sessions`` — list all sessions with interactive picker overlay."""

    name = "sessions"
    description = "List all sessions"

    def execute(self, args: str, terminal) -> bool:
        sessions = db.get_recent_sessions(50)
        if not sessions:
            terminal.console.print("\n  No sessions yet.")
            return True

        terminal.activate_session_picker(sessions)
        return True
