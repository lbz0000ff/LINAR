"""Configuration contract tests for the bundled DRB evaluator client."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping


BENCH_DIR = Path(__file__).resolve().parent / "deep_research_bench"
SUBPROCESS_ENV_VARS = {
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
}


def _read_api_config(overrides: Mapping[str, str]) -> dict[str, str]:
    env = {
        name: os.environ[name]
        for name in SUBPROCESS_ENV_VARS
        if name in os.environ
    }
    env.update(overrides)

    script = """
import json
from utils import api

client = api.AIClient()
print(json.dumps({
    "backend": api.LLM_BACKEND,
    "api_key": client.api_key,
    "base_url": client.base_url,
    "race_model": api.Model,
    "fact_model": api.FACT_Model,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BENCH_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip())


def test_uuapi_is_the_default_evaluator_backend() -> None:
    config = _read_api_config({"UUAPI_API_KEY": "test-uuapi-key"})

    assert config == {
        "backend": "uuapi",
        "api_key": "test-uuapi-key",
        "base_url": "https://uuapi.net/v1",
        "race_model": "gpt-5.5",
        "fact_model": "gpt-5.4-mini",
    }


def test_uuapi_allows_endpoint_and_model_overrides() -> None:
    config = _read_api_config(
        {
            "LLM_BACKEND": "uuapi",
            "UUAPI_API_KEY": "test-override-key",
            "UUAPI_BASE_URL": "https://proxy.example/v1/",
            "RACE_MODEL": "custom-race",
            "FACT_MODEL": "custom-fact",
        }
    )

    assert config == {
        "backend": "uuapi",
        "api_key": "test-override-key",
        "base_url": "https://proxy.example/v1",
        "race_model": "custom-race",
        "fact_model": "custom-fact",
    }


def test_openai_backend_remains_selectable() -> None:
    config = _read_api_config(
        {
            "LLM_BACKEND": "openai",
            "OPENAI_API_KEY": "test-openai-key",
        }
    )

    assert config["backend"] == "openai"
    assert config["api_key"] == "test-openai-key"
    assert config["base_url"] == "https://api.openai.com/v1"
