<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  nodes: { type: Object, default: () => ({}) },
})

const selectedId = ref('')
const expanded = ref(new Set())

const tracedNodes = computed(() => Object.values(props.nodes).filter(node => node.events?.length))
const selectedNode = computed(() => props.nodes[selectedId.value] || tracedNodes.value[0] || null)

watch(tracedNodes, nodes => {
  if (!nodes.length) selectedId.value = ''
  else if (!nodes.some(node => node.id === selectedId.value)) selectedId.value = nodes[0].id
}, { immediate: true })

function eventKey(sequence) {
  return `${selectedNode.value?.id || ''}:${sequence}`
}

function toggleEvent(sequence) {
  const key = eventKey(sequence)
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

function eventTitle(event) {
  return event.tool_name || event.event_type || 'event'
}

function eventSummary(event) {
  const summary = event.summary || {}
  if (event.tool_name === 'web_search') {
    return `${summary.query || ''} · ${summary.result_count ?? 0} results`
  }
  if (event.tool_name === 'web_fetch') {
    return `${summary.url || ''} · ${summary.content_length ?? 0} chars`
  }
  if (event.tool_name === 'submit_output') {
    return `${summary.status || 'submitted'} · ${summary.findings ?? 0} findings · ${summary.sources ?? 0} sources`
  }
  if (summary.message) return summary.message
  if (summary.state) return `${summary.state} · ${summary.remaining_calls ?? '?'} calls remaining`
  return Object.keys(summary).length ? JSON.stringify(summary) : event.status || ''
}

function formatTime(timestamp) {
  if (!timestamp) return '--:--:--'
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour12: false })
}

function formatDuration(durationMs) {
  if (durationMs == null) return ''
  if (durationMs < 1000) return `${durationMs}ms`
  return `${(durationMs / 1000).toFixed(1)}s`
}
</script>

<template>
  <section v-if="tracedNodes.length" class="trace-section">
    <div class="trace-title">Subagent Trace</div>
    <div class="trace-layout">
      <div class="trace-nodes">
        <button
          v-for="node in tracedNodes"
          :key="node.id"
          class="trace-node"
          :class="{ selected: selectedNode?.id === node.id }"
          @click="selectedId = node.id"
        >
          <span class="trace-node-head">
            <strong>{{ node.description || node.id }}</strong>
            <span class="trace-state" :data-state="node.status">{{ node.status }}</span>
          </span>
          <span class="trace-node-meta">
            {{ node.agentType || node.hint || 'subagent' }}
            · LLM {{ node.metrics?.llm_calls || 0 }}/{{ node.maxLlmCalls || '?' }}
            · search {{ node.metrics?.search_calls || 0 }}
            · fetch {{ node.metrics?.fetch_calls || 0 }}
          </span>
        </button>
      </div>

      <div v-if="selectedNode" class="trace-detail">
        <div class="trace-detail-head">
          <div>
            <strong>{{ selectedNode.description || selectedNode.id }}</strong>
            <div class="trace-node-meta">
              {{ selectedNode.agentType || selectedNode.hint || 'subagent' }}
              <span v-if="selectedNode.durationMs != null"> · {{ formatDuration(selectedNode.durationMs) }}</span>
            </div>
          </div>
          <span class="trace-state" :data-state="selectedNode.status">{{ selectedNode.status }}</span>
        </div>

        <div v-if="selectedNode.sequenceGap" class="trace-warning">Some events arrived out of sequence.</div>
        <div v-if="selectedNode.omittedEvents" class="trace-warning">
          {{ selectedNode.omittedEvents }} older events omitted.
        </div>

        <div class="trace-events">
          <article
            v-for="event in selectedNode.events"
            :key="event.sequence"
            class="trace-event"
            :data-status="event.status"
          >
            <button class="trace-event-summary" @click="toggleEvent(event.sequence)">
              <span class="trace-time">{{ formatTime(event.timestamp) }}</span>
              <span class="trace-action">{{ eventTitle(event) }}</span>
              <span class="trace-summary">{{ eventSummary(event) }}</span>
              <span class="trace-duration">{{ formatDuration(event.duration_ms) }}</span>
              <span>{{ expanded.has(eventKey(event.sequence)) ? '▾' : '›' }}</span>
            </button>
            <pre v-if="expanded.has(eventKey(event.sequence))" class="trace-event-detail">{{ JSON.stringify(event.detail || {}, null, 2) }}</pre>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trace-section { margin-bottom: 20px; }
.trace-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; }
.trace-layout { display: grid; grid-template-columns: minmax(150px, 0.85fr) minmax(220px, 1.5fr); gap: 10px; }
.trace-nodes { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.trace-node { border: 1px solid var(--border-light); background: transparent; color: var(--text-primary); border-radius: 7px; padding: 8px; text-align: left; cursor: pointer; }
.trace-node:hover { background: var(--bg-glass); }
.trace-node.selected { border-color: oklch(55% 0.12 240 / 0.65); background: oklch(55% 0.12 240 / 0.08); }
.trace-node-head, .trace-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.trace-node-head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.trace-node-meta { margin-top: 4px; color: var(--text-weak); font-size: 10px; line-height: 1.4; }
.trace-state { flex-shrink: 0; font-size: 9px; border-radius: 10px; padding: 2px 6px; color: var(--text-secondary); background: var(--bg-glass); }
.trace-state[data-state="ACTIVE"], .trace-state[data-state="IN_PROGRESS"] { color: oklch(55% 0.12 240); }
.trace-state[data-state="WRAP_UP"], .trace-state[data-state="SUBMIT_ONLY"] { color: oklch(60% 0.13 80); }
.trace-state[data-state="SUBMITTED"], .trace-state[data-state="COMPLETED"] { color: oklch(55% 0.14 145); }
.trace-state[data-state="FAILED"], .trace-state[data-state="CHECKPOINTED"] { color: var(--crimson); }
.trace-detail { min-width: 0; border-left: 1px solid var(--border-light); padding-left: 10px; }
.trace-warning { color: oklch(60% 0.13 80); background: oklch(60% 0.13 80 / 0.08); border-radius: 5px; padding: 5px 7px; margin: 7px 0; font-size: 10px; }
.trace-events { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; max-height: 360px; overflow-y: auto; }
.trace-event { flex: 0 0 auto; border-left: 2px solid var(--border-light); background: var(--bg-glass); border-radius: 4px; overflow: hidden; }
.trace-event[data-status="error"] { border-left-color: var(--crimson); }
.trace-event[data-status="running"] { border-left-color: oklch(55% 0.12 240); }
.trace-event-summary { width: 100%; display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto auto; gap: 6px; align-items: center; border: 0; background: transparent; color: var(--text-secondary); text-align: left; padding: 6px; cursor: pointer; font-size: 10px; }
.trace-time, .trace-duration { color: var(--text-weak); font-variant-numeric: tabular-nums; }
.trace-action { color: var(--text-primary); font-weight: 600; }
.trace-summary { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.trace-event-detail { margin: 0; border-top: 1px solid var(--border-light); padding: 8px; max-height: 220px; overflow: auto; white-space: pre-wrap; word-break: break-word; color: var(--text-secondary); font-size: 10px; }
@media (max-width: 420px) { .trace-layout { grid-template-columns: 1fr; } .trace-detail { border-left: 0; border-top: 1px solid var(--border-light); padding: 10px 0 0; } }
</style>
