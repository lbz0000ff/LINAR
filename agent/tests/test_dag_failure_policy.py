import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from executor import DAGExecutor
from plan import DAGNode, DAGNodeStatus, DAGPlan


def test_blocked_status_propagates_through_strict_chain_and_tolerant_node_recovers():
    plan = DAGPlan(goal="recover after failure")
    plan.add_node(DAGNode(id="source", description="fail"))
    plan.add_node(DAGNode(
        id="strict_middle", description="strict", depends_on=["source"],
    ))
    plan.add_node(DAGNode(
        id="strict_tail", description="strict tail", depends_on=["strict_middle"],
    ))
    plan.add_node(DAGNode(
        id="recovery",
        description="recover",
        depends_on=["strict_tail"],
        dependency_policy="all_terminal",
    ))

    async def runner(node_id, _description):
        if node_id == "source":
            raise RuntimeError("source failed")
        return f"ran {node_id}"

    results = asyncio.run(DAGExecutor(plan).execute_all_async(runner))

    assert plan.nodes["source"].status == DAGNodeStatus.FAILED
    assert plan.nodes["strict_middle"].status == DAGNodeStatus.BLOCKED
    assert plan.nodes["strict_tail"].status == DAGNodeStatus.BLOCKED
    assert plan.nodes["recovery"].status == DAGNodeStatus.COMPLETED
    assert results["recovery"] == "ran recovery"
