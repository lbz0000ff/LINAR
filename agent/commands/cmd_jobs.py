"""``/list_jobs`` — list all promises (background watch tasks)."""

import time
from . import Command


class ListJobsCommand(Command):
    name = "list_jobs"
    aliases = ["jobs", "list_job"]
    description = "List all background watch tasks (promises)"

    def execute(self, args: str, terminal) -> bool:
        agent = terminal.agent
        if not agent._promises:
            terminal.console.print("\n  No background jobs registered.")
            return True

        # Table header
        terminal.console.print("\n  ┌─────────────┬──────────┬──────────┬────────────────────────────────┬──────────┐")
        terminal.console.print("  │ Job ID      │ Type     │ Elapsed  │ End condition                 │ Status   │")
        terminal.console.print("  ├─────────────┼──────────┼──────────┼────────────────────────────────┼──────────┤")

        now = time.time()
        for pid in sorted(agent._promises.keys()):
            info = agent._promises[pid]
            meta = info.get("meta", {})
            status = info["status"]
            check_type = meta.get("check_type", "?")
            job_id = meta.get("job_id", "")
            start = meta.get("start_time", now)
            elapsed = now - start

            # Format elapsed time
            if elapsed < 60:
                elapsed_str = f"00:{int(elapsed):02d}s"
            elif elapsed < 3600:
                m, s = divmod(int(elapsed), 60)
                elapsed_str = f"{m:02d}:{s:02d}m"
            else:
                h, r = divmod(int(elapsed), 3600)
                m, s = divmod(int(r), 60)
                elapsed_str = f"{h:02d}:{m:02d}:{s:02d}"

            # End condition display
            end_cond = f"{check_type}: {job_id[:30]}" if job_id else check_type

            # Status emoji
            status_map = {
                "pending": "⏳",
                "resolved": "✓",
                "cancelled": "✗",
                "failed": "💀",
            }
            icon = status_map.get(status, "?")
            status_str = f"{icon} {status}"

            terminal.console.print(
                f"  │ {pid:<11s} │ {check_type:<8s} │ {elapsed_str:<8s} │ {end_cond:<30s} │ {status_str:<8s} │"
            )

        terminal.console.print("  └─────────────┴──────────┴──────────┴────────────────────────────────┴──────────┘")
        return True
