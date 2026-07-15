"""DeepResearch Bench adapter for LINAR.

This script generates raw DeepResearch Bench articles with LINAR's current
deep-research skill and final report contract. It does not run RACE/FACT scoring; use the
benchmark's evaluator separately for GPT-based scoring.

Usage:
    python eval/run_deep_research_bench.py --limit 1
    python eval/run_deep_research_bench.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT_DIR / "agent"
BENCH_DIR = ROOT_DIR / "eval" / "deep_research_bench"
QUERIES_PATH = BENCH_DIR / "data" / "prompt_data" / "query.jsonl"
RAW_DATA_DIR = BENCH_DIR / "data" / "test_data" / "raw_data"
DEFAULT_WORKSPACE_DIR = ROOT_DIR / "eval" / "results" / "deep_research_bench" / "workspaces"
DEFAULT_MODEL_NAME = "linar-step-3.7-flash"
REPORT_CONTAMINATION_MARKERS = (
    "eval/deep_research_bench/data/test_data",
    "eval\\deep_research_bench\\data\\test_data",
    "data/test_data/raw_data",
    "data\\test_data\\raw_data",
    "data/test_data/cleaned_data",
    "data\\test_data\\cleaned_data",
    "reference.jsonl",
    "claude-3-7-sonnet-latest.jsonl",
)
BENCHMARK_TOOLSETS = ["time", "file", "web", "plan", "vision"]
WORKSPACE_PATH_ARGUMENTS = {
    "read_file": ("file_path",),
    "write_file": ("file_path",),
    "delete_file": ("file_path",),
    "delete_dir": ("dir_path",),
    "patch_file": ("file_path",),
    "search_files": ("path",),
}
BLOCKED_BENCHMARK_TOOLS = {"cmd_execute", "create_workspace", "switch_workspace"}
BENCHMARK_DISABLED_HOOKS = (
    "builtin_db_user_persist",
    "builtin_db_agent_persist",
    "builtin_db_tool_persist",
)
ALLOWED_BENCHMARK_MCP_PREFIXES = ("mcp_stepsearch_", "mcp_anysearch_")

sys.path.insert(0, str(AGENT_DIR))


class BenchmarkRunError(RuntimeError):
    """Raised when benchmark output would be invalid."""


@dataclass
class BenchRunResult:
    id: int | str
    prompt: str
    article: str
    ok: bool
    error: str | None = None
    elapsed_seconds: float = 0.0


def default_output_path(model_name: str) -> Path:
    """Return the raw-data path expected by DeepResearch Bench."""
    safe_name = model_name.strip() or "linar"
    return RAW_DATA_DIR / f"{safe_name}.jsonl"


def load_queries(path: Path = QUERIES_PATH) -> list[dict[str, Any]]:
    """Load DeepResearch Bench query rows."""
    queries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def validate_article(article: str, source: str = "article") -> str:
    """Validate one final article before it can enter benchmark raw data."""
    if not article.strip():
        raise BenchmarkRunError(f"{source} is empty")
    normalized = article.lower()
    marker = next((item for item in REPORT_CONTAMINATION_MARKERS if item in normalized), None)
    if marker:
        raise BenchmarkRunError(
            f"{source} failed benchmark contamination check: found {marker!r}"
        )
    return article


def load_report(workspace_root: Path) -> str:
    """Load the exact final report and reject benchmark-answer leakage."""
    report_path = workspace_root / "report.md"
    if not report_path.is_file():
        raise BenchmarkRunError(f"report.md was not generated in {workspace_root}")
    article = report_path.read_text(encoding="utf-8")
    return validate_article(article, source=f"report.md in {workspace_root}")


class WorkspaceBoundTool:
    """Proxy a file tool while constraining every path to one task workspace."""

    def __init__(self, tool: Any, workspace_root: Path, path_arguments: tuple[str, ...]) -> None:
        self._tool = tool
        self._workspace_root = workspace_root.resolve()
        self._path_arguments = path_arguments

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tool, name)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        for argument in self._path_arguments:
            raw_path = kwargs.get(argument)
            if raw_path is None:
                continue
            if not isinstance(raw_path, str):
                return {"error": f"{argument} must be a string."}
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = self._workspace_root / candidate
            resolved = candidate.resolve()
            try:
                resolved.relative_to(self._workspace_root)
            except ValueError:
                return {
                    "error": (
                        "Benchmark workspace isolation denied access outside "
                        f"{self._workspace_root}: {raw_path}"
                    )
                }
        return self._tool.execute(*args, **kwargs)


def build_benchmark_tools(
    workspace_root: Path,
    requested_sets: list[str] | None = None,
) -> dict[str, Any]:
    """Build the non-interactive, workspace-confined toolset used for scoring."""
    from tool_registry import get_tools

    source_sets = BENCHMARK_TOOLSETS if requested_sets is None else requested_sets
    selected_sets = [name for name in source_sets if name in BENCHMARK_TOOLSETS]
    tools = get_tools(selected_sets, include_mcp=True)
    confined: dict[str, Any] = {}
    for name, tool in tools.items():
        if name.startswith("mcp_") and not name.startswith(
            ALLOWED_BENCHMARK_MCP_PREFIXES
        ):
            continue
        if name in BLOCKED_BENCHMARK_TOOLS:
            continue
        path_arguments = WORKSPACE_PATH_ARGUMENTS.get(name)
        confined[name] = (
            WorkspaceBoundTool(tool, workspace_root, path_arguments)
            if path_arguments
            else tool
        )
    return confined


async def run_deep_research(prompt: str, workspace_root: Path) -> None:
    """Run the same deep-research skill and main-agent loop used by LINAR."""
    from agent import Agent
    from skill import activate_skill_for_agent, get_skill, load_skills_from_markdown

    execution_cwd = Path.cwd()
    try:
        os.chdir(AGENT_DIR)
        tools = build_benchmark_tools(workspace_root)
        load_skills_from_markdown(str(ROOT_DIR / "skills"))
        skill = get_skill("deep-research")
        if skill is None:
            raise BenchmarkRunError("The deep-research skill could not be loaded")
        agent = Agent(tools=tools, memory_enabled=False)
        for hook_name in BENCHMARK_DISABLED_HOOKS:
            agent.hooks.unregister(hook_name)
    finally:
        os.chdir(execution_cwd)

    agent._workspace_root = str(workspace_root)
    agent._subagent_tool_factory = (
        lambda requested: build_benchmark_tools(workspace_root, requested)
    )
    agent.emit = lambda _event: None
    activate_skill_for_agent(
        agent,
        skill,
        args=prompt,
        persist=False,
        checkpoint=False,
        emit=False,
    )
    agent._conversation_round = 1
    agent.chat_history.append({"role": "user", "content": prompt, "round": 1})
    try:
        await agent.process_with_llm()
    finally:
        skill.detach_runtime(agent)


ResearchRunner = Callable[[str, Path], Awaitable[None]]
TaskRunner = Callable[[dict[str, Any], Path], Awaitable[BenchRunResult]]


async def run_single(
    query: dict[str, Any],
    workspace_root: Path,
    runner: ResearchRunner | None = None,
) -> BenchRunResult:
    """Run one isolated query and return its exact final report."""
    prompt = str(query["prompt"])
    qid = query["id"]
    start = time.time()

    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    try:
        os.chdir(workspace_root)
        await (runner or run_deep_research)(prompt, workspace_root)
        article = load_report(workspace_root)
        return BenchRunResult(
            id=qid,
            prompt=prompt,
            article=article,
            ok=True,
            elapsed_seconds=time.time() - start,
        )
    except Exception as exc:
        return BenchRunResult(
            id=qid,
            prompt=prompt,
            article="",
            ok=False,
            error=str(exc),
            elapsed_seconds=time.time() - start,
        )
    finally:
        os.chdir(previous_cwd)


def build_worker_command(
    query_id: int | str,
    query_file: Path,
    workspace_root: Path,
    result_path: Path,
    python_executable: Path = Path(sys.executable),
) -> list[str]:
    """Build the isolated worker command for one benchmark query."""
    return [
        str(python_executable),
        "-u",
        str(Path(__file__).resolve()),
        "--query-file",
        str(query_file),
        "--worker-query-id",
        str(query_id),
        "--worker-workspace",
        str(workspace_root),
        "--worker-result",
        str(result_path),
    ]


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Durably replace one JSONL file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            for row in rows:
                temporary_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("row is not a JSON object")
                    rows.append(row)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BenchmarkRunError(f"Could not load checkpoint {path}: {exc}") from exc
    return rows


def failure_output_path(output_path: Path) -> Path:
    """Return the failure ledger stored beside a raw-data JSONL file."""
    return output_path.with_name(f"{output_path.stem}.failures.jsonl")


def load_success_results(output_path: Path) -> list[BenchRunResult]:
    """Load and validate successful rows from an earlier campaign."""
    results: list[BenchRunResult] = []
    seen_ids: set[str] = set()
    for row in _load_jsonl_rows(output_path):
        try:
            qid = row["id"]
            prompt = str(row["prompt"])
            article = validate_article(str(row["article"]), source=f"article for id={qid}")
        except (KeyError, BenchmarkRunError) as exc:
            raise BenchmarkRunError(f"Invalid success checkpoint row in {output_path}: {exc}") from exc
        key = str(qid)
        if key in seen_ids:
            raise BenchmarkRunError(f"Duplicate id={qid} in {output_path}")
        seen_ids.add(key)
        results.append(BenchRunResult(id=qid, prompt=prompt, article=article, ok=True))
    return results


def load_failures(path: Path) -> list[BenchRunResult]:
    """Load failures recorded by an earlier campaign."""
    failures: list[BenchRunResult] = []
    seen_ids: set[str] = set()
    for row in _load_jsonl_rows(path):
        try:
            qid = row["id"]
            prompt = str(row["prompt"])
            error = str(row["error"])
            elapsed = float(row.get("elapsed_seconds", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise BenchmarkRunError(f"Invalid failure checkpoint row in {path}: {exc}") from exc
        key = str(qid)
        if key in seen_ids:
            raise BenchmarkRunError(f"Duplicate id={qid} in {path}")
        seen_ids.add(key)
        failures.append(BenchRunResult(
            id=qid,
            prompt=prompt,
            article="",
            ok=False,
            error=error,
            elapsed_seconds=elapsed,
        ))
    return failures


def write_failures(path: Path, failures: list[BenchRunResult]) -> None:
    """Atomically persist failures, or remove a cleared failure ledger."""
    if not failures:
        path.unlink(missing_ok=True)
        return
    rows = [
        {
            "id": failure.id,
            "prompt": failure.prompt,
            "error": failure.error or "unknown failure",
            "elapsed_seconds": failure.elapsed_seconds,
        }
        for failure in failures
    ]
    _atomic_write_jsonl(path, rows)


def _result_payload(result: BenchRunResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "prompt": result.prompt,
        "article": result.article,
        "ok": result.ok,
        "error": result.error,
        "elapsed_seconds": result.elapsed_seconds,
    }


def _result_from_payload(payload: dict[str, Any]) -> BenchRunResult:
    return BenchRunResult(
        id=payload["id"],
        prompt=str(payload["prompt"]),
        article=str(payload.get("article", "")),
        ok=bool(payload["ok"]),
        error=str(payload["error"]) if payload.get("error") is not None else None,
        elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
    )


async def worker_main(args: argparse.Namespace) -> int:
    """Execute exactly one query inside an isolated worker process."""
    queries = load_queries(Path(args.query_file))
    matches = [
        query for query in queries
        if str(query.get("id")) == str(args.worker_query_id)
    ]
    if len(matches) != 1:
        raise BenchmarkRunError(
            f"Worker expected one query for id={args.worker_query_id}, found {len(matches)}"
        )
    result = await run_single(matches[0], Path(args.worker_workspace))
    _atomic_write_jsonl(Path(args.worker_result), [_result_payload(result)])
    return 0


async def run_task_subprocess(
    query: dict[str, Any],
    workspace_root: Path,
    query_file: Path,
) -> BenchRunResult:
    """Run one task in a child process so cwd, globals and cancellation are isolated."""
    qid = query["id"]
    result_path = workspace_root.parent / f".{workspace_root.name}.worker-result.jsonl"
    result_path.unlink(missing_ok=True)
    command = build_worker_command(
        query_id=qid,
        query_file=query_file,
        workspace_root=workspace_root,
        result_path=result_path,
    )
    workspace_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_log_path = workspace_root.parent / f".{workspace_root.name}.harness.log"
    final_log_path = workspace_root / "harness.log"
    try:
        with temporary_log_path.open("wb") as log_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(ROOT_DIR),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                await process.wait()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            finally:
                log_file.flush()
                os.fsync(log_file.fileno())
    finally:
        if temporary_log_path.exists():
            workspace_root.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_log_path, final_log_path)

    if process.returncode != 0:
        tail = final_log_path.read_text(encoding="utf-8", errors="replace")[-1000:].strip()
        return BenchRunResult(
            id=qid,
            prompt=str(query["prompt"]),
            article="",
            ok=False,
            error=f"worker exited with code {process.returncode}: {tail}",
        )
    rows = _load_jsonl_rows(result_path)
    result_path.unlink(missing_ok=True)
    if len(rows) != 1:
        return BenchRunResult(
            id=qid,
            prompt=str(query["prompt"]),
            article="",
            ok=False,
            error=f"worker produced {len(rows)} result rows instead of 1",
        )
    try:
        return _result_from_payload(rows[0])
    except (KeyError, TypeError, ValueError) as exc:
        return BenchRunResult(
            id=qid,
            prompt=str(query["prompt"]),
            article="",
            ok=False,
            error=f"worker produced an invalid result: {exc}",
        )


def write_results(output_path: Path, results: list[BenchRunResult], strict: bool = True) -> None:
    """Write successful results in DeepResearch Bench raw-data JSONL format."""
    valid_results: list[BenchRunResult] = []
    failures: list[str] = []
    for result in results:
        if not result.ok or result.article.startswith("[Error:"):
            failures.append(f"id={result.id}: {result.error or 'invalid article'}")
            continue
        try:
            validate_article(result.article, source=f"article for id={result.id}")
        except BenchmarkRunError as exc:
            failures.append(str(exc))
        else:
            valid_results.append(result)
    if strict and failures:
        detail = "; ".join(failures)
        raise BenchmarkRunError(f"Refusing to write invalid benchmark raw data: {detail}")

    rows = [
        {"id": r.id, "prompt": r.prompt, "article": r.article}
        for r in valid_results
    ]
    if strict and len(rows) != len(results):
        raise BenchmarkRunError("Some benchmark rows were not successful.")

    _atomic_write_jsonl(output_path, rows)


async def async_main(
    args: argparse.Namespace,
    task_runner: TaskRunner | None = None,
) -> int:
    query_path = Path(args.query_file).resolve()
    queries = load_queries(query_path)
    limit = len(queries) if args.all else min(args.limit, len(queries))
    selected = queries[:limit]

    output_path = Path(args.output) if args.output else default_output_path(args.model_name)
    failure_path = failure_output_path(output_path)
    workspace_dir = Path(args.workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    resume = bool(getattr(args, "resume", True))
    retry_failed = bool(getattr(args, "retry_failed", False))
    strict = bool(getattr(args, "strict", False))
    if resume:
        existing_results = load_success_results(output_path)
        existing_failures = load_failures(failure_path)
    else:
        existing_results = []
        existing_failures = []
        output_path.unlink(missing_ok=True)
        failure_path.unlink(missing_ok=True)

    selected_prompts = {str(query["id"]): str(query["prompt"]) for query in selected}
    for recorded in [*existing_results, *existing_failures]:
        expected_prompt = selected_prompts.get(str(recorded.id))
        if expected_prompt is not None and recorded.prompt != expected_prompt:
            raise BenchmarkRunError(
                f"Checkpoint prompt mismatch for id={recorded.id}: "
                f"expected {expected_prompt!r}, found {recorded.prompt!r}"
            )

    results_by_id = {str(result.id): result for result in existing_results}
    failures_by_id = {str(result.id): result for result in existing_failures}
    pending = [
        query
        for query in selected
        if str(query["id"]) not in results_by_id
        and (retry_failed or str(query["id"]) not in failures_by_id)
    ]

    print(
        f"Running {len(pending)}/{len(selected)} pending queries with LINAR Deep Research "
        f"({len(results_by_id)} successful, {len(failures_by_id)} failed checkpoints)..."
    )
    print(f"Raw output target: {output_path}")
    if not selected:
        print("No queries selected; no raw-data file was written.")
        return 0

    max_workers = int(getattr(args, "max_workers", 1))
    task_timeout = float(getattr(args, "task_timeout", 3600))
    if max_workers < 1:
        raise BenchmarkRunError("--max-workers must be at least 1")
    if task_timeout < 0:
        raise BenchmarkRunError("--task-timeout cannot be negative")

    if task_runner is None:
        async def runner(query: dict[str, Any], workspace_root: Path) -> BenchRunResult:
            return await run_task_subprocess(query, workspace_root, query_path)
    else:
        runner = task_runner

    progress = tqdm(
        total=len(selected),
        initial=len(selected) - len(pending),
        desc="LINAR DRB",
        unit="task",
        dynamic_ncols=True,
        disable=True if bool(getattr(args, "no_progress", False)) else None,
    )

    async def execute_pending(
        idx: int,
        query: dict[str, Any],
    ) -> tuple[int, BenchRunResult]:
        prompt = str(query["prompt"])
        qid = query["id"]
        started = time.time()
        try:
            operation = runner(query, workspace_dir / f"task_{qid}")
            result = (
                await asyncio.wait_for(operation, timeout=task_timeout)
                if task_timeout > 0
                else await operation
            )
        except TimeoutError:
            result = BenchRunResult(
                id=qid,
                prompt=prompt,
                article="",
                ok=False,
                error=f"task timed out after {task_timeout:g} seconds",
                elapsed_seconds=time.time() - started,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = BenchRunResult(
                id=qid,
                prompt=prompt,
                article="",
                ok=False,
                error=f"task runner failed: {exc}",
                elapsed_seconds=time.time() - started,
            )
        if str(result.id) != str(qid) or result.prompt != prompt:
            result = BenchRunResult(
                id=qid,
                prompt=prompt,
                article="",
                ok=False,
                error="task runner returned an id or prompt that did not match its query",
                elapsed_seconds=time.time() - started,
            )
        return idx, result

    pending_iterator = iter(enumerate(pending, start=1))
    active_tasks: set[asyncio.Task[tuple[int, BenchRunResult]]] = set()

    def launch_next() -> bool:
        try:
            idx, query = next(pending_iterator)
        except StopIteration:
            return False
        active_tasks.add(asyncio.create_task(execute_pending(idx, query)))
        return True

    def refresh_progress() -> None:
        progress.set_postfix({
            "ok": sum(1 for query in selected if str(query["id"]) in results_by_id),
            "failed": sum(1 for query in selected if str(query["id"]) in failures_by_id),
            "running": len(active_tasks),
        })

    try:
        for _ in range(min(max_workers, len(pending))):
            launch_next()
        refresh_progress()

        stop_after_failure = False
        while active_tasks and not stop_after_failure:
            completed, still_running = await asyncio.wait(
                active_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            active_tasks = set(still_running)
            for completed_task in completed:
                _idx, result = await completed_task
                key = str(result.id)
                if result.ok:
                    validate_article(result.article, source=f"article for id={result.id}")
                    results_by_id[key] = result
                    failures_by_id.pop(key, None)
                else:
                    failures_by_id[key] = result
                    progress.write(
                        f"FAILED ID={result.id} in {result.elapsed_seconds:.0f}s: {result.error}"
                    )
                if results_by_id:
                    write_results(output_path, list(results_by_id.values()), strict=False)
                write_failures(failure_path, list(failures_by_id.values()))
                progress.update(1)
                if strict and not result.ok:
                    stop_after_failure = True
                    refresh_progress()
                    break
                launch_next()
                refresh_progress()

        if stop_after_failure and active_tasks:
            for task in active_tasks:
                task.cancel()
            await asyncio.gather(*active_tasks, return_exceptions=True)
            active_tasks.clear()
            refresh_progress()
    finally:
        progress.close()

    selected_successes = sum(1 for query in selected if str(query["id"]) in results_by_id)
    selected_failures = sum(1 for query in selected if str(query["id"]) in failures_by_id)
    print(f"\nSaved {selected_successes}/{len(selected)} successful results to {output_path}")
    if selected_failures:
        print(f"Failure ledger: {failure_path} ({selected_failures} tasks)")
    return 0 if selected_failures == 0 or args.allow_partial else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="Number of queries to run")
    parser.add_argument("--all", action="store_true", help="Run all benchmark queries")
    parser.add_argument(
        "--query-file",
        default=str(QUERIES_PATH),
        help="Query JSONL path; useful for an isolated smoke-test case",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="Raw-data filename/model name",
    )
    parser.add_argument("--output", default="", help="Override raw-data JSONL output path")
    parser.add_argument(
        "--workspace-dir",
        default=str(DEFAULT_WORKSPACE_DIR),
        help="Directory for per-task workspaces and research_state.json files",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Write only successful rows instead of failing the run when a task fails",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from valid success and failure checkpoints (default: enabled)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry task IDs already present in the failure ledger",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop scheduling useful work after the first completed failure",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum isolated task subprocesses (default: 1)",
    )
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=3600,
        help="Per-task timeout in seconds; 0 disables it (default: 3600)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the dynamic tqdm campaign progress bar",
    )
    parser.add_argument("--worker-query-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-workspace", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-result", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker_query_id:
        raise SystemExit(asyncio.run(worker_main(args)))
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
