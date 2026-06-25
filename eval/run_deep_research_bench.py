"""DeepResearch Bench adapter — runs EchoLily deep research on 100 queries.

Usage:
    python eval/run_deep_research_bench.py --limit 5
    python eval/run_deep_research_bench.py --all
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

BENCH_DIR = os.path.join(os.path.dirname(__file__), "deep_research_bench")
QUERIES_PATH = os.path.join(BENCH_DIR, "data", "prompt_data", "query.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results", "deep_research_bench")


async def run_single(prompt: str, max_turns: int = 8) -> str:
    """Run one research query and return a formatted report."""
    from tool_registry import get_tools
    from agent import Agent
    from tool.basic_tools.tool_plan import Tool_CreatePlan
    from plan import DAGPlan, DAGNode

    agent = Agent(tools=get_tools(["web", "file"], include_mcp=False), memory_enabled=False)
    tool = Tool_CreatePlan()
    tool.agent_ref = agent

    # Step 1: DAG research — collect web results
    raw = await tool.execute(
        goal=prompt,
        sub_tasks=[{
            "id": "research",
            "description": f"Search the web for: {prompt}. Collect information from multiple sources.",
            "agent_hint": "research",
            "depends_on": [],
        }],
    )
    search_data = str(raw)

    # Step 2: Generate a structured research report
    from config import load_config
    from openai import AsyncOpenAI
    cfg = load_config()
    aux = cfg.get("aux") or cfg.get("llm", {})
    client = AsyncOpenAI(base_url=aux.get("base_url", ""), api_key=aux.get("api_key", ""))
    resp = await client.chat.completions.create(
        model=aux.get("model", "deepseek-v4-flash"),
        messages=[
            {"role": "system", "content": "You are a professional research analyst. Write a comprehensive, well-structured research report in Markdown format."},
            {"role": "user", "content": (
                f"# Research Topic\n{prompt}\n\n"
                f"## Source Material\n{search_data[:6000]}\n\n"
                f"## Requirements\n"
                f"1. **Structure**: Include all of: Executive Summary, Introduction, Main Analysis "
                f"(with 3-5 subsections covering different angles), Discussion, Conclusion, References\n"
                f"2. **Depth**: Provide specific data, statistics, and factual details from the sources\n"
                f"3. **Balance**: Cover multiple perspectives and contradictory evidence where applicable\n"
                f"4. **Citations**: Use [Source: URL] markers throughout the text\n"
                f"5. **Format**: Professional Markdown with section headers (##), bullet points, and tables where appropriate\n"
                f"6. **Length**: 1500-3000 words"
            )},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    return resp.choices[0].message.content.strip()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="Number of queries to run")
    parser.add_argument("--all", action="store_true", help="Run all 100 queries")
    args = parser.parse_args()

    # Load queries
    queries = []
    with open(QUERIES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))

    limit = len(queries) if args.all else min(args.limit, len(queries))
    print(f"Running {limit} queries...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = []

    for i, q in enumerate(queries[:limit]):
        qid = q["id"]
        prompt = q["prompt"]
        lang = q.get("language", "zh")
        print(f"\n[{i+1}/{limit}] ID={qid} [{lang}] {prompt[:60]}...")

        start = time.time()
        try:
            article = await run_single(prompt)
        except Exception as e:
            article = f"[Error: {e}]"
            print(f"  ERROR: {e}")

        elapsed = time.time() - start
        results.append({"id": qid, "prompt": prompt, "article": article})
        print(f"  Done in {elapsed:.0f}s ({len(article)} chars)")

    # Save output
    out_path = os.path.join(OUTPUT_DIR, "echolily_results.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(results)} results to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
