<script setup>
import { computed } from 'vue'

const props = defineProps({
  nodes: { type: Object, default: () => ({}) },
  goal: { type: String, default: '' },
  active: { type: Boolean, default: false },
})

const STATUS_CFG = {
  PENDING:    { cls: 'st-pending',    icon: '○', label: '等待中' },
  IN_PROGRESS:{ cls: 'st-running',    icon: '◉', label: '执行中' },
  COMPLETED:  { cls: 'st-done',       icon: '●', label: '完成' },
  FAILED:     { cls: 'st-failed',     icon: '✕', label: '失败' },
  BLOCKED:    { cls: 'st-blocked',    icon: '⊘', label: '阻塞' },
}

// Compute dependency levels for each node
function computeLevels(nodesMap) {
  const levels = []  // levels[0] = root nodes, levels[1] = their dependents, etc.
  const assigned = new Set()

  // Handle plan_nodes format (array) and legacy format (object keyed by id)
  let entries
  if (Array.isArray(nodesMap)) {
    entries = nodesMap
  } else {
    entries = Object.values(nodesMap)
  }

  if (!entries.length) return levels

  // Normalize: ensure each entry has depends_on as an array
  let remaining = entries.map(n => ({
    ...n,
    depends_on: Array.isArray(n.depends_on) ? n.depends_on
                : n.depends ? [n.depends]
                : [],
  }))

  while (remaining.length) {
    // Nodes whose all deps are already assigned
    const ready = remaining.filter(n =>
      n.depends_on.every(d => assigned.has(d))
    )
    if (!ready.length) {
      // Stuck — remaining nodes have unmet deps, assign them as a fallback level
      levels.push(remaining.map(n => n.id))
      break
    }
    levels.push(ready.map(n => n.id))
    ready.forEach(n => assigned.add(n.id))
    remaining = remaining.filter(n => !assigned.has(n.id))
  }

  return levels
}

const dagLevels = computed(() => computeLevels(props.nodes))
const hasNodes = computed(() => {
  const e = props.nodes
  if (Array.isArray(e)) return e.length > 0
  return Object.keys(e).length > 0
})
</script>

<template>
  <div class="pp-section">
    <div class="pp-title">📋 任务计划</div>
    <div v-if="!active && !hasNodes" class="pp-empty">暂无活跃任务</div>
    <template v-else>
      <div v-if="goal" class="pp-goal">{{ goal }}</div>
      <div class="pp-dag">
        <div v-for="(level, li) in dagLevels" :key="li" class="pp-level">
          <div class="pp-level-label">
            Wave {{ li + 1 }}
            <span v-if="level.length > 1" class="pp-level-badge">并行 {{ level.length }}</span>
          </div>
          <div class="pp-level-nodes">
            <div
              v-for="nid in level"
              :key="nid"
              class="pp-node"
              :class="STATUS_CFG[nodes[nid]?.status]?.cls || ''"
            >
              <span class="pp-status" :title="STATUS_CFG[nodes[nid]?.status]?.label || nodes[nid]?.status">
                {{ STATUS_CFG[nodes[nid]?.status]?.icon || '?' }}
              </span>
              <span class="pp-desc">{{ nodes[nid]?.description || nid }}</span>
            </div>
          </div>
          <div v-if="li < dagLevels.length - 1" class="pp-arrow">↓</div>
        </div>
      </div>
      <div v-if="!hasNodes && active" class="pp-empty">等待节点分配...</div>
    </template>
  </div>
</template>

<style scoped>
.pp-section { margin-bottom: 20px; }
.pp-title {
  font-size: 13px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 10px;
}
.pp-empty {
  font-size: 12px; color: var(--text-weak);
  padding: 8px 0;
}
.pp-goal {
  font-size: 12px; color: var(--text-secondary);
  margin-bottom: 10px; padding: 8px 10px;
  background: var(--bg-glass); border-radius: 6px;
  line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  max-height: 80px; overflow-y: auto;
}

.pp-dag {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.pp-level {
  width: 100%;
  display: flex; flex-direction: column; gap: 4px;
}
.pp-level-label {
  font-size: 11px; font-weight: 600; color: var(--text-weak);
  text-transform: uppercase; letter-spacing: 0.5px;
  display: flex; align-items: center; gap: 8px;
}
.pp-level-badge {
  font-size: 10px; font-weight: 400;
  color: oklch(55% 0.1 240);
  background: oklch(55% 0.1 240 / 0.1);
  padding: 1px 6px; border-radius: 4px;
}
.pp-level-nodes {
  display: flex; flex-direction: column; gap: 4px;
}
.pp-arrow {
  font-size: 14px; color: var(--text-weak); opacity: 0.5;
  line-height: 1;
}

.pp-node {
  display: flex; align-items: baseline; gap: 8px;
  padding: 6px 8px; border-radius: 6px;
  font-size: 12px;
  transition: background 150ms ease;
}
.pp-node:hover { background: var(--bg-glass); }
.pp-status {
  flex-shrink: 0; font-size: 10px; width: 16px; text-align: center;
}
.pp-desc { color: var(--text-primary); line-height: 1.4; }

/* Status colors */
.st-pending  .pp-status { color: var(--text-weak); }
.st-pending  .pp-desc  { color: var(--text-weak); }
.st-running  .pp-status { color: oklch(55% 0.12 240); animation: pulse-status 1s ease-in-out infinite; }
.st-running  .pp-desc  { color: var(--text-primary); }
.st-done     .pp-status { color: oklch(55% 0.14 145); }
.st-done     .pp-desc  { color: var(--text-secondary); }
.st-failed   .pp-status { color: var(--crimson); }
.st-failed   .pp-desc  { color: var(--crimson); }
.st-blocked  .pp-status { color: oklch(55% 0.1 80); }
.st-blocked  .pp-desc  { color: var(--text-weak); }

@keyframes pulse-status {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
