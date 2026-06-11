"""DAG executor — walk a DAGPlan wave by wave, executing ready nodes in parallel.

Usage::

    executor = DAGExecutor(dag, runner=my_runner)
    results = executor.execute_all()
    # results -> {"discover_files": "found 12 files", ...}

    # Async version:
    results = await executor.execute_all_async(async_runner)
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, wait

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
    interrupt_check : callable, optional
        ``interrupt_check() -> bool``. Called between waves; if it returns
        True, execution stops early.  Remaining PENDING nodes are marked FAILED.
    """

    def __init__(self, dag: DAGPlan, runner=None, interrupt_check=None) -> None:
        self.dag = dag
        self.runner = runner or _default_runner
        self.interrupt_check = interrupt_check
        self.execution_log: list[dict] = []
        self.interrupted: bool = False

    # ── public API ──────────────────────────────────────────

    def execute_all(self) -> dict[str, str]:
        """Execute all nodes in dependency order.

        Stops when:
        - All nodes are complete, OR
        - Nodes have failed and no more can be made ready, OR
        - ``interrupt_check()`` returns True (if set).

        Returns ``{node_id: result_string}`` for every node.
        Failed nodes have their error message as the result;
        blocked nodes (dependents of a failure) have ``"[BLOCKED]"``.
        """
        results: dict[str, str] = {}
        while not self.dag.is_complete:
            # ── check interrupt between waves ──
            if self.interrupt_check and self.interrupt_check():
                self.interrupted = True
                break

            # ── termination check: stuck with failures ──────────
            if not self.dag.get_ready():
                # No ready nodes but DAG isn't complete — either blocked
                # nodes exist (still more to process) or we're stuck.
                if not self.dag.get_blocked():
                    break  # nothing will ever become ready — stop
            wave_results = self._execute_wave()
            results.update(wave_results)

        if self.interrupted:
            for node in self.dag.nodes.values():
                if node.status == DAGNodeStatus.PENDING:
                    node.status = DAGNodeStatus.FAILED
                    node.result = "[INTERRUPTED]"
        return results

    async def execute_all_async(self, async_runner) -> dict[str, str]:
        """Async version — runs each wave with ``asyncio.gather``."""
        results: dict[str, str] = {}
        while not self.dag.is_complete:
            if self.interrupt_check and self.interrupt_check():
                self.interrupted = True
                break
            if not self.dag.get_ready():
                if not self.dag.get_blocked():
                    break
            wave_results = await self._execute_wave_async(async_runner)
            results.update(wave_results)
        if self.interrupted:
            for node in self.dag.nodes.values():
                if node.status == DAGNodeStatus.PENDING:
                    node.status = DAGNodeStatus.FAILED
                    node.result = "[INTERRUPTED]"
        return results

    async def _execute_wave_async(self, async_runner) -> dict[str, str]:
        ready = self.dag.get_ready()
        if not ready:
            if self.dag.is_complete:
                return {}
            blocked = self.dag.get_blocked()
            if blocked:
                return self._mark_blocked(blocked)
            failed = [n.id for n in self.dag.nodes.values()
                      if n.status == DAGNodeStatus.FAILED]
            raise RuntimeError(
                f"DAG stuck: no ready/blocked, {len(failed)} failed"
            )

        wave = self._next_wave_num()
        results: dict[str, str] = {}

        async def _run(node: DAGNode) -> None:
            node.status = DAGNodeStatus.IN_PROGRESS
            self.execution_log.append({
                "wave": wave, "node_id": node.id,
                "action": "start", "description": node.description,
            })
            try:
                result = await async_runner(node.id, node.description)
                node.status = DAGNodeStatus.COMPLETED
                node.result = str(result)
                self.execution_log.append({
                    "wave": wave, "node_id": node.id, "action": "complete",
                })
                results[node.id] = str(result)
            except Exception as exc:
                node.status = DAGNodeStatus.FAILED
                node.result = str(exc)
                self.execution_log.append({
                    "wave": wave, "node_id": node.id,
                    "action": "failed", "error": str(exc),
                })
                results[node.id] = str(exc)

        tasks = [_run(node) for node in ready]
        await asyncio.gather(*tasks)
        return results

    # ── internal ────────────────────────────────────────────

    def _execute_wave(self) -> dict[str, str]:
        """Execute all currently-ready nodes as one wave, in parallel.

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
        lock = threading.Lock()

        def _run(node: DAGNode) -> None:
            """Execute one node and record its result (thread-safe)."""
            with lock:
                node.status = DAGNodeStatus.IN_PROGRESS
                self.execution_log.append({
                    "wave": wave,
                    "node_id": node.id,
                    "action": "start",
                    "description": node.description,
                })

            try:
                result = self.runner(node.id, node.description)
                with lock:
                    node.status = DAGNodeStatus.COMPLETED
                    node.result = str(result)
                    self.execution_log.append({
                        "wave": wave,
                        "node_id": node.id,
                        "action": "complete",
                    })
                    results[node.id] = str(result)
            except Exception as exc:
                with lock:
                    node.status = DAGNodeStatus.FAILED
                    node.result = str(exc)
                    self.execution_log.append({
                        "wave": wave,
                        "node_id": node.id,
                        "action": "failed",
                        "error": str(exc),
                    })
                    results[node.id] = str(exc)

        # ── execute ready nodes in parallel (interruptible) ──
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            futures = {pool.submit(_run, node): node for node in ready}
            done = set()
            while len(done) < len(futures):
                if self.interrupt_check and self.interrupt_check():
                    for f in futures:
                        f.cancel()
                    break
                pending = set(futures.keys()) - done
                if not pending:
                    break
                newly_done, _ = wait(pending, timeout=0.3)
                if newly_done:
                    for f in newly_done:
                        done.add(f)

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
