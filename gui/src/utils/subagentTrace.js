export const DEFAULT_MAX_EVENTS = 500

export function appendDagPlan(plans, plan) {
  return [...plans, {
    id: plan.id,
    goal: plan.goal || '',
    nodes: plan.nodes || {},
    status: plan.status || 'ACTIVE',
    startedAt: plan.startedAt || Date.now(),
    completedAt: plan.completedAt || null,
  }]
}

export function updateDagPlan(plans, planId, updater) {
  return plans.map(plan => plan.id === planId ? updater(plan) : plan)
}

function normalizeNode(data = {}, existing = {}) {
  return {
    id: data.id || existing.id || '',
    description: data.description ?? existing.description ?? '',
    hint: data.hint ?? existing.hint ?? '',
    agentType: data.agent ?? data.agent_type ?? existing.agentType ?? null,
    depends_on: Array.isArray(data.depends_on) ? data.depends_on : (existing.depends_on || []),
    status: data.status || existing.status || 'ACTIVE',
    result: data.result ?? existing.result ?? '',
    metrics: { ...(existing.metrics || {}), ...(data.metrics || {}) },
    events: existing.events || [],
    omittedEvents: existing.omittedEvents || 0,
    sequenceGap: existing.sequenceGap || false,
    stopReason: data.stop_reason ?? existing.stopReason ?? null,
    durationMs: data.duration_ms ?? existing.durationMs ?? null,
    maxLlmCalls: data.max_llm_calls ?? existing.maxLlmCalls ?? null,
    submissionReserve: data.submission_reserve ?? existing.submissionReserve ?? null,
    wrapUpCalls: data.wrap_up_calls ?? existing.wrapUpCalls ?? null,
    startedAt: data.started_at ?? existing.startedAt ?? null,
  }
}

export function applyDagNodeStart(nodes, data) {
  if (!data?.id) return nodes
  const existing = nodes[data.id] || {}
  return {
    ...nodes,
    [data.id]: normalizeNode({ ...data, status: data.status || 'ACTIVE' }, existing),
  }
}

export function applySubagentEvent(nodes, payload, maxEvents = DEFAULT_MAX_EVENTS) {
  const nodeId = payload?.node_id
  if (!nodeId || !nodes[nodeId]) return nodes

  const existing = nodes[nodeId]
  const previousEvents = existing.events || []
  const highestSequence = previousEvents.reduce(
    (highest, event) => Math.max(highest, Number(event.sequence) || 0),
    0,
  )
  const sequence = Number(payload.sequence) || 0
  const hasGap = existing.sequenceGap || sequence !== highestSequence + 1
  const sorted = [...previousEvents, payload].sort(
    (left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0),
  )
  const overflow = Math.max(0, sorted.length - maxEvents)
  const events = overflow ? sorted.slice(overflow) : sorted
  const node = normalizeNode({}, existing)
  node.events = events
  node.metrics = { ...(existing.metrics || {}), ...(payload.metrics || {}) }
  node.omittedEvents = (existing.omittedEvents || 0) + overflow
  node.sequenceGap = hasGap
  if (payload.event_type === 'budget_state' && payload.summary?.state) {
    node.status = payload.summary.state
  }

  return { ...nodes, [nodeId]: node }
}

export function applyDagNodeComplete(nodes, data) {
  if (!data?.id || !nodes[data.id]) return nodes
  const existing = nodes[data.id]
  return {
    ...nodes,
    [data.id]: normalizeNode({ ...data, status: data.status || 'COMPLETED' }, existing),
  }
}
