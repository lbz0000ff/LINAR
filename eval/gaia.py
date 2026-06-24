"""GAIA benchmark dataset loader.

Requires HuggingFace authentication (``huggingface-cli login``) to access
the gated dataset at https://huggingface.co/datasets/gaia-benchmark/GAIA.
"""

from __future__ import annotations

from .benchmark import Benchmark, EvalTask


class GAIA(Benchmark):
    """GAIA benchmark — multi-step reasoning with tool use.

    Levels: 1 (easy) → 3 (hard).  Questions require web search,
    multi-step reasoning, and tool use to answer.
    """

    name = "GAIA"
    description = "General AI Assistants benchmark — multi-step reasoning + tool use"

    def __init__(self, levels: list[str] | None = None, split: str = "validation", max_tasks: int | None = None):
        self._levels = levels or ["1", "2", "3"]
        self._split = split
        self._max_tasks = max_tasks

    async def load(self) -> list[EvalTask]:
        """Load GAIA tasks from HuggingFace datasets."""
        try:
            from datasets import load_dataset
        except ImportError:
            raise RuntimeError("Install datasets: pip install datasets")

        tasks: list[EvalTask] = []
        for level in self._levels:
            ds_name = f"2023_level{level}"
            try:
                ds = load_dataset("gaia-benchmark/GAIA", ds_name, split=self._split, streaming=True)
            except Exception as e:
                print(f"  GAIA level {level}: skip ({e})")
                continue

            for i, example in enumerate(ds):
                if self._max_tasks and len(tasks) >= self._max_tasks:
                    break
                tasks.append(EvalTask(
                    task_id=f"GAIA-{level}-{i:04d}",
                    question=example["Question"],
                    expected_answer=example["Final answer"],
                    level=level,
                    metadata={"file_name": example.get("file_name", "")},
                ))
            print(f"  GAIA level {level}: {len([t for t in tasks if t.level == level])} tasks")
        return tasks

    async def judge(self, task: EvalTask, actual: str) -> bool:
        """Judge using LLM-as-Judge for better semantic matching."""
        if not actual:
            return False
        # Extract FINAL_ANSWER if present (agent should output this format)
        import re
        m = re.search(r"FINAL_ANSWER:\s*(\S+)", actual)
        final = m.group(1) if m else actual
        # For exact/contained answers, do substring match first
        expected = task.expected_answer.strip()
        if expected.lower() in final.lower():
            return True
        # Fall back to LLM-as-Judge for semantic equivalence
        return await self._llm_judge(task.question, expected, actual)

    @staticmethod
    async def _llm_judge(question: str, expected: str, actual: str) -> bool:
        """Use a small LLM to judge answer equivalence."""
        try:
            from openai import AsyncOpenAI
            from config import load_config
            cfg = load_config()
            aux = cfg.get("aux") or cfg.get("llm", {})
            client = AsyncOpenAI(base_url=aux.get("base_url", ""), api_key=aux.get("api_key", ""))
            resp = await client.chat.completions.create(
                model=aux.get("model", "deepseek-v4-flash"),
                messages=[
                    {"role": "system", "content": "You are a strict judge. Determine if the ACTUAL ANSWER "
                     "is semantically equivalent to the EXPECTED ANSWER for the given QUESTION. "
                     "Reply with YES or NO only."},
                    {"role": "user", "content": f"QUESTION: {question}\n\n"
                     f"EXPECTED ANSWER: {expected}\n\nACTUAL ANSWER: {actual}"},
                ],
                temperature=0,
                max_tokens=10,
            )
            answer = resp.choices[0].message.content.strip().upper()
            return answer == "YES"
        except Exception:
            # On error, fall back to substring match
            return expected.lower() in actual.lower()
