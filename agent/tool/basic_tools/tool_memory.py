"""Memory tools: remember, recall, and topic management for Fact Store."""

from __future__ import annotations

from .tool import Tool


# ---------------------------------------------------------------------------
# Remember
# ---------------------------------------------------------------------------


class Tool_Remember(Tool):
    name: str = "remember"
    description: str = (
        "Manually save an important fact to long-term memory. "
        "The fact will be available in future conversations via the compiled memory prompt. "
        "Topic must be a single short word. Use get_topic_list to see existing topics."
    )
    tool_schema: dict = {
        "name": "remember",
        "description": "Save a fact to long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The fact to remember. One complete, self-contained sentence."
                    ),
                },
                "topic": {
                    "type": "string",
                    "description": (
                        "Topic category. A single short word — e.g. preference, "
                        "project, behavior, workflow. Use the same word for "
                        "related facts so they group together. "
                        "Use get_topic_list to see all existing topics."
                    ),
                },
            },
            "required": ["content", "topic"],
        },
    }

    def execute(self, content: str, topic: str = "") -> str:
        try:
            from memory.fact import Fact, FactStore
            from memory.topic import TopicRegistry
            from memory.collision import detect as _cd
            from memory.collision import Duplicate, Extends, Conflict

            store = FactStore()
            tr = TopicRegistry()

            resolved, is_new, fuzzy = tr.resolve_topic(topic)
            candidates = store.get_by_topic(resolved, active=True)
            result = _cd(content, candidates)

            fact = Fact(content=content, topic=resolved, source="remember")
            if isinstance(result, Duplicate):
                return f"Already exists as [{result.existing.id}] in topic '{resolved}': {content[:80]}"

            if isinstance(result, (Extends, Conflict)):
                store.commit(fact, conflicting=result.existing)
                action = "updated" if isinstance(result, Extends) else "conflict"
            else:
                store.commit(fact)
                action = "stored"

            store.save()

            if is_new:
                return f"Created new topic '{resolved}' and {action} as [{fact.id}]: {content[:80]}"
            if fuzzy:
                return f"Topic '{topic}' matched existing '{resolved}' — {action} as [{fact.id}]: {content[:80]}"
            return f"{action} as [{fact.id}] in topic '{resolved}': {content[:80]}"

        except Exception as e:
            from logger import get_logger as _gl
            _gl(__name__).error("remember failed: %s", e, exc_info=True)
            return f"Error: failed to save fact — {e}"


# ---------------------------------------------------------------------------
# RecallFact
# ---------------------------------------------------------------------------


class Tool_RecallFact(Tool):
    name: str = "recall_fact"
    description: str = (
        "Search stored facts by keyword. Returns matching facts with their "
        "topic and importance score. Results are ranked by relevance."
    )
    tool_schema: dict = {
        "name": "recall_fact",
        "description": "Search stored facts by keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in stored facts.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    }

    def execute(self, query: str, limit: int = 5) -> str:
        try:
            from memory.fact import FactStore

            if not query.strip():
                return "Error: query is required."

            store = FactStore()
            limit = max(1, min(limit, 20))

            # Substring match on content, sorted by view_score
            q = query.lower()
            matches = [
                f for f in store.all(active=True)
                if q in f.content.lower()
            ]
            matches.sort(key=lambda f: f.view_score, reverse=True)
            matches = matches[:limit]

            if not matches:
                return f"No facts found matching '{query}'."

            lines = [f"Found {len(matches)} fact(s) matching '{query}':", ""]
            for f in matches:
                lines.append(f"  [{f.id}] ({f.topic}, score={f.view_score:.2f}) {f.content}")
            return "\n".join(lines)

        except Exception as e:
            return f"Error: search failed — {e}"


# ---------------------------------------------------------------------------
# RecallTopic
# ---------------------------------------------------------------------------


class Tool_RecallTopic(Tool):
    name: str = "recall_topic"
    description: str = "Browse all stored facts under a specific topic."
    tool_schema: dict = {
        "name": "recall_topic",
        "description": "Browse facts by topic category.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic name (use get_topic_list to see available topics).",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only show currently active facts (default true).",
                    "default": True,
                },
            },
            "required": ["topic"],
        },
    }

    def execute(self, topic: str, active_only: bool = True) -> str:
        try:
            from memory.fact import FactStore
            from memory.topic import TopicRegistry

            store = FactStore()
            tr = TopicRegistry()

            resolved, _, _ = tr.resolve_topic(topic)
            facts = store.get_by_topic(resolved, active=active_only)
            facts.sort(key=lambda f: f.view_score, reverse=True)

            if not facts:
                return f"No facts in topic '{resolved}'."

            total = store.count(active=None)
            lines = [
                f"Topic: {resolved} ({len(facts)} facts, "
                f"{sum(1 for f in facts if f.active)} active)",
                "",
            ]
            for f in facts:
                status = " " if f.active else "✗"
                if f.pinned:
                    status = "📌"
                lines.append(
                    f"  {status} [{f.id}] score={f.view_score:.2f} "
                    f"({f.created_at[:10]}) {f.content}"
                )
            lines.append("")
            lines.append(f"Total across all topics: {total} facts")
            return "\n".join(lines)

        except Exception as e:
            return f"Error: topic lookup failed — {e}"


# ---------------------------------------------------------------------------
# GetTopicList
# ---------------------------------------------------------------------------


class Tool_GetTopicList(Tool):
    name: str = "get_topic_list"
    description: str = "List all existing topics with their definitions and fact counts."
    tool_schema: dict = {
        "name": "get_topic_list",
        "description": "List all memory topics.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    }

    def execute(self) -> str:
        try:
            from memory.fact import FactStore
            from memory.topic import TopicRegistry

            store = FactStore()
            tr = TopicRegistry()
            topics = tr.list_with_counts(fact_store=store)

            if not topics:
                return "No topics yet."

            lines = [f"Topics ({len(topics)} total):", ""]
            for t in topics:
                lines.append(f"  {t['name']}  ({t['fact_count']} facts) — {t['definition']}")
            return "\n".join(lines)

        except Exception as e:
            return f"Error: topic list failed — {e}"
