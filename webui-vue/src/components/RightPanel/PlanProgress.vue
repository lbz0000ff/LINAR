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

const nodeList = computed(() => {
  return Object.values(props.nodes)
})
</script>

<template>
  <div class="pp-section">
    <div class="pp-title">📋 任务计划</div>
    <div v-if="!active && !nodeList.length" class="pp-empty">暂无活跃任务</div>
    <template v-else>
      <div v-if="goal" class="pp-goal">{{ goal }}</div>
      <div class="pp-list">
        <div v-for="n in nodeList" :key="n.id" class="pp-node" :class="STATUS_CFG[n.status]?.cls || ''">
          <span class="pp-status" :title="STATUS_CFG[n.status]?.label || n.status">
            {{ STATUS_CFG[n.status]?.icon || '?' }}
          </span>
          <span class="pp-desc">{{ n.description }}</span>
        </div>
      </div>
      <div v-if="!nodeList.length && active" class="pp-empty">等待节点分配...</div>
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
.pp-list {
  display: flex; flex-direction: column; gap: 4px;
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
