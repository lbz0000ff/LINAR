# Subagent Observability and Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a B1 summary-first GUI for live DAG subagent activity and guarantee that every `submit_output`-dependent subagent produces a structured submission or explicit checkpoint before its execution budget expires.

**Architecture:** A focused `SubagentTraceRelay` converts existing subagent events into bounded, redacted, node-scoped events that the parent WebSocket forwards. Vue keeps those events inside `dagNodes` and renders them in a new trace panel. A capability-driven budget lifecycle in `Agent` reserves calls for generic `submit_output`, while `Tool_CreatePlan` owns the submission contract and checkpoint fallback.

**Tech Stack:** Python 3.10+, asyncio, pytest, Vue 3 Composition API, Node built-in test runner, Vite.

## Global Constraints

- Do not expose hidden reasoning or forward `token` / `reasoning_token` subagent streams.
- Do not send full fetched pages through WebSocket events; previews are bounded to 2,000 characters.
- Redact secrets before events leave the subagent boundary.
- Keep per-node event ordering with a monotonically increasing `sequence`.
- Keep at most 500 display events per node in the Vue client.
- Do not lower existing LLM, search, fetch, or concurrency budgets during the observability phase.
- Any normal budget exhaustion for a subagent with `submit_output` must yield a structured submission or explicit checkpoint.
- Preserve existing Deep Research fields and accept `assets` during the `artifacts` migration.
- Do not modify or stage unrelated dirty-worktree files.

---

## File Structure

- Create `agent/orchestrator/subagent_trace.py`: event filtering, redaction, typed summaries, sequence assignment, and metric accumulation.
- Create `agent/tests/test_subagent_trace.py`: relay unit tests.
- Modify `agent/tool/basic_tools/tool_plan.py`: attach relays, emit rich node states, extend `submit_output`, and checkpoint missing submissions.
- Modify `agent/agent.py`: generic `ACTIVE -> WRAP_UP -> SUBMIT_ONLY` budget lifecycle and shared stop-event preservation.
- Modify `agent/subagent.py`: load optional `finalization_hint` from template frontmatter.
- Modify `agent_types/web_researcher.md`, `agent_types/analyst.md`, and `agent_types/critic.md`: teach the generic required envelope while retaining role fields.
- Create `agent/tests/test_subagent_finalization.py`: budget lifecycle, restricted tools, partial submission, and checkpoint tests.
- Create `gui/src/utils/subagentTrace.js`: pure event-to-node state reducer.
- Create `gui/src/utils/subagentTrace.test.js`: Node unit tests for routing, ordering, and retention.
- Create `gui/src/components/RightPanel/SubagentTracePanel.vue`: B1 node list and summary-first detail timeline.
- Modify `gui/src/App.vue`: route `subagent_event` into DAG state.
- Modify `gui/src/components/RightPanel.vue`: mount the trace panel.
- Modify `gui/package.json`: add the built-in unit-test command.

---

### Task 1: Node-scoped trace relay

**Files:**
- Create: `agent/orchestrator/subagent_trace.py`
- Create: `agent/tests/test_subagent_trace.py`

**Interfaces:**
- Produces: `SubagentTraceRelay(parent_emit: Callable[[dict], None], node_id: str, agent_type: str | None)`.
- Produces: `SubagentTraceRelay.__call__(event: dict) -> None`.
- Produces: `SubagentTraceRelay.snapshot_metrics() -> dict[str, Any]`.
- Consumes: `logger.redact_sensitive(value: str) -> str`.

- [ ] **Step 1: Write failing relay tests**

Add tests that send `token`, `tool_call`, `tool_result`, `usage`, and `error` events. Assert token events are absent; retained events use `type="subagent_event"`, the correct `node_id`, sequences `[1, 2, 3, 4]`, redacted secrets, a result preview no longer than 2,000 characters, and metrics with one LLM/tool/search/fetch count as appropriate.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest agent/tests/test_subagent_trace.py -q`

Expected: collection fails because `orchestrator.subagent_trace` does not exist.

- [ ] **Step 3: Implement the minimal relay**

Implement constants `FORWARDED_EVENT_TYPES`, `PREVIEW_LIMIT = 2000`, and a callable relay. Parse JSON tool arguments when possible, summarize `web_search`, `web_fetch`, and `submit_output`, use a generic fallback for other tools, and increment metrics from `start`, `tool_call`, and tool-result events. Store pending tool start timestamps by tool-call id so duration is included when available.

- [ ] **Step 4: Run relay tests and existing redaction tests**

Run: `pytest agent/tests/test_subagent_trace.py agent/tests/test_log_redaction.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the relay**

Run:

```powershell
git add agent/orchestrator/subagent_trace.py agent/tests/test_subagent_trace.py
git commit -m "feat: add node-scoped subagent trace relay"
```

---

### Task 2: Wire trace events into DAG execution

**Files:**
- Modify: `agent/tool/basic_tools/tool_plan.py`
- Modify: `agent/tests/test_plan_subagent_limits.py`

**Interfaces:**
- Consumes: `SubagentTraceRelay` from Task 1.
- Produces: enriched `dag_node_start`, `subagent_event`, and `dag_node_complete` parent events.

- [ ] **Step 1: Add failing Tool_CreatePlan integration tests**

Extend the fake subagent so `process_with_llm()` emits a `tool_call`, `tool_result`, and `usage` event. Assert the parent receives node-scoped events and `dag_node_complete.data` contains `status`, `metrics`, and `stop_reason`. Add two independent nodes and assert their event sequences both start at one.

- [ ] **Step 2: Run the integration tests and verify RED**

Run: `pytest agent/tests/test_plan_subagent_limits.py -q`

Expected: assertions fail because subagent events are still discarded.

- [ ] **Step 3: Attach the relay**

After each subagent is created, replace its no-op emitter with a relay bound to the parent and node. Include agent type and initial metric fields in `dag_node_start`. On return, include relay metrics, elapsed duration, explicit terminal status, and stop reason in `dag_node_complete`.

- [ ] **Step 4: Run focused tests**

Run: `pytest agent/tests/test_plan_subagent_limits.py agent/tests/test_subagent_trace.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit DAG wiring**

Run:

```powershell
git add agent/tool/basic_tools/tool_plan.py agent/tests/test_plan_subagent_limits.py
git commit -m "feat: expose subagent execution events"
```

---

### Task 3: Vue trace state reducer

**Files:**
- Create: `gui/src/utils/subagentTrace.js`
- Create: `gui/src/utils/subagentTrace.test.js`
- Modify: `gui/package.json`
- Modify: `gui/src/App.vue`

**Interfaces:**
- Produces: `applySubagentEvent(nodes: object, payload: object, maxEvents?: number) -> object`.
- Produces: `applyDagNodeStart(nodes: object, data: object) -> object`.
- Produces: `applyDagNodeComplete(nodes: object, data: object) -> object`.

- [ ] **Step 1: Write failing reducer tests**

Use `node:test` and `node:assert/strict`. Assert events route by `node_id`, invalid node ids do not mutate state, out-of-order events are sorted by sequence and set `sequenceGap`, metrics update from backend snapshots, and 501 inserted events retain the newest 500 with `omittedEvents === 1`.

- [ ] **Step 2: Add and run the unit-test script**

Add `"test:unit": "node --test src/utils/subagentTrace.test.js"` to `gui/package.json`.

Run from `gui`: `npm run test:unit`

Expected: failure because `subagentTrace.js` does not exist.

- [ ] **Step 3: Implement the immutable reducers**

Return new node and map objects on every update so Vue reactivity is reliable. Initialize missing nodes only for valid `dag_node_start`; ignore orphan `subagent_event` payloads. Preserve dependency fields, result text, metrics, events, omitted count, and terminal state.

- [ ] **Step 4: Route events in App.vue**

Add `subagent_event` to `scopedTypes`. Replace inline DAG mutations with reducer calls for `dag_node_start` and `dag_node_complete`, and add a `subagent_event` branch.

- [ ] **Step 5: Run unit tests and production build**

Run from `gui`:

```powershell
npm run test:unit
npm run build
```

Expected: unit tests pass and Vite exits successfully.

- [ ] **Step 6: Commit reducer wiring**

Run:

```powershell
git add gui/package.json gui/src/utils/subagentTrace.js gui/src/utils/subagentTrace.test.js gui/src/App.vue
git commit -m "feat: track subagent events in the GUI"
```

---

### Task 4: B1 summary-first trace panel

**Files:**
- Create: `gui/src/components/RightPanel/SubagentTracePanel.vue`
- Modify: `gui/src/components/RightPanel.vue`
- Modify: `gui/src/components/RightPanel/PlanProgress.vue`

**Interfaces:**
- Consumes: DAG nodes containing `events`, `metrics`, `status`, `agentType`, and `result`.
- Produces: a node selector and expandable event-detail timeline inside the right panel.

- [ ] **Step 1: Implement the B1 component**

Render a node list with status, elapsed time, LLM/search/fetch/submission counts, and selected state. Render the selected node timeline with timestamp, tool/action name, status, duration, and short summary. Expand a row to show sanitized `detail` JSON and artifact path. Render an omitted-event notice and sequence-gap warning.

- [ ] **Step 2: Preserve dependency overview**

Keep `PlanProgress` as the compact stage/dependency diagram and mount `SubagentTracePanel` immediately beneath it when any node has trace events. Do not duplicate trace events into chat messages.

- [ ] **Step 3: Adjust right-panel sizing**

Change the initial width to 480 pixels, retain resize support, and allow a 720-pixel maximum so the two-column B1 view remains readable. Add a media rule inside the trace component that stacks list and detail below 420 pixels.

- [ ] **Step 4: Verify build and inspect in Electron GUI**

Run from `gui`: `npm run test:unit` and `npm run build`.

Then launch `python linar.py --gui`, execute a two-node synthetic plan, and confirm node selection, live updates, expandable details, and main-chat isolation.

- [ ] **Step 5: Commit the panel**

Run:

```powershell
git add gui/src/components/RightPanel/SubagentTracePanel.vue gui/src/components/RightPanel.vue gui/src/components/RightPanel/PlanProgress.vue
git commit -m "feat: add subagent trace panel"
```

---

### Task 5: Generic submit_output envelope

**Files:**
- Modify: `agent/tool/basic_tools/tool_plan.py`
- Modify: `agent/subagent.py`
- Modify: `agent_types/web_researcher.md`
- Modify: `agent_types/analyst.md`
- Modify: `agent_types/critic.md`
- Create: `agent/tests/test_subagent_finalization.py`

**Interfaces:**
- Produces required submission fields `status: Literal["completed", "partial", "blocked"]` and `summary: str`.
- Produces optional `unresolved: list[str]`, `artifacts: list[dict]`, and `error: str | None`.
- Preserves all existing research extension fields and accepts legacy `assets`.
- Produces optional template metadata `finalization_hint: str`.

- [ ] **Step 1: Write failing submission compatibility tests**

Assert a generic completed submission records status and summary; a partial research submission preserves findings and maps legacy `assets` into `artifacts` without losing `assets`; missing required status or summary returns an error and does not set `_submission`; all three installed research templates contain the required generic handoff instruction.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest agent/tests/test_subagent_finalization.py -q`

Expected: failures because the generic envelope is absent.

- [ ] **Step 3: Extend SubmitOutputTool atomically**

Add the generic fields to the JSON schema and validate them in `execute()`. Keep role-specific arrays optional. Store `artifacts` and the compatibility `assets` view. Return a normal success string only after validation.

- [ ] **Step 4: Extend template loading and templates**

Load `finalization_hint` from frontmatter. Update all three templates to call `submit_output` with `status` and `summary`, and give each a concise role-specific finalization hint.

- [ ] **Step 5: Run submission and Deep Research tests**

Run:

```powershell
pytest agent/tests/test_subagent_finalization.py eval/test_deep_research_bench_harness.py eval/test_deep_research.py -q
```

Expected: all compatible tests pass.

- [ ] **Step 6: Commit the generic contract**

Run:

```powershell
git add agent/tool/basic_tools/tool_plan.py agent/subagent.py agent_types agent/tests/test_subagent_finalization.py
git commit -m "feat: generalize DAG subagent submissions"
```

---

### Task 6: Capability-driven budget finalization

**Files:**
- Modify: `agent/agent.py`
- Modify: `agent/tool/basic_tools/tool_plan.py`
- Modify: `agent/tests/test_subagent_finalization.py`
- Modify: `agent/tests/test_agent_limits.py`

**Interfaces:**
- Produces agent attributes `submission_required: bool`, `submission_reserve: int`, `wrap_up_calls: int`, `finalization_hint: str`, and `budget_state: str`.
- Produces budget events with state, call number, remaining calls, and reserved calls.

- [ ] **Step 1: Write failing lifecycle tests**

Use a fake streaming LLM and tools. Assert a submission-dependent agent emits `WRAP_UP` once, enters `SUBMIT_ONLY` with only `submit_output` visible to the LLM, stops immediately after `_submission` is recorded, and does not emit the ordinary hard-limit notice. Assert an agent without `submit_output` retains existing main-agent behavior. Assert a parent-provided stop event is not replaced.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest agent/tests/test_subagent_finalization.py agent/tests/test_agent_limits.py -q`

Expected: lifecycle assertions fail against the current abrupt limit behavior.

- [ ] **Step 3: Implement lifecycle transitions**

Before each model call, compute remaining calls. For submission-dependent agents, inject the generic WRAP_UP message once when remaining calls equal `submission_reserve + wrap_up_calls`; emit the budget-state event; when remaining calls are within the reserve, inject SUBMIT_ONLY once and replace `llm.tools` with only `submit_output`. Break as soon as `_submission` exists. Preserve an injected `stop_event` instead of creating a fresh one.

- [ ] **Step 4: Configure plan subagents**

After injecting `submit_output`, set `submission_required = True`, copy any template `finalization_hint`, and derive conservative defaults without lowering the existing maximum: `submission_reserve = 2`, `wrap_up_calls = 2`. Attach the values to trace node start data.

- [ ] **Step 5: Add explicit checkpoint fallback**

When `process_with_llm()` returns without `_submission`, create a bounded checkpoint with generic `status="checkpointed"`, summary, unresolved reason, recent tool metadata, and artifact paths. Emit `dag_node_complete.status="CHECKPOINTED"`; do not merge checkpoint content into verified `research_state` findings.

- [ ] **Step 6: Run focused and limit regression tests**

Run:

```powershell
pytest agent/tests/test_subagent_finalization.py agent/tests/test_agent_limits.py agent/tests/test_plan_subagent_limits.py -q
```

Expected: all tests pass, including existing main-agent limit behavior.

- [ ] **Step 7: Commit budget finalization**

Run:

```powershell
git add agent/agent.py agent/tool/basic_tools/tool_plan.py agent/tests/test_subagent_finalization.py agent/tests/test_agent_limits.py
git commit -m "feat: reserve subagent submission budget"
```

---

### Task 7: Integrated verification and baseline run

**Files:**
- Modify only if verification exposes a defect in files already listed above.

**Interfaces:**
- Consumes all prior tasks.
- Produces fresh backend, frontend, and manual GUI verification evidence.

- [ ] **Step 1: Run backend regression suite for touched systems**

Run:

```powershell
pytest agent/tests/test_subagent_trace.py agent/tests/test_subagent_finalization.py agent/tests/test_plan_subagent_limits.py agent/tests/test_agent_limits.py agent/tests/test_ws_permissions.py eval/test_deep_research_bench_harness.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend verification**

Run from `gui`:

```powershell
npm run test:unit
npm run build
```

Expected: unit tests and production build pass.

- [ ] **Step 3: Run a controlled two-node DAG**

Use one researcher node and one dependent analyst node with the existing high limits. Verify the GUI shows node-local tool activity and that the analyst receives the researcher's structured submission.

- [ ] **Step 4: Record the baseline metrics**

Record node duration, LLM calls, search calls, fetch calls, submission state, sources submitted, and findings submitted. Do not introduce lower budgets or source-quality gates in this implementation.

- [ ] **Step 5: Review the final diff boundary**

Run `git status --short` and `git diff HEAD~6 --stat`. Confirm unrelated pre-existing dirty files remain unstaged and unchanged by these tasks.

