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
    relay({"type": "usage", "data": {"prompt_tokens": 123}})

    assert [event["data"]["sequence"] for event in emitted] == [1, 2]
    assert all(event["type"] == "subagent_event" for event in emitted)
    assert all(event["data"]["node_id"] == "wave1_income" for event in emitted)
    assert all(event["data"]["agent_type"] == "web_researcher" for event in emitted)
    assert relay.snapshot_metrics()["llm_calls"] == 1


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
        "result": {
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
