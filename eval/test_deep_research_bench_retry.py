from __future__ import annotations

import importlib
from pathlib import Path
import sys
import threading


BENCH_DIR = Path(__file__).resolve().parent / "deep_research_bench"
sys.path.insert(0, str(BENCH_DIR))

race = importlib.import_module("deepresearch_bench_race")


class _AlwaysFailClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("temporary evaluator failure")


class _Progress:
    def update(self, _amount: int) -> None:
        return None


def test_evaluator_stops_after_three_total_attempts(monkeypatch) -> None:
    prompt = "test prompt"
    client = _AlwaysFailClient()
    monkeypatch.setattr(race.time, "sleep", lambda _delay: None)

    result = race.process_single_item(
        {"id": 1, "prompt": prompt},
        {prompt: {"article": "target"}},
        {prompt: {"article": "reference"}},
        {prompt: {"criterions": {}}},
        client,
        threading.Lock(),
        _Progress(),
        race.MAX_RETRIES,
        "zh",
    )

    assert race.MAX_RETRIES == 3
    assert client.calls == 3
    assert result["error"] == "Failed to get valid response after 3 attempts"
