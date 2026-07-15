from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_deep_research_prompts_define_lightweight_source_priority():
    prompt_paths = [
        ROOT / "skills" / "deep-research" / "SKILL.md",
        ROOT / "agent_types" / "web_researcher.md",
        ROOT / "agent_types" / "analyst.md",
        ROOT / "agent_types" / "critic.md",
    ]

    for prompt_path in prompt_paths:
        text = prompt_path.read_text(encoding="utf-8").lower()
        assert "primary" in text, prompt_path
        assert "authoritative" in text, prompt_path
        assert "community" in text, prompt_path
