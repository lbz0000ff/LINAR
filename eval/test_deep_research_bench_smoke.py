"""Offline contract tests for the one-command Deep Research smoke runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType


ROOT_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT_DIR / "eval" / "deep_research_bench"
SMOKE_SCRIPT = BENCH_DIR / "smoke_test.py"


def _load_smoke_module() -> ModuleType:
    assert SMOKE_SCRIPT.is_file(), "smoke_test.py has not been implemented"
    spec = importlib.util.spec_from_file_location("deep_research_smoke", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_stages_uses_root_for_generation_and_bench_for_scoring() -> None:
    smoke = _load_smoke_module()
    python = Path("C:/Python/python.exe")
    query_file = Path("C:/Temp/smoke-query.jsonl")

    generation, scoring = smoke.build_stages(
        model_name="linar-smoke-123",
        language="zh",
        python_executable=python,
        query_file=query_file,
    )

    assert generation.cwd == ROOT_DIR
    assert generation.command == [
        str(python),
        "-u",
        str(ROOT_DIR / "eval" / "run_deep_research_bench.py"),
        "--limit",
        "1",
        "--query-file",
        str(query_file),
        "--model-name",
        "linar-smoke-123",
    ]
    assert scoring.cwd == BENCH_DIR
    assert scoring.command == [
        str(python),
        "-u",
        str(BENCH_DIR / "deepresearch_bench_race.py"),
        "linar-smoke-123",
        "--limit",
        "1",
        "--query_file",
        str(query_file),
        "--only_zh",
        "--max_workers",
        "1",
        "--output_dir",
        "results/race/linar-smoke-123",
    ]


def test_read_query_selects_requested_id(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    query_path = tmp_path / "query.jsonl"
    query_path.write_text(
        "\n".join(
            [
                json.dumps({"id": 1, "language": "zh", "prompt": "first"}),
                json.dumps({"id": 20, "language": "en", "prompt": "safe technical query"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert smoke.read_query(20, query_path) == {
        "id": 20,
        "language": "en",
        "prompt": "safe technical query",
    }


def test_default_smoke_query_is_low_sensitivity_technical_question() -> None:
    smoke = _load_smoke_module()

    assert smoke.DEFAULT_QUERY_ID == 20


def test_default_model_name_is_safe_and_unique_by_timestamp() -> None:
    smoke = _load_smoke_module()

    assert smoke.default_model_name("20260714-183000") == (
        "linar-step-3.7-flash-smoke-20260714-183000"
    )
