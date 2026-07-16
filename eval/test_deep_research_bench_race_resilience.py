from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest


BENCH_DIR = Path(__file__).parent / "deep_research_bench"
if str(BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(BENCH_DIR))

import deepresearch_bench_race as race  # noqa: E402
from utils.api import EvaluationCancelled  # noqa: E402
from utils.clean_article import ArticleCleaner  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_result_checkpoint_upserts_by_id_without_duplicates(tmp_path: Path) -> None:
    output = tmp_path / "raw_results.jsonl"
    checkpoint = race.ResultCheckpoint(
        output,
        [
            {"id": 2, "overall_score": 0.2},
            {"id": 1, "overall_score": 0.1},
        ],
    )

    checkpoint.record({"id": 2, "overall_score": 0.9})
    checkpoint.record({"id": 3, "overall_score": 0.3})

    rows = _read_jsonl(output)
    assert [row["id"] for row in rows] == [1, 2, 3]
    assert rows[1]["overall_score"] == 0.9
    assert not list(tmp_path.glob("*.tmp"))


def test_result_checkpoint_can_atomically_clear_for_force_run(tmp_path: Path) -> None:
    output = tmp_path / "raw_results.jsonl"
    output.write_text('{"id": 99}\n', encoding="utf-8")
    checkpoint = race.ResultCheckpoint(output)

    checkpoint.clear()

    assert output.read_text(encoding="utf-8") == ""


def test_select_tasks_skips_existing_ids_and_applies_limit_to_remaining() -> None:
    tasks = [
        {"id": 1, "prompt": "one"},
        {"id": 2, "prompt": "two"},
        {"id": 3, "prompt": "three"},
    ]
    complete_prompts = {prompt: {} for prompt in ("one", "two", "three")}

    selected = race._select_tasks_to_process(
        tasks,
        complete_prompts,
        complete_prompts,
        complete_prompts,
        existing_ids={1},
        limit=1,
    )

    assert [task["id"] for task in selected] == [2]


def test_process_single_item_does_not_retry_cancellation() -> None:
    class CancelledClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, **_: object) -> str:
            self.calls += 1
            raise EvaluationCancelled("cancelled")

    class Progress:
        def update(self, _: int) -> None:
            raise AssertionError("cancelled item must not be marked completed")

    client = CancelledClient()
    task = {"id": 1, "prompt": "question"}
    articles = {"question": {"article": "answer"}}
    criteria = {"question": {"criterions": {}}}

    with pytest.raises(EvaluationCancelled):
        race.process_single_item(
            task,
            articles,
            articles,
            criteria,
            client,
            threading.Lock(),
            Progress(),
            max_attempts=3,
            language="zh",
            stop_event=threading.Event(),
        )

    assert client.calls == 1


def test_article_cleaner_does_not_retry_cancellation() -> None:
    class CancelledClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, **_: object) -> str:
            self.calls += 1
            raise EvaluationCancelled("cancelled")

    client = CancelledClient()

    with pytest.raises(EvaluationCancelled):
        ArticleCleaner(client)._clean_text("article", language="en")

    assert client.calls == 1


def test_hard_exit_watchdog_is_daemonized_and_started() -> None:
    created: list[object] = []

    class FakeTimer:
        def __init__(self, delay: float, callback, args: tuple[int]) -> None:
            self.delay = delay
            self.callback = callback
            self.args = args
            self.daemon = False
            self.started = False
            created.append(self)

        def start(self) -> None:
            self.started = True

    exit_calls: list[int] = []
    timer = race._schedule_hard_exit(
        delay=3.0,
        exit_func=exit_calls.append,
        timer_factory=FakeTimer,
    )

    assert timer is created[0]
    assert timer.delay == 3.0
    assert timer.args == (130,)
    assert timer.daemon is True
    assert timer.started is True
