"""Extractor — reads conversation windows and commits extracted facts.

The extractor runs on a schedule (every N rounds, with back-pressure
when extractions yield nothing).  It is **not** a background agent;
it is a simple function called from a hook after each round.

Data flow::

    Agent round completes
        → hook triggers ``try_extract()``
            → ``should_extract()`` checks back-pressure
                → ``extract()`` builds the delta window
                    → LLM extracts candidate facts
                        → collision detection per fact
                            → commit to FactStore
"""

from __future__ import annotations

import json
import os
import re as _re
from typing import Any

from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "state", "extraction_state.json"
)

_DEFAULT_STATE: dict[str, Any] = {
    "last_extraction_round": 0,
    "last_extraction_turn": 0,
    "consecutive_failures": 0,
    "current_interval": 6,
}

_INTERVAL = 6
_MAX_WINDOW_ROUNDS = 20


def _load_state() -> dict[str, Any]:
    if os.path.isfile(_STATE_PATH):
        try:
            with open(_STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Failed to load extraction state, resetting")
    return dict(_DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    tmp = _STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, _STATE_PATH)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def should_extract(
    state: dict[str, Any] | None = None,
    current_round: int = 0,
    extraction_interval: int = _INTERVAL,
) -> bool:
    """Return ``True`` if extraction should run now.

    Fixed-interval rules:

    * Run every ``extraction_interval`` rounds regardless of content.
    * No back-pressure — empty extractions do not stretch the interval
      or suppress future extractions.
    """
    if state is None:
        state = _load_state()

    delta = current_round - state.get("last_extraction_round", 0)

    if delta < extraction_interval:
        return False

    return True


# ---------------------------------------------------------------------------
# Window building
# ---------------------------------------------------------------------------


def _build_window(
    messages: list[dict[str, Any]],
    start_round: int,
    end_round: int,
) -> str:
    """Format a subset of conversation messages for the extraction LLM.

    Only messages with round > *start_round* and ≤ *end_round* are
    included.  Tool results are condensed to a single line.
    """
    lines: list[str] = []
    for m in messages:
        rnd = m.get("conversation_round") or 0
        if rnd <= start_round:
            continue
        if rnd > end_round:
            break

        role = m.get("role", "unknown")
        content = (m.get("content") or "").strip()
        if not content:
            continue

        if role == "user":
            lines.append(f"User: {content[:1500]}")
        elif role == "agent":
            lines.append(f"Assistant: {content[:1500]}")
        elif role == "tool":
            tool = m.get("tool_name") or "tool"
            lines.append(f"[Tool {tool}: {content[:200]}]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------


_EXTRACTOR_SYSTEM_PROMPT = """You are a state extraction system.

Your task is to read a conversation window and extract facts that are
worth remembering across sessions.  Each fact must be a single,
self-contained sentence.

Rules:
- Each fact is ONE complete sentence.  Not a summary, not keywords.
- Each fact belongs to exactly one existing topic, or you create a new one.
- If you see new information that contradicts an existing fact, mark it as a conflict.
- If nothing worth remembering happened, return an empty list.

Output ONLY valid JSON (no markdown fences, no commentary):
{
  "facts": [
    {
      "content": "user prefers Python for data processing",
      "topic": "preference",
      "topic_definition": ""
    }
  ]
}

When creating a new topic, set "topic" to the new name and provide a
"topic_definition" (one sentence).  When using an existing topic, leave
"topic_definition" empty.

If no facts are worth extracting, return: {"facts": []}"""


def _call_extraction_llm(prompt: str, cfg: dict) -> str:
    """Non-streaming LLM call for extraction.

    *cfg* must contain ``base_url``, ``api_key``, and optionally ``model``.
    """
    import openai

    client = openai.OpenAI(
        base_url=cfg.get("base_url"),
        api_key=cfg.get("api_key"),
    )
    model = cfg.get("model", "deepseek-v4-flash")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _EXTRACTOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _parse_extraction_response(raw: str) -> list[dict[str, Any]]:
    """Parse the LLM JSON response into a list of fact-like dicts."""
    text = raw.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text)
    text = _re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Extraction LLM returned non-JSON: %.200s", raw)
        return []

    facts_raw = data.get("facts", [])
    if not isinstance(facts_raw, list):
        return []

    result: list[dict[str, Any]] = []
    for item in facts_raw:
        if isinstance(item, dict) and item.get("content"):
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def try_extract(
    store: Any,
    topic_registry: Any,
    messages: list[dict[str, Any]],
    session_id: int,
    current_round: int,
    llm_cfg: dict[str, Any],
    extraction_interval: int = _INTERVAL,
) -> list[Any]:
    """Run one extraction cycle.

    *store* — a ``FactStore`` instance.
    *topic_registry* — a ``TopicRegistry`` instance.
    *messages* — all messages for the current session
        (from ``database.get_session_messages()``).
    *session_id* — the current session id.
    *current_round* — the current ``conversation_round``.
    *llm_cfg* — LLM config dict (``base_url``, ``api_key``, ``model``).
    *extraction_interval* — rounds between extractions (default 6).

    Returns the list of newly committed ``Fact`` objects, or an empty
    list if nothing was extracted or on failure (never raises).
    """
    from memory.fact import Fact
    from memory.collision import detect as collision_detect
    from memory.collision import Duplicate, Extends, Conflict, NewFact

    state = _load_state()

    # ── 1. Scheduling ────────────────────────────────────────
    if not should_extract(state, current_round, extraction_interval):
        return []

    # ── 2. Build window ──────────────────────────────────────
    start_rnd = state.get("last_extraction_round", 0)
    window = _build_window(messages, start_rnd, current_round)
    if not window.strip():
        log.debug("Extraction window empty (rounds %d→%d)", start_rnd, current_round)
        return []

    # ── 3. LLM call ──────────────────────────────────────────
    topic_defs = topic_registry.get_definitions_text()
    full_prompt = (
        f"Current topics:\n{topic_defs}\n\n"
        f"Conversation window (round {start_rnd + 1} → {current_round}):\n"
    )
    # Trim window to avoid exceeding context limits
    max_window_chars = 6000
    trimmed = window if len(window) <= max_window_chars else window[:max_window_chars] + "\n…(truncated)"

    try:
        raw = _call_extraction_llm(full_prompt + trimmed, llm_cfg)
    except Exception as e:
        log.warning("Extraction LLM call failed: %s", e)
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        _save_state(state)
        return []

    facts_data = _parse_extraction_response(raw)
    if not facts_data:
        log.debug("Extraction LLM returned no facts")
        state["last_extraction_round"] = current_round
        _save_state(state)
        return []

    # ── 4. Collision detection + commit ──────────────────────
    new_facts: list[Fact] = []
    for fd in facts_data:
        topic_name = fd["topic"]

        # Handle new topic creation
        if fd.get("topic_definition"):
            topic_registry.add(topic_name, fd["topic_definition"])

        candidates = store.get_by_topic(topic_name, active=True)
        result = collision_detect(fd["content"], candidates)
        source = f"s{session_id}_t{start_rnd + 1}-{current_round}"

        if isinstance(result, NewFact):
            fact = Fact(content=fd["content"], topic=topic_name, source=source)
            store.commit(fact)
            new_facts.append(fact)
            log.debug("Extracted new fact: %s", fd["content"][:60])

        elif isinstance(result, (Extends, Conflict)):
            fact = Fact(content=fd["content"], topic=topic_name, source=source)
            store.commit(fact, conflicting=result.existing)
            new_facts.append(fact)
            log.debug(
                "Extracted fact (supersedes %s): %s",
                result.existing.id if result.existing else "?",
                fd["content"][:60],
            )
        # Duplicate → silently skip

    # ── 5. Update state ──────────────────────────────────────
    state["last_extraction_round"] = current_round
    state["last_extraction_turn"] = current_round
    state["consecutive_failures"] = 0
    state["current_interval"] = extraction_interval

    _save_state(state)
    store.save()

    log.info("Extracted %d new facts (rounds %d→%s)", len(new_facts), start_rnd, current_round)
    return new_facts
