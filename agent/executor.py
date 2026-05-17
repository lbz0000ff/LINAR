"""DAG executor — walk a DAGPlan wave by wave.

A wave is a set of nodes whose dependencies are all satisfied and that
can therefore execute concurrently (in a true multi-agent system).

Usage::

    executor = DAGExecutor(dag, runner=my_runner)
    results = executor.execute_all()
    # results -> {"discover_files": "found 12 files", ...}
    # executor.execution_log -> [{"wave": 0, "node_id": "...", "action": "start"}, ...]
"""

from __future__ import annotations

from plan import DAGNode, DAGNodeStatus, DAGPlan


# ── default runner (injectable for tests) ─────────────────────────────────

def _default_runner(node_id: str, description: str) -> str:
    """Fallback runner — just reports the node was dispatched."""
    return f"[executed] {node_id}: {description}"


# ── executor ──────────────────────────────────────────────────────────────

class DAGExecutor:
    """Walk a DAGPlan wave by wave, dispatching ready nodes to a runner.

    Parameters
    ----------
    dag : DAGPlan
        The task DAG to execute.
    runner : callable, optional
        ``runner(node_id, description) -> str``. Called for each node.
        If omitted a no-op default is used.
    """

    def __init__(self, dag: DAGPlan, runner=None) -> None:
        self.dag = dag
        self.runner = runner or _default_runner
        self.execution_log: list[dict] = []

    # ── public API ──────────────────────────────────────────

    def execute_all(self) -> dict[str, str]:
        """Execute all nodes in dependency order.

        Stops when:
        - All nodes are complete, OR
        - Nodes have failed and no more can be made ready.

        Returns ``{node_id: result_string}`` for every node.
        Failed nodes have their error message as the result;
        blocked nodes (dependents of a failure) have ``"[BLOCKED]"``.
        """
        results: dict[str, str] = {}
        while not self.dag.is_complete:
            # ── termination check: stuck with failures ──────────
            if not self.dag.get_ready():
                # No ready nodes but DAG isn't complete — either blocked
                # nodes exist (still more to process) or we're stuck.
                if not self.dag.get_blocked():
                    break  # nothing will ever become ready — stop
            wave_results = self._execute_wave()
            results.update(wave_results)
        return results

    # ── internal ────────────────────────────────────────────

    def _execute_wave(self) -> dict[str, str]:
        """Execute all currently-ready nodes as one wave.

        If no nodes are ready, checks for failure-induced blocking
        and marks dependent nodes as BLOCKED.

        Returns ``{node_id: result}`` for the nodes processed in this wave.
        """
        ready = self.dag.get_ready()

        # ── no ready nodes → propagate failures as BLOCKED ──
        if not ready:
            if self.dag.is_complete:
                return {}
            blocked = self.dag.get_blocked()
            if blocked:
                return self._mark_blocked(blocked)
            # Should not reach here if execute_all's termination check works,
            # but guard against truly unexpected states.
            failed = [n.id for n in self.dag.nodes.values()
                      if n.status == DAGNodeStatus.FAILED]
            raise RuntimeError(
                f"DAG is stuck: no ready/blocked nodes, {len(failed)} failed, "
                f"not complete"
            )

        wave = self._next_wave_num()
        results: dict[str, str] = {}

        for node in ready:
            node.status = DAGNodeStatus.IN_PROGRESS
            self.execution_log.append({
                "wave": wave,
                "node_id": node.id,
                "action": "start",
                "description": node.description,
            })

            try:
                result = self.runner(node.id, node.description)
                node.status = DAGNodeStatus.COMPLETED
                node.result = str(result)
                self.execution_log.append({
                    "wave": wave,
                    "node_id": node.id,
                    "action": "complete",
                })
                results[node.id] = str(result)
            except Exception as exc:
                node.status = DAGNodeStatus.FAILED
                node.result = str(exc)
                self.execution_log.append({
                    "wave": wave,
                    "node_id": node.id,
                    "action": "failed",
                    "error": str(exc),
                })
                results[node.id] = str(exc)

        return results

    # ── helpers ─────────────────────────────────────────────

    def _mark_blocked(self, nodes: list[DAGNode]) -> dict[str, str]:
        """Mark each node in *nodes* as BLOCKED and log the event."""
        wave = self._next_wave_num()
        for node in nodes:
            node.status = DAGNodeStatus.BLOCKED
            self.execution_log.append({
                "wave": wave,
                "node_id": node.id,
                "action": "blocked",
                "description": node.description,
            })
        return {n.id: "[BLOCKED]" for n in nodes}

    def _next_wave_num(self) -> int:
        if not self.execution_log:
            return 0
        return max(e["wave"] for e in self.execution_log) + 1
