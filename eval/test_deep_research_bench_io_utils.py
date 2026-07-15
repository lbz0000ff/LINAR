"""Regression tests for DeepResearch Bench JSONL file handling."""

from __future__ import annotations

import json
from pathlib import Path
import sys


BENCH_DIR = Path(__file__).resolve().parent / "deep_research_bench"
sys.path.insert(0, str(BENCH_DIR))

from utils.io_utils import load_jsonl  # noqa: E402
from deepresearch_bench_race import CRITERIA_FILE, REFERENCE_FILE  # noqa: E402


def test_load_jsonl_reads_utf8_chinese_on_windows(tmp_path: Path) -> None:
    input_path = tmp_path / "query.jsonl"
    expected = [{"id": 1, "prompt": "收集中国9阶层实际收入"}]
    input_path.write_text(
        json.dumps(expected[0], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert load_jsonl(input_path) == expected


def test_bundled_evaluator_assets_do_not_depend_on_working_directory() -> None:
    criteria_path = Path(CRITERIA_FILE)
    reference_path = Path(REFERENCE_FILE)

    assert criteria_path.is_absolute()
    assert criteria_path.is_file()
    assert reference_path.is_absolute()
    assert reference_path.is_file()
