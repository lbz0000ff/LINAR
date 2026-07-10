# Subagent Observability and Finalization Design

Date: 2026-07-10

## Summary

LINAR currently exposes only DAG node start and completion events. Events produced
inside a subagent are discarded, which makes long Deep Research runs opaque and
prevents evidence-based tuning of search, fetch, concurrency, and model-call
budgets. The existing `max_llm_calls` behavior also stops an agent before another
model call without guaranteeing that work is handed to downstream nodes.

This design adds an expandable GUI trace for every DAG node and introduces a
generic submission lifecycle for every subagent that depends on
`submit_output`. The first implementation phase is observational: it forwards
and displays subagent activity without reducing current budgets. Budget
convergence and forced submission are added only after a baseline trace has
been collected.

## Goals

- Show what every concurrent subagent actually does while a DAG is running.
- Keep events associated with the correct DAG node and in node-local order.
- Show concise summaries by default and expandable details on demand.
- Surface model calls, tool calls, durations, failures, and submission state.
- Prevent normal budget exhaustion from silently discarding completed work.
- Make submission finalization reusable for any DAG subagent, not only research
  agents.
- Preserve the current FSM, DAG executor, subagent templates, and structured
  `research_state.json` flow.

## Non-goals

- Automatically score source quality in the first phase.
- Add search, fetch, or concurrency limits before a trace baseline exists.
- Expose hidden chain-of-thought or stream subagent tokens into the main chat.
- Replace LINAR orchestration with LangGraph or another workflow framework.
- Persist full fetched page bodies in WebSocket events.
- Redesign the final report or DeepResearch Bench adapter in this change.

## Current Problems

### Opaque subagent execution

`agent_factory.create_agent()` currently assigns a no-op emitter to every
subagent. The subagent internally emits tool, usage, completion, and error
events, but the parent receives only `dag_node_start` and `dag_node_complete`.
The GUI therefore cannot explain queries, fetched URLs, retries, failures, model
rounds, or why a node stopped.

### Abrupt budget exhaustion

`Agent.process_with_llm()` stops before another model call once
`max_llm_calls` is exceeded. It appends a notice but does not reserve a call for
finalization. If a DAG subagent has not called `submit_output`, `Tool_CreatePlan`
falls back to recent agent text or a small, truncated selection of tool results.
Useful work may never enter structured state or reach downstream nodes.

### Research-specific submission schema

`SubmitOutputTool` is injected into every DAG subagent, but its schema currently
contains only fields for `web_researcher`, `analyst`, and `critic`. A generic
submission lifecycle also requires a generic outer result contract.

## User Experience

The approved GUI layout is **B1: node list plus summary-first detail panel**.

### Node list

The left side shows all DAG nodes and compact live metrics:

```text
Data definitions · web_researcher
WRAP_UP · 03:42
LLM 9/12 · search 3 · fetch 11 · findings pending
```

Selecting a node changes the right-side detail panel. Concurrent node events do
not appear in the main chat timeline.

### Detail timeline

The right side shows concise event rows:

```text
09:31:02  web_search  10 candidates · 1.2s
09:31:05  web_fetch   accepted · 14k chars · 8.4s
09:31:14  web_fetch   status 200 · 3.3k chars
09:31:20  submit      partial · 5 findings · 3 sources
```

Expanding a row reveals sanitized arguments, candidate URLs, short result
previews, error details, and artifact paths. Full fetched bodies remain in
workspace files and are not sent through WebSocket events.

### Node states

The GUI distinguishes:

- `ACTIVE`
- `WRAP_UP`
- `SUBMIT_ONLY`
- `SUBMITTED`
- `CHECKPOINTED`
- `FAILED`
- `STOPPED`

`CHECKPOINTED` means useful activity occurred but a valid structured submission
was not produced. It must not be displayed as successful completion.

## Backend Architecture

### Subagent trace relay

A reusable trace relay wraps a subagent's existing event emitter. It is created
for each DAG node and forwards selected events through the parent agent:

```python
sub_agent.emit = SubagentTraceRelay(
    parent_emit=parent_agent.emit,
    node_id=node_id,
    agent_type=agent_type,
)
```

The relay forwards lifecycle, usage, tool-call, tool-result, error, and
completion events. It drops token, reasoning-token, ready, and other high-rate
events that do not help audit execution.

Every forwarded event uses a common envelope:

```json
{
  "type": "subagent_event",
  "data": {
    "node_id": "wave1_income",
    "agent_type": "web_researcher",
    "sequence": 7,
    "timestamp": 1783680000,
    "event_type": "tool_result",
    "tool_name": "web_fetch",
    "status": "success",
    "summary": {},
    "detail": {}
  }
}
```

`sequence` is monotonically increasing within one node. Global event ordering is
not required because DAG nodes execute concurrently.

The relay must preserve the parent-provided `stop_event`. The current
`process_with_llm()` implementation replaces that event at startup; phase 1
must remove that replacement for injected events or otherwise retain the shared
event so user interruption still propagates into running subagents.

### Event normalization

The relay creates typed summaries instead of asking the Vue client to parse
arbitrary Python strings.

For `web_search`, the summary includes the query, backend, result count, and
duration. Detail includes bounded title, URL, and snippet previews.

For `web_fetch`, the summary includes URL, status code, content length,
artifact path, truncated flag, and duration. Detail includes only a bounded
preview.

For `submit_output`, the summary includes generic submission status plus counts
of artifacts, unresolved items, findings, sources, gaps, and verdicts when those
fields exist.

Unknown tools receive a generic summary containing name, success state,
duration, sanitized arguments, and a bounded result preview.

### Metrics

Each node accumulates objective metrics:

```json
{
  "llm_calls": 0,
  "tool_calls": 0,
  "search_calls": 0,
  "fetch_calls": 0,
  "findings_submitted": 0,
  "sources_submitted": 0,
  "started_at": 0,
  "duration_ms": 0,
  "stop_reason": null
}
```

Source utilization is intentionally excluded from the first phase because it
cannot be known reliably until report claims are linked back to source or claim
identifiers.

### Event size and security

- Token and reasoning streams are not forwarded.
- Tool arguments and results pass through centralized secret redaction.
- Result previews use a fixed character limit.
- Complete fetched pages remain on disk.
- A node retains at most 500 display events in the Vue client.
- API keys, authorization headers, passwords, and MCP secrets must never appear
  in event summaries or details.

## Generic Submission Contract

Every DAG subagent with a `submit_output` tool uses a generic outer envelope:

```json
{
  "status": "completed",
  "summary": "Concise handoff for downstream nodes.",
  "unresolved": [],
  "artifacts": [],
  "error": null
}
```

`status` is one of `completed`, `partial`, or `blocked`. `status` and `summary`
are required. `unresolved`, `artifacts`, and `error` are generic optional fields.

Existing research fields remain optional extensions:

- `findings`
- `gaps`
- `sources`
- `contradictions`
- `verdicts`
- `coverage_score`
- `next_wave_suggestions`
- `overall_assessment`
- `assets` during compatibility migration

`artifacts` becomes the generic name; `assets` remains accepted while existing
Deep Research state and templates migrate.

Making `status` and `summary` required is an atomic migration: the tool schema,
`web_researcher`, `analyst`, and `critic` templates, result collection, state
merge logic, and compatibility tests must change together. The runtime must not
publish a required schema that the installed templates have not yet been taught
to satisfy.

Downstream nodes always receive the generic fields. They consume role-specific
extensions only when they understand them.

## Generic Budget Finalization

Budget behavior is capability-driven:

```python
requires_submission = "submit_output" in sub_agent.tools
```

It is not selected by `agent_type` or by research-specific names.

### Lifecycle

```text
ACTIVE
  -> WRAP_UP
  -> SUBMIT_ONLY
  -> SUBMITTED

SUBMIT_ONLY
  -> CHECKPOINTED  (only when valid submission still fails)
```

### WRAP_UP prompt

```text
You are approaching the execution budget for this subtask.

Stop starting new branches of work. Finish only work that is already in
progress, consolidate the valid results you have obtained, identify anything
that remains unresolved, and prepare a structured handoff.

A partial but accurate result is acceptable. Do not discard completed work
because the full task could not be finished.

You have {remaining_calls} model calls remaining, including
{submission_reserve} calls reserved for submission.
```

### SUBMIT_ONLY prompt

```text
The remaining execution budget is reserved for handoff.

Do not start new work and do not call any tool except submit_output. Call
submit_output now using the best validated results currently available.

If the task is incomplete, submit it with status="partial" and explicitly list
the unresolved items. If progress is blocked, use status="blocked" and explain
the blocking condition.

Do not merely describe what you would submit. You must call submit_output.
```

In `SUBMIT_ONLY`, the LLM sees only `submit_output`. A subagent template may add
a short `finalization_hint`, but it cannot replace or redefine the generic
lifecycle.

Examples of optional hints:

- Research: preserve URLs and confidence for every finding.
- Code: include changed files, verification results, and remaining failures.
- File processing: include produced paths and skipped inputs.

### Checkpoint fallback

If reserved submission calls fail, the runtime records a non-authoritative
checkpoint containing node identity, status, stop reason, visited artifacts,
the last bounded agent output, and recoverable bounded tool-result metadata.
Checkpoint data is not merged as verified findings or treated as a successful
node result.

The invariant is:

> Normal budget exhaustion must produce a structured submission or an explicit
> checkpoint; it must never silently discard completed work.

## Frontend Architecture

`App.vue` remains the centralized WebSocket event router. It handles
`subagent_event` and updates the corresponding node by `node_id`. Rendering is
delegated to a focused component hierarchy:

```text
SubagentTracePanel
  NodeList
  NodeMetrics
  EventTimeline
  EventDetail
```

The component does not add trace events to the main `messages` collection.
Selecting another node changes only the detail pane. Events beyond the client
limit are evicted from display in oldest-first order with a visible count of
omitted events.

## Failure Handling

- Invalid or missing `node_id`: ignore the event and log a warning.
- Duplicate or out-of-order sequence: retain the newest valid state and mark the
  timeline as having a sequence gap.
- Malformed tool arguments: show a bounded raw preview rather than crashing.
- WebSocket disconnect: running execution continues; the initial version does
  not guarantee replay of missed trace events.
- Subagent exception: emit `FAILED` with a sanitized error and duration.
- User interruption: emit `STOPPED`, preserve any successful prior submission,
  and otherwise create a checkpoint. The parent and subagent must still share
  the same stop event throughout execution.
- Budget exhaustion: transition through submission reserve; never report
  ordinary completion without a submission.

## Delivery Phases

### Phase 1: Observability baseline

- Add the trace relay and typed event summaries.
- Add B1 GUI node list and detail timeline.
- Display existing limits and remaining calls without lowering them.
- Run one representative Deep Research task and inspect real trajectories.

### Phase 2: Generic submission contract

- Add required generic fields to `submit_output`.
- Preserve existing research fields and `assets` compatibility.
- Update DAG result collection and node completion states.

### Phase 3: Budget finalization

- Add `WRAP_UP` and `SUBMIT_ONLY` transitions.
- Reserve calls for submission.
- Restrict tools during `SUBMIT_ONLY`.
- Add explicit checkpoint fallback.

### Phase 4: Evidence-based optimization

- Use traces to choose model-call, search, fetch, and concurrency budgets.
- Add source validation, URL deduplication, and relevance gates separately.
- Compare runtime, source quality, report quality, and structured-result recovery
  against the Phase 1 baseline.

## Testing

### Backend

- Events include the correct `node_id` and `agent_type`.
- Per-node sequence numbers are monotonic under concurrent execution.
- Token and reasoning events are filtered.
- Tool summaries are typed and bounded.
- Secret redaction applies to arguments, results, and errors.
- Exceptions and interruptions produce the correct terminal node states.
- Generic completed, partial, and blocked submissions are accepted.
- Existing research submissions remain compatible.
- `SUBMIT_ONLY` exposes only `submit_output`.
- Budget exhaustion produces a submission or checkpoint.
- Successful partial submissions reach downstream nodes and structured state.

### Frontend

- Concurrent nodes update independently.
- Selecting a node displays only its events.
- Event details expand and collapse without altering the main chat.
- The 500-event display limit works and reports omitted events.
- Malformed details do not crash rendering.
- All terminal states are visually distinct.
- Existing main-agent tool rendering remains unchanged.
- The production Vue build succeeds.

## Success Criteria

- A user can explain every subagent's queries, tool calls, outputs, failures,
  duration, model-call usage, and terminal state from the GUI.
- Concurrent subagent events never appear under the wrong node.
- The GUI remains responsive during a representative two-wave research run.
- No full fetched page or secret is sent in a trace event.
- No DAG subagent loses all useful work solely because its normal execution
  budget expires before an unreserved submission call.
- Existing Deep Research structured submissions and report generation remain
  compatible during migration.
