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
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def async_main(args: argparse.Namespace) -> int:
    queries = load_queries(Path(args.query_file))
    limit = len(queries) if args.all else min(args.limit, len(queries))
    selected = queries[:limit]

    output_path = Path(args.output) if args.output else default_output_path(args.model_name)
    workspace_dir = Path(args.workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(selected)} queries with LINAR Deep Research...")
    print(f"Raw output target: {output_path}")
    if not selected:
        print("No queries selected; no raw-data file was written.")
        return 0

    results: list[BenchRunResult] = []
    for idx, query in enumerate(selected, start=1):
        prompt = str(query["prompt"])
        qid = query["id"]
        print(f"\n[{idx}/{len(selected)}] ID={qid} {prompt[:80]}...")
        result = await run_single(
            query,
            workspace_root=workspace_dir / f"task_{qid}",
        )
        results.append(result)
        if result.ok:
            print(f"  OK in {result.elapsed_seconds:.0f}s ({len(result.article)} chars)")
        else:
            print(f"  FAILED in {result.elapsed_seconds:.0f}s: {result.error}")

    try:
        write_results(output_path, results, strict=not args.allow_partial)
    except BenchmarkRunError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        if args.allow_partial:
            return 0
        return 1

    ok_count = sum(1 for r in results if r.ok)
    print(f"\nSaved {ok_count}/{len(results)} successful results to {output_path}")
    return 0 if ok_count == len(results) or args.allow_partial else 1


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
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(async_main(parse_args())))


if __name__ == "__main__":
    main()
