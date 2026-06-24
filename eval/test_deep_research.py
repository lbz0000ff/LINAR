"""pytest integration for deep research evaluation.

Quick smoke test using a small set of sample questions.
For full GAIA evaluation, configure HuggingFace auth and run::

    HF_TOKEN=xxx pytest eval/test_deep_research.py -k gaia --no-header
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import pytest


@pytest.mark.anyio
async def test_smoke_single_question():
    """Smoke test: answer one simple research question via create_plan."""
    from tool.basic_tools.tool_plan import Tool_CreatePlan
    from plan import DAGPlan, DAGNode
    from executor import DAGExecutor
    from agent_factory import create_agent, run_task as run_agent_task
    from tool_registry import get_tools
    from agent import Agent

    agent = Agent(tools=get_tools(["web", "file"], include_mcp=False), memory_enabled=False)
    tool = Tool_CreatePlan()
    tool.agent_ref = agent

    result = await tool.execute(
        goal="What is the capital of France?",
        sub_tasks=[{
            "id": "q1", "description": "Search for the capital of France using web_search.",
            "agent_hint": "research", "depends_on": [],
        }],
    )

    assert result is not None
    assert "Paris" in result or "paris" in result, f"Expected Paris in result: {result[:200]}"
    print(f"Smoke test PASSED: {result[:100]}")


@pytest.mark.anyio
async def test_dag_execution_basic():
    """Test that a minimal 2-node DAG executes and returns results."""
    from tool.basic_tools.tool_plan import Tool_CreatePlan
    from tool_registry import get_tools
    from agent import Agent

    agent = Agent(tools=get_tools(["web", "file"], include_mcp=False), memory_enabled=False)
    tool = Tool_CreatePlan()
    tool.agent_ref = agent

    result = await tool.execute(
        goal="Research Python and JavaScript popularity",
        sub_tasks=[
            {"id": "py", "description": "Search for Python usage statistics 2025", "agent_hint": "research", "depends_on": []},
            {"id": "js", "description": "Search for JavaScript usage statistics 2025", "agent_hint": "research", "depends_on": []},
        ],
    )

    assert result is not None
    assert "COMPLETED" in result or "completed" in result
    print(f"DAG test PASSED: {len(result)} chars of results")


@pytest.mark.anyio
async def test_gaia_level_1():
    """Run GAIA Level 1 validation set (requires HuggingFace auth)."""
    import os
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not hf_token:
        pytest.skip("HF_TOKEN not set — skipping GAIA test")
    try:
        from huggingface_hub import whoami
        whoami(token=hf_token)
    except Exception:
        pytest.skip("HuggingFace auth failed — run `huggingface-cli login`")
    from eval.gaia import GAIA
    from eval.runner import ResearchEvalRunner
    from tool_registry import get_tools
    from agent import Agent

    agent = Agent(tools=get_tools(["web", "file"], include_mcp=False), memory_enabled=False)
    benchmark = GAIA(levels=["1"], max_tasks=3)
    runner = ResearchEvalRunner(benchmark, agent=agent, max_concurrency=1)
    results = await runner.run()

    assert runner.metrics.total_tasks > 0
    print(runner.metrics.report())
