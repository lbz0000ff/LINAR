"""Deep research evaluation runner.

Usage::

    from eval.runner import ResearchEvalRunner
    from eval.gaia import GAIA

    runner = ResearchEvalRunner(benchmark=GAIA(levels=["1"], max_tasks=5))
    results = await runner.run()
    print(runner.metrics.report())
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from dataclasses import asdict

from .benchmark import Benchmark, EvalTask, EvalResult
from .metrics import ResearchMetrics, extract_node_count


class ResearchEvalRunner:
    """Run a benchmark against EchoLily's deep research system.

    For each task, constructs a ``create_plan`` call with a single
    research sub-task and collects results + metrics.
    """

    def __init__(self, benchmark: Benchmark, agent=None, max_concurrency: int = 2):
        self.benchmark = benchmark
        self._agent = agent
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.metrics = ResearchMetrics()
        self.results: list[EvalResult] = []

    async def run(self) -> list[EvalResult]:
        """Run all tasks and return results."""
        tasks = await self.benchmark.load()
        if not tasks:
            print("No tasks loaded — check benchmark configuration.")
            return []

        print(f"\nRunning {len(tasks)} tasks from {self.benchmark.name}...")
        self.metrics.total_tasks = len(tasks)

        async def _evaluate(task: EvalTask) -> EvalResult:
            async with self._semaphore:
                return await self._run_single(task)

        coros = [_evaluate(t) for t in tasks]
        self.results = await asyncio.gather(*coros)

        # Aggregate metrics
        for r in self.results:
            if r.passed:
                self.metrics.passed += 1
            else:
                self.metrics.failed += 1
            self.metrics.total_tokens += r.token_cost
            self.metrics.total_time_seconds += r.time_seconds
            self.metrics.total_nodes += r.node_count
            if r.error:
                self.metrics.errors.append(r.error)

        print(f"\n{self.metrics.report()}")
        self._save_results()
        return self.results

    def _save_results(self) -> None:
        """Save evaluation results to eval/results/ as JSON."""
        results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(results_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(results_dir, f"{self.benchmark.name}_{ts}.json")
        report = {
            "timestamp": ts,
            "benchmark": self.benchmark.name,
            "metrics": asdict(self.metrics),
            "results": [asdict(r) for r in self.results],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Results saved: {path}")

    async def _run_single(self, task: EvalTask) -> EvalResult:
        """Execute a single evaluation task.

        Creates a deep research plan with ``create_plan`` and returns
        the result.  Tracks token usage, timing, and DAG node count.
        """
        from tool.basic_tools.tool_plan import Tool_CreatePlan
        from plan import DAGPlan, DAGNode
        from executor import DAGExecutor
        from agent_factory import create_agent

        agent = self._agent
        start = time.time()
        token_estimate = 0
        dag_summary = ""
        error_msg = None

        try:
            # Build a simple single-wave plan
            plan = DAGPlan(goal=task.question)
            plan.add_node(DAGNode(
                id="research",
                description=f"Research: {task.question}. Search the web and find the answer.",
                agent_hint="research",
                depends_on=[],
            ))
            agent.emit({"type": "plan_start"})
            agent.emit({"type": "plan_execute", "data": plan.format_for_prompt()})

            agent_results: dict[str, str] = {}

            async def _run_node(node_id: str, description: str) -> str:
                sub = create_agent(
                    agent_hint="research",
                    stop_event=agent.stop_event,
                    workspace_root=getattr(agent, "_workspace_root", None),
                )
                agent.emit({"type": "dag_node_start", "data": {"id": node_id, "description": description}})
                # Give the sub-agent enough turns to search AND provide an answer
                sub.max_llm_calls = 10
                # Put task + answer format in USER message (survives _build_prompt() rebuild)
                user_msg = (
                    f"Question: {description}\n\n"
                    "1. Search the web to find the answer (max 2-3 searches)\n"
                    "2. After you have enough information, output the final answer\n"
                    "3. End with: FINAL_ANSWER: <value>\n\n"
                    "Example: If the answer is 42, your final response should end with: FINAL_ANSWER: 42"
                )
                await sub.add_user_message(user_msg)
                await sub.process_with_llm()
                # Collect ALL sub-agent output: tool results + agent text responses
                output_parts = []
                for m in sub.chat_history:
                    if m.get("role") == "agent" and m.get("content"):
                        output_parts.append(m["content"])
                    elif m.get("role") == "tool":
                        r = m.get("result", "")
                        if isinstance(r, dict):
                            r = json.dumps(r, ensure_ascii=False)
                        r = str(r).strip()
                        if r:
                            output_parts.append(r[:500])
                full_output = "\n\n".join(output_parts) if output_parts else "[no output]"
                result = full_output[:500]
                agent.emit({"type": "dag_node_complete", "data": {"id": node_id, "result": result[:200]}})
                agent_results[node_id] = result
                return result

            executor = DAGExecutor(plan, interrupt_check=lambda: agent.stop_event.is_set())
            try:
                all_results = await executor.execute_all_async(_run_node)
            except Exception as exc:
                return EvalResult(
                    task_id=task.task_id, question=task.question,
                    expected_answer=task.expected_answer, actual_answer="",
                    passed=False, error=f"DAG failed: {exc}",
                )

            # Combine results
            parts = []
            for nid in (list(plan.nodes.keys()) if not plan.is_complete else list(plan.nodes.keys())):
                node = plan.nodes[nid]
                result = all_results.get(nid, "")
                parts.append(f"[{node.status.value}] {result[:300]}")
            dag_summary = "\n\n".join(parts)

            # Token estimate (rough: each tool call ≈ 500 tokens)
            token_estimate = len(dag_summary) // 4 * 2  # very rough

        except Exception as exc:
            error_msg = str(exc)
            dag_summary = ""

        elapsed = time.time() - start
        actual_answer = dag_summary[:1000]
        passed = await self.benchmark.judge(task, actual_answer)

        return EvalResult(
            task_id=task.task_id, question=task.question,
            expected_answer=task.expected_answer, actual_answer=actual_answer,
            passed=passed, score=1.0 if passed else 0.0,
            token_cost=token_estimate,
            time_seconds=elapsed,
            node_count=extract_node_count(dag_summary),
            error=error_msg,
            details={"dag_summary_len": len(dag_summary)},
        )
