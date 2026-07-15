import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.subagent_trace import PREVIEW_LIMIT, SubagentTraceRelay


def test_relay_filters_stream_tokens_and_scopes_kept_events():
    emitted = []
    relay = SubagentTraceRelay(emitted.append, "wave1_income", "web_researcher")

    relay({"type": "token", "data": "hidden streaming text"})
    relay({"type": "reasoning_token", "data": "hidden reasoning"})
    relay({"type": "start"})
    relay({
        "type": "usage",
        "data": {"prompt_tokens": 123, "completion_tokens": 1, "total_tokens": 124},
    })
    relay({
        "type": "usage",
        "data": {"prompt_tokens": 123, "completion_tokens": 2, "total_tokens": 125},
    })
    relay({"type": "done"})

    assert [event["data"]["sequence"] for event in emitted] == [1, 2]
    assert [event["data"]["event_type"] for event in emitted] == ["start", "done"]
    assert all(event["type"] == "subagent_event" for event in emitted)
    assert all(event["data"]["node_id"] == "wave1_income" for event in emitted)
    assert all(event["data"]["agent_type"] == "web_researcher" for event in emitted)
    assert relay.snapshot_metrics() == {
        "llm_calls": 1,
        "tool_calls": 0,
        "search_calls": 0,
        "fetch_calls": 0,
        "findings_submitted": 0,
        "sources_submitted": 0,
        "prompt_tokens": 123,
        "completion_tokens": 2,
        "total_tokens": 125,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "reasoning_tokens": 0,
    }


def test_relay_accumulates_final_usage_across_llm_calls():
    relay = SubagentTraceRelay(lambda _event: None, "node-a", "researcher")

    relay({"type": "start"})
    relay({
        "type": "usage",
        "data": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 75,
            "prompt_cache_miss_tokens": 25,
            "reasoning_tokens": 8,
        },
    })
    relay({"type": "done"})
    relay({"type": "start"})
    relay({
        "type": "usage",
        "data": {
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "total_tokens": 60,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 10,
            "reasoning_tokens": 3,
        },
    })
    relay({"type": "done"})

    metrics = relay.snapshot_metrics()
    assert metrics["prompt_tokens"] == 150
    assert metrics["completion_tokens"] == 30
    assert metrics["total_tokens"] == 180
    assert metrics["prompt_cache_hit_tokens"] == 115
    assert metrics["prompt_cache_miss_tokens"] == 35
    assert metrics["reasoning_tokens"] == 11


def test_relay_summarizes_tools_redacts_secrets_and_bounds_preview():
    emitted = []
    relay = SubagentTraceRelay(emitted.append, "node-a", "researcher")
    secret = "sk-live-1234567890"

    relay({
        "type": "tool_call",
        "name": "web_search",
        "id": "search-1",
        "arguments": '{"query":"robotics", "api_key":"%s"}' % secret,
    })
    relay({
        "type": "tool_result",
        "name": "web_search",
        "id": "search-1",
        "result": {
            "query": "robotics",
            "backend": "tavily",
            "total": 1,
            "results": [{"title": "Paper", "url": "https://example.com", "snippet": "useful"}],
        },
    })
    relay({
        "type": "tool_call",
        "name": "web_fetch",
        "id": "fetch-1",
        "arguments": '{"url":"https://example.com"}',
    })
    relay({
        "type": "tool_result",
        "name": "web_fetch",
        "id": "fetch-1",
        "result": "web_fetch saved full markdown to web_fetch/example.md",
        "raw_result": {
            "url": "https://example.com",
            "status_code": 200,
            "content_length": 5000,
            "content_file": "web_fetch/example.md",
            "truncated": True,
            "content": "x" * (PREVIEW_LIMIT + 500) + " api_key=" + secret,
        },
    })

    payloads = [event["data"] for event in emitted]
    assert [payload["sequence"] for payload in payloads] == [1, 2, 3, 4]
    assert secret not in str(payloads)
    assert "[REDACTED]" in str(payloads)
    assert payloads[1]["summary"] == {
        "query": "robotics",
        "backend": "tavily",
        "result_count": 1,
    }
    assert payloads[3]["summary"]["content_length"] == 5000
    assert len(payloads[3]["detail"]["preview"]) <= PREVIEW_LIMIT
    assert relay.snapshot_metrics()["tool_calls"] == 2
    assert relay.snapshot_metrics()["search_calls"] == 1
    assert relay.snapshot_metrics()["fetch_calls"] == 1


def test_relay_records_structured_submission_counts():
    relay = SubagentTraceRelay(lambda _event: None, "node-a", "researcher")

    relay.record_submission({
        "findings": [{"text": "one"}, {"text": "two"}],
        "sources": ["https://one.example", "https://two.example"],
    })

    metrics = relay.snapshot_metrics()
    assert metrics["findings_submitted"] == 2
    assert metrics["sources_submitted"] == 2


def test_relay_redacts_common_header_and_oauth_secret_keys():
    emitted = []
    relay = SubagentTraceRelay(emitted.append, "node-a", "researcher")

    relay({
        "type": "tool_call",
        "name": "mcp_call",
        "id": "secret-1",
        "arguments": '{"x-api-key":"sk-live-1234567890","client_secret":"oauth-secret-value","access_token":"access-token-value","github_token":"github-token-value","prompt_tokens":123}',
    })

    text = str(emitted)
    assert "sk-live-1234567890" not in text
    assert "oauth-secret-value" not in text
    assert "access-token-value" not in text
    assert "github-token-value" not in text
    assert text.count("[REDACTED]") >= 4
    assert emitted[0]["data"]["summary"]["arguments"]["prompt_tokens"] == 123


def test_relay_redacts_bare_api_key_tool_results():
    emitted = []
    relay = SubagentTraceRelay(emitted.append, "node-a", "researcher")

    relay({"type": "tool_result", "name": "mcp_call", "id": "bare", "result": "sk-live-1234567890"})

    assert "sk-live-1234567890" not in str(emitted)
    assert "[REDACTED]" in str(emitted)
