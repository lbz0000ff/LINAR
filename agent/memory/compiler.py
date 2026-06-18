"""View Compiler — compiles the Fact Store into USR.md and AGT.md.

Two-stage process::

    Stage 1 (rules):
        - Properties            → always in View (fixed slots)
        - #pinned facts         → always in View (fixed slots)
        - All active facts      → sorted by ``view_score`` → top-N candidates
        - Candidate pool        → ~30 facts

    Stage 2 (LLM):
        - From ~30 candidates   → pick ~15 that belong in the system prompt
        - Output: selected fact IDs + reason

    After compilation:
        - Update ``view_score`` for every active fact (decay + boost selected)
        - Write ``USR.md`` and ``AGT.md``
        - Mark FactStore as compiled
"""

from __future__ import annotations

import json
import os
import re as _re
from typing import Any

from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompt")
_USR_PATH = os.path.join(_PROMPT_DIR, "USER.md")
_AGT_PATH = os.path.join(_PROMPT_DIR, "AGENT.md")

# ---------------------------------------------------------------------------
# Configurable limits
# ---------------------------------------------------------------------------

_PROPERTIES_LIMIT = 15
_PINNED_LIMIT = 5
_CANDIDATE_POOL_SIZE = 30
_SELECTED_SLOTS = 15
_SCORE_DECAY = 0.8
_NEW_FACT_BIAS = 0.3

# ---------------------------------------------------------------------------
# Stage 1 — rules-based filtering
# ---------------------------------------------------------------------------


def _stage1_rules(
    store: Any,
    topic_registry: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply rule-based filtering.

    Returns ``(unconditional, candidates)`` where:

    * *unconditional* — facts that are always included (properties + pinned).
    * *candidates* — the top ``_CANDIDATE_POOL_SIZE`` facts by ``view_score``.
    """
    from memory.fact import Fact

    unconditional: list[dict[str, Any]] = []

    # Properties (from FactStore)
    for prop in store.get_properties():
        unconditional.append({
            "type": "property",
            "key": prop["key"],
            "value": prop["value"],
        })

    # Pinned facts
    pinned_count = 0
    candidates_pool: list[Fact] = []
    for fact in store.all(active=True):
        if fact.pinned and pinned_count < _PINNED_LIMIT:
            unconditional.append({
                "type": "fact",
                "id": fact.id,
                "content": fact.content,
                "topic": fact.topic,
                "view_score": fact.view_score,
                "pinned": True,
            })
            pinned_count += 1
        else:
            candidates_pool.append(fact)

    # Sort by view_score descending, take top N
    candidates_pool.sort(key=lambda f: f.view_score, reverse=True)
    top_candidates = candidates_pool[:_CANDIDATE_POOL_SIZE]

    candidates: list[dict[str, Any]] = [
        {
            "type": "fact",
            "id": f.id,
            "content": f.content,
            "topic": f.topic,
            "view_score": f.view_score,
            "pinned": f.pinned,
        }
        for f in top_candidates
    ]

    return unconditional, candidates


# ---------------------------------------------------------------------------
# Stage 2 — LLM selection
# ---------------------------------------------------------------------------


_COMPILER_SYSTEM_PROMPT = """You are a prompt compiler for an AI assistant's long-term memory.

Your task is to select the most important facts from a candidate pool
to include in the system prompt.  You NEVER rewrite or condense facts;
you only choose which full sentences to include.

Selection priority (high to low):
1. User identity and immutable attributes (name, language, etc.)
2. User's explicitly stated behavioral preferences
3. Long-standing project state and technical decisions
4. Recent significant behavioral adjustments

Constraints:
- Output ONLY valid JSON (no markdown fences, no commentary).
- Do NOT rewrite or abbreviate any fact.
- If a fact's topic assignment seems wrong, note it in its ``reason``.

Output:
{"selected": [{"id": "fact_042", "reason": "current preference — supersedes earlier versions"}, {"id": "fact_018", "reason": "key architectural decision"}]}"""


def _call_compiler_llm(
    prompt: str,
    cfg: dict[str, Any],
) -> str:
    """Non-streaming LLM call for View compilation."""
    import openai

    client = openai.OpenAI(
        base_url=cfg.get("base_url"),
        api_key=cfg.get("api_key"),
    )
    model = cfg.get("model", "deepseek-v4-flash")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _COMPILER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _parse_compiler_response(raw: str) -> list[str]:
    """Extract the list of selected fact IDs from the LLM JSON response."""
    text = raw.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text)
    text = _re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Compiler LLM returned non-JSON: %.200s", raw)
        return []

    selected = data.get("selected", [])
    if isinstance(selected, list):
        return [s["id"] for s in selected if isinstance(s, dict) and s.get("id")]
    return []


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def _write_view_files(
    unconditional: list[dict[str, Any]],
    selected_facts: list[dict[str, Any]],
) -> None:
    """Write USR.md and AGT.md to the prompt directory.

    USR.md contains properties + all selected facts from ``preference``
    and ``general`` topics.

    AGT.md contains all selected facts from ``behavior``, ``workflow``,
    ``project``, and other topics.
    """
    os.makedirs(_PROMPT_DIR, exist_ok=True)

    usr_lines = ["# User State\n"]
    agt_lines = ["# Agent State\n"]

    # Properties → USR only
    unconditional_props = [u for u in unconditional if u["type"] == "property"]
    unconditional_pinned = [u for u in unconditional if u["type"] == "fact"]

    if unconditional_props:
        usr_lines.append("## Properties\n")
        for p in unconditional_props:
            usr_lines.append(f"- {p['key']}: {p['value']}")
        usr_lines.append("")

    # Pinned facts → split by topic
    user_topics = {"preference", "general"}
    agent_topics = {"behavior", "workflow", "project"}

    user_facts = [f for f in selected_facts if f["topic"] in user_topics]
    agent_facts = [f for f in selected_facts if f["topic"] not in user_topics]
    # Pinned go to logical side
    user_pinned = [f for f in unconditional_pinned if f["topic"] in user_topics]
    agent_pinned = [f for f in unconditional_pinned if f["topic"] not in user_topics]

    if user_pinned or user_facts:
        usr_lines.append("## Long-term Facts\n")
        for f in (user_pinned + user_facts):
            usr_lines.append(f"- [{f['id']}] {f['content']}")
        usr_lines.append("")

    if agent_pinned or agent_facts:
        agt_lines.append("## Long-term Facts\n")
        for f in (agent_pinned + agent_facts):
            agt_lines.append(f"- [{f['id']}] {f['content']}")
        agt_lines.append("")

    usr_content = "\n".join(usr_lines).strip()
    agt_content = "\n".join(agt_lines).strip()

    with open(_USR_PATH, "w", encoding="utf-8") as f:
        f.write(usr_content)
    with open(_AGT_PATH, "w", encoding="utf-8") as f:
        f.write(agt_content)

    log.info("Wrote USR.md (%d bytes) and AGT.md (%d bytes)",
             len(usr_content), len(agt_content))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compile_view(store: Any, topic_registry: Any, llm_cfg: dict[str, Any]) -> None:
    """Run the full compilation pipeline.

    *store* — a ``FactStore`` instance.
    *topic_registry* — a ``TopicRegistry`` instance.
    *llm_cfg* — LLM config dict for the compiler call (or ``None`` to skip Stage 2).
    """
    # ── Stage 1: rules ──────────────────────────────────────
    unconditional, candidates = _stage1_rules(store, topic_registry)

    if not candidates and not unconditional:
        log.debug("Nothing to compile — empty fact store")
        # Still write empty files (fallback will read old USER.md/MEMORY.md)
        _write_view_files(unconditional, [])
        store.update_view_scores([], decay=_SCORE_DECAY)
        store.save()
        store.mark_compiled()
        return

    # ── Stage 2: LLM ────────────────────────────────────────
    selected_ids: list[str] = []
    if llm_cfg and candidates:
        # Build the candidate prompt
        candidate_lines = ["Candidate facts (select up to %d):" % _SELECTED_SLOTS]
        for i, c in enumerate(candidates, 1):
            candidate_lines.append(
                f"  {i}. [{c['id']}] (topic={c['topic']}, score={c['view_score']}) "
                f"{c['content']}"
            )
        prompt = "\n".join(candidate_lines)

        try:
            raw = _call_compiler_llm(prompt, llm_cfg)
            selected_ids = _parse_compiler_response(raw)
            log.debug("Compiler selected %d facts from %d candidates",
                      len(selected_ids), len(candidates))
        except Exception as e:
            log.warning("Compiler LLM call failed: %s — using top candidates", e)

    # Fallback if LLM selection fails: use top candidates by score
    if not selected_ids:
        selected_ids = [c["id"] for c in candidates[:_SELECTED_SLOTS]]
        log.info("Fallback: using top %d candidates by view_score", len(selected_ids))

    # Build full selected list (all unconditional + selected candidates)
    unconditional_facts = [u for u in unconditional if u["type"] == "fact"]
    selected_candidates = [c for c in candidates if c["id"] in selected_ids]
    all_selected = unconditional_facts + selected_candidates

    # ── Write output files ──────────────────────────────────
    _write_view_files(unconditional, all_selected)

    # ── Update scores ───────────────────────────────────────
    store.update_view_scores(selected_ids, decay=_SCORE_DECAY)
    store.save()           # persist score changes first
    store.mark_compiled()  # then mark, so version > fact_pool mtime

    log.info(
        "Compilation done: %d unconditional + %d selected = %d facts in View",
        len(unconditional_facts),
        len(selected_candidates),
        len(all_selected),
    )
