<script setup>
import { ref } from 'vue'
import PlanProgress from './RightPanel/PlanProgress.vue'
import BtwResults from './RightPanel/BtwResults.vue'
import AgentStatus from './RightPanel/AgentStatus.vue'
import AssetsArea from './RightPanel/AssetsArea.vue'

const props = defineProps({
  dagNodes: { type: Object, default: () => ({}) },
  dagGoal: { type: String, default: '' },
  dagActive: { type: Boolean, default: false },
  btwResults: { type: Array, default: () => [] },
  workspacePath: { type: String, default: '' },
  workspaceAssets: { type: Array, default: () => [] },
})

const emit = defineEmits(['close'])

const panelEl = ref(null)
let panelWidth = 300
let isResizing = false

function onResizeStart(e) {
  e.preventDefault()
  if (!panelEl.value) return
  const startX = e.clientX
  const startW = panelEl.value.clientWidth
  isResizing = true
  if (panelEl.value) panelEl.value.style.transition = 'none'
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  function onMove(ev) {
    const w = Math.max(200, Math.min(520, startW - (ev.clientX - startX)))
    panelWidth = w
    if (panelEl.value) panelEl.value.style.width = w + 'px'
  }
  function onUp() {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    isResizing = false
    if (panelEl.value) panelEl.value.style.transition = 'width 200ms ease'
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>

<template>
  <aside id="right-panel" ref="panelEl">
    <div class="rp-resize-handle" @mousedown="onResizeStart"></div>

    <div class="rp-header">
      <span class="rp-header-title">{{ $t('panel.title') }}</span>
      <button class="rp-close-btn" @click="emit('close')" :title="$t('panel.close')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <div class="rp-body">
      <PlanProgress :nodes="dagNodes" :goal="dagGoal" :active="dagActive" />
      <AssetsArea :assets="workspaceAssets" :workspace-path="workspacePath" />
      <BtwResults :results="btwResults" />
      <AgentStatus />
    </div>
  </aside>
</template>

<style scoped>
#right-panel {
  position: relative;
  width: 300px; min-width: 200px; max-width: 520px;
  display: flex; flex-direction: column;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  border-left: 1px solid var(--border-glass);
  margin: 8px 8px 8px 0;
  border-radius: 12px;
  overflow: hidden;
  transition: width 200ms ease;
  contain: layout style;
}

/* Resize handle — left edge */
.rp-resize-handle {
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 4px; cursor: col-resize; z-index: 10;
  transition: background var(--transition-fast);
}
.rp-resize-handle:hover,
.rp-resize-handle:active {
  background: var(--crimson-alpha);
}

/* Header */
.rp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
.rp-header-title {
  font-size: 13px; font-weight: 600; color: var(--text-primary);
}
.rp-close-btn {
  width: 26px; height: 26px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; background: transparent; border: none;
  color: var(--text-weak);
  transition: all var(--transition-fast);
}
.rp-close-btn:hover { background: oklch(0% 0 0 / 0.08); color: var(--crimson); }

/* Scrollable body */
.rp-body {
  flex: 1; overflow-y: auto; padding: 16px;
}

/* Section pattern reused by child components */
.rp-section { margin-bottom: 20px; }
.rp-section-title {
  font-size: 13px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 10px;
}
</style>
