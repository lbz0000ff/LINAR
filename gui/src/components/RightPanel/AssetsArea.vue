<script setup>
defineProps({
  assets: { type: Array, default: () => [] },
  workspacePath: { type: String, default: '' },
})

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

function extIcon(ext) {
  const icons = {
    '.md': '📝', '.json': '📋', '.mmd': '🔷', '.png': '🖼️',
    '.jpg': '🖼️', '.jpeg': '🖼️', '.svg': '🎨', '.pdf': '📄',
    '.csv': '📊', '.html': '🌐', '.txt': '📄',
  }
  return icons[ext] || '📄'
}

function openFile(file) {
  if (window.electronAPI?.openFile) {
    window.electronAPI.openFile(file.path)
  } else {
    window.open('/raw-file/' + encodeURIComponent(file.path), '_blank')
  }
}
</script>

<template>
  <div v-if="workspacePath" class="rp-section">
    <div class="rp-section-title">{{ $t('artifacts.title') }}</div>
    <div v-if="assets.length === 0" class="aa-placeholder">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="1.5" opacity="0.3">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
      </svg>
      <span>{{ $t('artifacts.empty') }}</span>
    </div>
    <div v-else class="aa-list">
      <div v-for="file in assets" :key="file.path"
           class="aa-item" @click="openFile(file)" :title="file.path">
        <span class="aa-icon">{{ extIcon(file.ext) }}</span>
        <span class="aa-name">{{ file.name }}</span>
        <span class="aa-size">{{ formatSize(file.size) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aa-list { display: flex; flex-direction: column; gap: 2px; }
.aa-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 6px;
  cursor: pointer; font-size: 12px;
  color: var(--text-secondary);
  transition: background var(--transition-fast);
}
.aa-item:hover { background: var(--bg-glass-hover); color: var(--text-primary); }
.aa-icon { flex-shrink: 0; font-size: 14px; }
.aa-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aa-size { flex-shrink: 0; font-size: 11px; color: var(--text-weak); font-family: var(--font-mono); }
.aa-placeholder {
  display: flex; align-items: center; gap: 8px;
  padding: 16px; border: 1px dashed var(--border-light);
  border-radius: 8px; font-size: 12px; color: var(--text-weak);
}
</style>
