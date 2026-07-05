<script setup>
const api = window.electronAPI

function onMinimize() { api?.minimize() }
function onMaximize() { api?.maximize() }
function onClose() { api?.close() }
</script>

<template>
  <header v-if="api?.isElectron" id="titlebar">
    <div class="tb-drag"></div>
    <div class="tb-controls">
      <button class="tb-btn" @click="onMinimize" :title="$t('titlebar.minimize')">
        <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="5.5" width="10" height="1" fill="currentColor"/></svg>
      </button>
      <button class="tb-btn" @click="onMaximize" :title="$t('titlebar.maximize')">
        <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
      </button>
      <button class="tb-btn tb-close" @click="onClose" :title="$t('titlebar.close')">
        <svg width="12" height="12" viewBox="0 0 12 12"><line x1="1" y1="1" x2="11" y2="11" stroke="currentColor" stroke-width="1.4"/><line x1="11" y1="1" x2="1" y2="11" stroke="currentColor" stroke-width="1.4"/></svg>
      </button>
    </div>
  </header>
</template>

<style scoped>
#titlebar {
  height: 32px;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  border-bottom: 1px solid var(--border-light);
  user-select: none;
}
.tb-drag {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: center;
  -webkit-app-region: drag;
}
.tb-controls {
  display: flex;
  height: 100%;
  -webkit-app-region: no-drag;
}
.tb-btn {
  width: 44px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.tb-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--text-primary);
}
.tb-close:hover {
  background: oklch(55% 0.16 25);
  color: #fff;
}
</style>
