"""Memory tools: remember and recall with archival and event referencing."""

import difflib
import os
import re
from datetime import datetime

from .tool import Tool

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROMPT_DIR = os.path.join(_AGENT_DIR, "prompt")
_MEMORY_FILE = os.path.join(_PROMPT_DIR, "MEMORY.md")
_USER_FILE = os.path.join(_PROMPT_DIR, "USER.md")
_ARCHIVE_DIR = os.path.join(_AGENT_DIR, "memory", "archived")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config():
    import yaml
    cfg_path = os.path.join(_AGENT_DIR, "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    return cfg


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)



def _next_id(content: str, prefix: str) -> int:
    """Return the next sequential ID (prefix + number) for a memory file.

    prefix='M' scans for ``[M<N>]``, prefix='U' for ``[U<N>]``.
    """
    pattern = re.compile(rf"\[{prefix}(\d+)\]")
    existing = [int(m) for m in pattern.findall(content)]
    return max(existing, default=0) + 1


def _get_current_session_id():
    """Return the most recent session id from DB (the current conversation)."""
    import database as db
    sessions = db.get_recent_sessions(1)
    return sessions[0]["id"] if sessions else None


def _shorten(text: str, max_len: int = 70) -> str:
    """Truncate text at a sentence boundary within max_len."""
    if len(text) <= max_len:
        return text
    # Try to break at the last sentence end before max_len
    cutoff = text[:max_len]
    for sep in ("。", "！", "？", ". ", "! ", "? "):
        idx = cutoff.rfind(sep)
        if idx > max_len // 2:  # only if we keep at least half
            return text[:idx + len(sep)] + "…"
    # fallback: break at last space
    idx = cutoff.rfind(" ")
    return (cutoff[:idx] + "…") if idx > max_len // 2 else cutoff + "…"


def _parse_turns(turns_str: str):
    """Parse a turns string like ``"3"`` or ``"3,5"`` into (start, end)."""
    turns_str = turns_str.strip()
    if not turns_str:
        return None
    parts = turns_str.split(",")
    try:
        start = int(parts[0])
        end = int(parts[1]) if len(parts) > 1 else start
        return (min(start, end), max(start, end))
    except (ValueError, IndexError):
        return None


def _get_dedup_threshold() -> float:
    """Read similarity threshold from config.yaml, default 0.85."""
    cfg = _load_config()
    try:
        return float(cfg.get("memory_dedup_threshold", 0.85))
    except (TypeError, ValueError):
        return 0.85


def _is_duplicate(content: str, prefix: str, value: str, threshold: float = 0.85):
    """Check if *value* already exists in a memory file.

    Returns ``(existing_id, match_type)`` or ``(None, None)``.
    *match_type* is ``'exact'`` or ``'fuzzy'``.
    """
    pattern = re.compile(rf"- \[({prefix}\d+)\]\s+(.*)")
    value_norm = value.strip().lower()

    for existing_id, existing_value in pattern.findall(content):
        existing_norm = existing_value.strip().lower()

        if existing_norm == value_norm:
            return (existing_id, "exact")

        ratio = difflib.SequenceMatcher(None, existing_norm, value_norm).ratio()
        if ratio >= threshold:
            return (existing_id, "fuzzy")

    return (None, None)


_COMPRESS_TRIGGER = 0.75  # trigger compression at 75% of max chars


def _llm_compress(entries: list) -> tuple[list, list]:
    """Ask the LLM to split entries into keep vs archive.

    *entries* is a list of (id, text) tuples, e.g. ``("U1", "name is Alex")``.
    Returns ``(keep_ids, archive_ids)``.

    On any failure, returns (all IDs, []) — no data loss.
    """
    if not entries:
        return ([], [])

    cfg = _load_config()
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=cfg["llm"]["base_url"],
            api_key=cfg["llm"]["api_key"],
        )

        entries_text = "\n".join(f"- [{eid}] {text}" for eid, text in entries)
        prompt = (
            "You are a memory management system. Classify each entry as KEEP or ARCHIVE.\n\n"
            "KEEP = the AI assistant must ALWAYS know this without searching:\n"
            "- User's name, identity, core preferences\n"
            "- Critical ongoing facts the assistant needs constantly\n\n"
            "ARCHIVE = useful but not critical; can be searched later if needed:\n"
            "- Temporary observations\n"
            "- Nice-to-know but non-essential details\n"
            "- Historical notes that don't affect current interactions\n\n"
            "Respond ONLY with valid JSON:\n"
            '{"keep": ["id1", "id2", ...], "archive": ["id3", "id4", ...]}'
        )

        response = client.chat.completions.create(
            model=cfg["llm"]["model"],
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Classify these entries:\n{entries_text}"},
            ],
            temperature=0.1,
            max_tokens=1000,
        )

        raw = response.choices[0].message.content.strip()

        # Extract JSON from possible markdown fences or surrounding text
        import json
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw)

        keep = result.get("keep", [])
        archive = result.get("archive", [])

        # Validate IDs — only return IDs that actually exist in input
        valid_ids = {eid for eid, _ in entries}
        keep = [eid for eid in keep if eid in valid_ids]
        archive = [eid for eid in archive if eid in valid_ids]

        # If everything is archive, keep at least the most important entry
        if not keep and archive:
            keep = [archive.pop(0)]

        return (keep, archive)

    except Exception:
        # On any error: keep everything, no data loss
        return ([eid for eid, _ in entries], [])


# ---------------------------------------------------------------------------
# Remember Tool
# ---------------------------------------------------------------------------

def _is_deletion(value: str) -> bool:
    """Return True if the value signals a deletion (empty / placeholder)."""
    return not value.strip() or value.strip() in ("（已删除）", "(deleted)")


class Tool_Remember(Tool):
    name: str = "remember"
    description: str = "Store a summary of important conversation turns to memory for future retrieval."
    tool_schema: dict = {
        "name": "remember",
        "description": "Stores information to persistent memory files that are reloaded "
                       "in future conversations.\n\n"
                       "- user: the USER's personal traits, preferences, habits → USER.md\n"
                       "- normal: facts about Lily herself or the conversation → MEMORY.md\n"
                       "- archive: content too long to fit in a single MEMORY.md line (>250 chars) "
                       "→ saved as a separate .md file, with [MEM:tag] in MEMORY.md\n"
                       "- event: bookmark conversation turns → [EVENT:session_id,turns] "
                       "short sentence in MEMORY.md",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "description": "user: user's traits/preferences → USER.md. "
                                   "normal: fact about Lily/conversation → MEMORY.md. "
                                   "archive: long content → separate file with [MEM:tag]. "
                                   "event: bookmark conversation turns → [EVENT:...] short sentence."
                },
                "value": {
                    "type": "string",
                    "description": "For user: description of the user's trait/preference. "
                                   "For normal: the fact to remember. "
                                   "For archive: the full detailed content to save as a file. "
                                   "For event: short keywords only (3-10 words), not a full sentence. "
                                   "This is used as a summary label in MEMORY.md."
                },
                "turns": {
                    "type": "string",
                    "description": "Only for event mode. The conversation turn(s) to bookmark. "
                                   "Single turn: '3'. Range: '3,5'. "
                                   "(The [turn N] markers in chat history tell you which turn you're on.)"
                },
                "event_ref": {
                    "type": "string",
                    "description": "Only for archive mode. The source event turn(s) this archived "
                                   "content came from, e.g. '3' or '3,5'. "
                                   "Links the archived file back to the original conversation."
                },
                "update_id": {
                    "type": "string",
                    "description": "Optional. If provided, UPDATE the existing memory with this ID "
                                   "instead of creating a new one. E.g., 'U1' or 'M3'. "
                                   "Use when the user's preference has changed or a fact needs correction. "
                                   "Only supported for 'user' and 'normal' memory types."
                }
            },
            "required": ["memory_type", "value"]
        }
    }

    def execute(self, memory_type: str, value: str, turns: str = "", event_ref: str = "",
                update_id: str = ""):
        if update_id:
            if memory_type == "user":
                return self._update_user(update_id, value)
            elif memory_type == "normal":
                return self._update_normal(update_id, value)
            else:
                return (f"Error: update_id is only supported for 'user' and 'normal' "
                        f"memory types, got '{memory_type}'.")
        if memory_type == "user":
            return self._user(value)
        elif memory_type == "normal":
            return self._normal(value)
        elif memory_type == "archive":
            return self._archive(value, event_ref)
        elif memory_type == "event":
            return self._event(value, turns)
        else:
            return f"Error: Unknown memory_type '{memory_type}'. Use: user, normal, archive, or event."

    # ── append a line under ## Memories in MEMORY.md ──────────

    def _append(self, label: str, line: str):
        """Append *line* under ## Memories, prepending ``[M<N>] `` label."""
        content = _read_file(_MEMORY_FILE)

        # Dedup check — skip if this line already exists (exact or fuzzy)
        dedup_id, match = _is_duplicate(content, "M", line, _get_dedup_threshold())
        if dedup_id:
            return f"[{dedup_id}]"

        if not content.strip():
            content = "# Summary of chatting history\n\n## Memories\n"
        elif "## Memories" not in content:
            content += "\n\n## Memories\n"

        cfg = _load_config()
        max_chars = cfg.get("max_memory_length", 2200)
        if len(content) > max_chars * _COMPRESS_TRIGGER:
            content = self._compress_entries(content, "M", max_chars, "memory")

        content += f"- {label} {line}\n"
        _write_file(_MEMORY_FILE, content)
        return label

    # ── user: user traits/preferences → USER.md ────────────

    def _user(self, value: str) -> str:
        content = _read_file(_USER_FILE)

        # Dedup check
        dedup_id, match = _is_duplicate(content, "U", value, _get_dedup_threshold())
        if dedup_id:
            preview = value[:80] + ("…" if len(value) > 80 else "")
            return f"Already exists as [{dedup_id}]: {preview}"

        if not content.strip():
            content = "# User's preferences\n\n## Traits & Preferences\n"
        elif "## Traits" not in content and "## Preferences" not in content:
            content += "\n\n## Traits & Preferences\n"

        cfg = _load_config()
        max_chars = cfg.get("max_user_preferences_length", 500)
        if len(content) > max_chars * _COMPRESS_TRIGGER:
            content = self._compress_entries(content, "U", max_chars, "user")

        uid = _next_id(content, "U")
        content += f"- [U{uid}] {value}\n"
        _write_file(_USER_FILE, content)

        preview = value[:80] + ("…" if len(value) > 80 else "")
        return f"Stored in USER.md as [U{uid}]: {preview}"

    # ── normal: short fact → MEMORY.md (auto-archive if too long) ────

    def _normal(self, value: str) -> str:
        # Auto-redirect long entries to archive
        if len(value) > 250:
            return self._archive(value)
        mid = self._append(f"[M{_next_id(_read_file(_MEMORY_FILE), 'M')}]", value)
        preview = value[:80] + ("…" if len(value) > 80 else "")
        return f"→ {mid}: {preview}"

    # ── archive: long content → separate .md + [MEM:tag] ──

    def _archive(self, value: str, event_ref: str = "") -> str:
        os.makedirs(_ARCHIVE_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        first_line = value.strip().split("\n")[0]
        slug_raw = re.sub(r"[^a-zA-Z0-9一-鿿_-]", "", first_line)[:30]
        slug = f"{timestamp}_{slug_raw}" if slug_raw else timestamp

        filepath = os.path.join(_ARCHIVE_DIR, f"{slug}.md")

        # Prepend event reference to the file content if provided
        store_value = value
        if event_ref:
            header = f"> Source: [EVENT:{_get_current_session_id()},{event_ref}]\n\n"
            store_value = header + value

        _write_file(filepath, store_value)

        tag = f"[MEM:{slug}]"
        # Link to event in the MEMORY.md entry
        event_link = f" <- [EVENT:{_get_current_session_id()},{event_ref}]" if event_ref else ""
        summary = _shorten(first_line, 70)

        mid = self._append(f"[M{_next_id(_read_file(_MEMORY_FILE), 'M')}]", f"{summary} {tag}{event_link}")
        return f"Archived to memory/archived/{slug}.md, {mid} added to MEMORY.md"

    # ── event: bookmark conversation → [EVENT:...] tag ─────

    def _event(self, value: str, turns: str = "") -> str:
        parsed = _parse_turns(turns) if turns else None
        if not parsed:
            return ("Error: event mode requires a 'turns' parameter. "
                    "Provide a turn number or range based on the [turn N] markers, "
                    "e.g. turns='3' or turns='3,5'.")

        turn_start, turn_end = parsed
        session_id = _get_current_session_id()
        if session_id is None:
            return "Error: no active session found."

        tag = f"[EVENT:{session_id},{turn_start},{turn_end}]"
        summary = _shorten(value, 70)

        mid = self._append(f"[M{_next_id(_read_file(_MEMORY_FILE), 'M')}]", f"{summary} {tag}")
        return f"Event bookmark added to MEMORY.md as {mid}: {summary} {tag}"

    # ── compress: LLM-classify + archive old entries when near char limit ──

    def _compress_entries(self, content: str, prefix: str, max_chars: int,
                          archive_prefix: str) -> str:
        """Compress memory file by archiving older entries via LLM.

        Takes the older half of entries under a ``##`` section, sends them to the
        LLM to classify as keep (essential) vs archive (optional). Archived entries
        are moved to ``memory/archived/{slug}.md``, and an index line with
        ``[MEM:{slug}]`` is added to the file. Kept entries remain in place.

        *prefix* ``"U"`` or ``"M"`` — determines ID pattern to scan.
        *max_chars* — character limit from config.
        *archive_prefix* — ``"user"`` or ``"memory"``, used in archive filename.

        On any failure, returns content unchanged (no data loss).
        """
        lines = content.split("\n")

        # Find ## section start
        section_start = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("## "):
                section_start = i
                break

        header = lines[:section_start]
        section_line = lines[section_start] if section_start < len(lines) else ""
        entries_lines = lines[section_start + 1:]

        # Parse entries with ID pattern
        pattern = re.compile(rf"-\s*\[({prefix}\d+)\]\s+(.*)")
        entries = []
        non_entry_lines = []
        for i, line in enumerate(entries_lines):
            m = pattern.match(line)
            if m:
                entries.append((i, m.group(1), m.group(2)))
            else:
                non_entry_lines.append((i, line))

        if len(entries) < 4:
            return content  # too few to compress

        # Old half → LLM (skip tagged entries like [MEM:] / [EVENT:])
        mid = len(entries) // 2
        old_half = entries[:mid]
        new_half = entries[mid:]

        untagged = [(eid, text) for _, eid, text in old_half
                     if "[MEM:" not in text and "[EVENT:" not in text]
        tagged = [(idx, eid, text) for idx, eid, text in old_half
                   if "[MEM:" in text or "[EVENT:" in text]

        if not untagged:
            return content  # all old entries are already references

        keep_ids, archive_ids = _llm_compress(untagged)

        if not archive_ids:
            return content  # LLM says everything should stay

        # Build archive file
        archive_text = "\n".join(
            [f"- [{eid}] {text}" for eid, text in untagged if eid in archive_ids])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{archive_prefix}_compress_{timestamp}"
        os.makedirs(_ARCHIVE_DIR, exist_ok=True)
        _write_file(os.path.join(_ARCHIVE_DIR, f"{slug}.md"), archive_text)

        # Rebuild section content
        kept = [f"- [{eid}] {text}" for eid, text in untagged if eid in keep_ids]
        kept.extend(f"- [{eid}] {text}" for _, eid, text in tagged)
        new_part = [f"- [{eid}] {text}" for _, eid, text in new_half]

        section_body = "\n".join(kept + new_part)
        non_entry_text = [line for _, line in non_entry_lines if line.strip()]
        if non_entry_text:
            section_body += "\n" + "\n".join(non_entry_text)
        section_body += f"\n\n*({len(archive_text.split(chr(10)))} older entries archived → [MEM:{slug}])*\n"

        result = "\n".join(header)
        if section_line:
            result += "\n" + section_line + "\n" + section_body
        else:
            result += "\n" + section_body

        return result

    # ── update existing entry by ID ──────────────────────────

    def _update_user(self, id_str: str, new_value: str) -> str:
        """Replace or delete a [U{N}] line in USER.md."""
        content = _read_file(_USER_FILE)
        lines = content.split("\n")
        pattern = re.compile(rf"^(\s*-\s*\[{re.escape(id_str)}\]\s*).*")
        found = False
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if m:
                if _is_deletion(new_value):
                    lines.pop(i)
                    found = True
                    _write_file(_USER_FILE, "\n".join(lines))
                    return f"Deleted [{id_str}] from USER.md."
                lines[i] = f"{m.group(1)}{new_value}"
                found = True
                break
        if not found:
            return f"Error: [{id_str}] not found in USER.md."
        _write_file(_USER_FILE, "\n".join(lines))
        preview = new_value[:80] + ("…" if len(new_value) > 80 else "")
        return f"Updated [{id_str}] in USER.md: {preview}"

    def _update_normal(self, id_str: str, new_value: str) -> str:
        """Replace or delete an [M{N}] line in MEMORY.md."""
        content = _read_file(_MEMORY_FILE)
        lines = content.split("\n")
        pattern = re.compile(rf"^(\s*-\s*\[{re.escape(id_str)}\]\s*).*")
        found = False
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if m:
                if _is_deletion(new_value):
                    lines.pop(i)
                    found = True
                    _write_file(_MEMORY_FILE, "\n".join(lines))
                    return f"Deleted [{id_str}] from MEMORY.md."
                lines[i] = f"{m.group(1)}{new_value}"
                found = True
                break
        if not found:
            return f"Error: [{id_str}] not found in MEMORY.md."
        _write_file(_MEMORY_FILE, "\n".join(lines))
        preview = new_value[:80] + ("…" if len(new_value) > 80 else "")
        return f"Updated [{id_str}] in MEMORY.md: {preview}"


# ---------------------------------------------------------------------------
# Recall Tool
# ---------------------------------------------------------------------------

class Tool_Recall(Tool):
    name: str = "recall"
    description: str = "Read archived content or past conversation turns referenced by [MEM:] or [EVENT:] tags."
    tool_schema: dict = {
        "name": "recall",
        "description": "Retrieves previously stored information.\n\n"
                       "- archive: read a file by its [MEM:slug] tag → returns full content\n"
                       "- event: read conversation turns by [EVENT:session_id,turns] → returns messages\n"
                       "- search: keyword search across all archived sessions\n"
                       "- recent: list recent session titles\n\n"
                       "WARNING: Do NOT use to investigate tool failures or command errors. "
                       "Only use when you have a specific historical question to answer.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "archive: read file by [MEM:slug] tag. "
                                   "event: read messages by [EVENT:session_id,turns]. "
                                   "search: keyword search in archived conversations. "
                                   "recent: list recent sessions."
                },
                "query": {
                    "type": "string",
                    "description": "For mode=archive: the slug from [MEM:slug]. "
                                   "For mode=event: 'session_id,turn_start,turn_end' from [EVENT:...]. "
                                   "For mode=search: keyword to search for. "
                                   "For mode=recent: number of sessions (default 10)."
                }
            },
            "required": ["mode", "query"]
        }
    }

    def execute(self, mode: str, query: str = ""):
        if mode == "archive":
            return self._read_archived(query)
        elif mode == "event":
            return self._read_event(query)
        elif mode == "search":
            return self._search(query)
        elif mode == "recent":
            limit = int(query) if query.strip().isdigit() else 10
            return self._recent(limit)
        else:
            return f"Error: Unknown mode '{mode}'. Use: archive, event, search, or recent."

    # ── archive: read [MEM:slug] file ─────────────────────

    def _read_archived(self, slug: str) -> str:
        slug = slug.strip().replace("[MEM:", "").replace("]", "")
        if not slug:
            return "Error: slug is required."

        path = os.path.join(_ARCHIVE_DIR, f"{slug}.md")
        content = _read_file(path)
        if not content:
            return f"No archived file found for [MEM:{slug}]."

        return f"[MEM:{slug}]\n\n{content}"

    # ── event: read by turn range ─────────────────────────

    def _read_event(self, query: str) -> str:
        query = query.strip().replace("[EVENT:", "").replace("]", "")
        parts = query.split(",")
        if len(parts) < 2:
            return "Error: expected format 'session_id,turn_start[,turn_end]'."

        try:
            session_id = int(parts[0])
            turn_start = int(parts[1])
            turn_end = int(parts[2]) if len(parts) > 2 else turn_start
        except ValueError:
            return "Error: session_id and turn numbers must be integers."

        import database as db
        all_msgs = db.get_session_messages(session_id)
        if not all_msgs:
            return f"No messages found for session #{session_id}."

        # Filter by turn range
        matched = [m for m in all_msgs if turn_start <= (m.get("turn") or 0) <= turn_end]
        if not matched:
            return (f"No messages in session #{session_id} for turn range "
                    f"[{turn_start},{turn_end}].")

        turn_range = f"{turn_start}–{turn_end}" if turn_start != turn_end else str(turn_start)
        lines = [f"Session #{session_id} turn {turn_range}:", ""]
        for m in matched:
            role = m["role"].upper()
            content = (m.get("content") or "")[:1000]
            t = m.get("turn") or ""
            lines.append(f"  [turn {t}] {role}: {content}")

        return "\n".join(lines)

    # ── search: keyword in DB ─────────────────────────────

    def _search(self, keyword: str) -> str:
        if not keyword.strip():
            return "Error: query is required for search mode."

        import database as db
        sessions = db.get_recent_sessions(50)
        results = []

        for ses in sessions:
            msgs = db.get_session_messages(ses["id"])
            matches = []
            for m in msgs:
                content = m.get("content") or ""
                if keyword.lower() in content.lower():
                    role = m["role"]
                    preview = content[:300].replace("\n", " ")
                    t = m.get("turn") or ""
                    matches.append(f"  [turn {t}] [{role}] {preview}")
            if matches:
                title = ses["title"] or f"Session #{ses['id']}"
                results.append(f"Session: {title}")
                results.extend(matches[:5])
                results.append("")

        if not results:
            return f"No archived conversations found matching '{keyword}'."
        return "\n".join(results).strip()

    # ── recent: list sessions ─────────────────────────────

    def _recent(self, limit: int) -> str:
        import database as db
        sessions = db.get_recent_sessions(limit)
        if not sessions:
            return "No archived sessions yet."

        lines = ["Recent sessions:", ""]
        for s in sessions:
            lines.append(f"  #{s['id']}  {s['created_at'] or ''}  {s['title'] or 'Untitled'}")
        return "\n".join(lines)
