import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  applyDagNodeComplete,
  applyDagNodeStart,
  applySubagentEvent,
  appendDagPlan,
  formatTokenCount,
  sumTokenMetrics,
  tokenCacheHitRate,
  updateDagPlan,
} from './subagentTrace.js'

test('appends DAG plans without replacing earlier traces', () => {
  const first = appendDagPlan([], { id: 'wave-1', goal: 'Broad search' })
  const second = appendDagPlan(first, { id: 'wave-2', goal: 'Fill gaps' })

  assert.equal(first.length, 1)
  assert.deepEqual(second.map(plan => plan.id), ['wave-1', 'wave-2'])
  assert.equal(second[0].goal, 'Broad search')
  assert.deepEqual(second[0].nodes, {})
})

test('updates only the selected DAG plan', () => {
  const plans = [
    { id: 'wave-1', goal: 'Broad search', nodes: { old: { id: 'old' } }, status: 'COMPLETED' },
    { id: 'wave-2', goal: 'Fill gaps', nodes: {}, status: 'ACTIVE' },
  ]
  const updated = updateDagPlan(plans, 'wave-2', plan => ({
    ...plan,
    nodes: applyDagNodeStart(plan.nodes, { id: 'new', description: 'Research gap' }),
  }))

  assert.equal(updated[0], plans[0])
  assert.equal(updated[1].nodes.new.description, 'Research gap')
  assert.deepEqual(plans[1].nodes, {})
})

test('routes events to the matching node without mutating prior state', () => {
  const initial = applyDagNodeStart({}, { id: 'one', description: 'First' })
  const updated = applySubagentEvent(initial, {
    node_id: 'one', sequence: 1, event_type: 'tool_call', metrics: { tool_calls: 1 },
  })

  assert.notEqual(updated, initial)
  assert.equal(initial.one.events.length, 0)
  assert.equal(updated.one.events.length, 1)
  assert.equal(updated.one.metrics.tool_calls, 1)
  assert.equal(applySubagentEvent(updated, { node_id: 'missing', sequence: 1 }), updated)
})

test('sorts out-of-order events and marks a sequence gap', () => {
  let nodes = applyDagNodeStart({}, { id: 'one' })
  nodes = applySubagentEvent(nodes, { node_id: 'one', sequence: 2 })
  nodes = applySubagentEvent(nodes, { node_id: 'one', sequence: 1 })

  assert.deepEqual(nodes.one.events.map(event => event.sequence), [1, 2])
  assert.equal(nodes.one.sequenceGap, true)
})

test('retains only the newest configured events and counts omissions', () => {
  let nodes = applyDagNodeStart({}, { id: 'one' })
  for (let sequence = 1; sequence <= 501; sequence += 1) {
    nodes = applySubagentEvent(nodes, { node_id: 'one', sequence }, 500)
  }

  assert.equal(nodes.one.events.length, 500)
  assert.equal(nodes.one.events[0].sequence, 2)
  assert.equal(nodes.one.omittedEvents, 1)
})

test('applies explicit terminal status and completion metadata', () => {
  const initial = applyDagNodeStart({}, { id: 'one' })
  const updated = applyDagNodeComplete(initial, {
    id: 'one', status: 'CHECKPOINTED', result: 'partial', stop_reason: 'budget', duration_ms: 42,
  })

  assert.equal(updated.one.status, 'CHECKPOINTED')
  assert.equal(updated.one.stopReason, 'budget')
  assert.equal(updated.one.durationMs, 42)
})

test('sums per-node token metrics into DAG totals', () => {
  const totals = sumTokenMetrics({
    one: { metrics: { prompt_tokens: 1000, completion_tokens: 200, prompt_cache_hit_tokens: 750 } },
    two: { metrics: { prompt_tokens: 500, completion_tokens: 100, prompt_cache_hit_tokens: 250, prompt_cache_miss_tokens: 250 } },
  })

  assert.equal(totals.prompt_tokens, 1500)
  assert.equal(totals.completion_tokens, 300)
  assert.equal(totals.prompt_cache_hit_tokens, 1000)
  assert.equal(totals.prompt_cache_miss_tokens, 250)
  assert.equal(tokenCacheHitRate(totals), '80.0%')
  assert.equal(formatTokenCount(1500), '1.5K')
})

test('trace event rows cannot shrink instead of overflowing the scroll container', () => {
  const componentPath = fileURLToPath(new URL('../components/RightPanel/SubagentTracePanel.vue', import.meta.url))
  const source = readFileSync(componentPath, 'utf8')

  assert.match(source, /\.trace-events\s*\{[^}]*overflow-y:\s*auto/s)
  assert.match(source, /\.trace-event\s*\{[^}]*flex:\s*0\s+0\s+auto/s)
})
