<script setup>
const props = defineProps({
  results: { type: Array, default: () => [] },
})

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <div class="btw-section">
    <div class="btw-title">💬 侧边查询</div>
    <div v-if="!results.length" class="btw-empty">暂无查询</div>
    <div v-for="(r, i) in results" :key="i" class="btw-card">
      <div class="btw-q">
        <span class="btw-q-label">Q</span>
        <span class="btw-q-text">{{ r.question }}</span>
        <span class="btw-ts">{{ fmtTime(r.ts) }}</span>
      </div>
      <div class="btw-a">{{ r.answer }}</div>
    </div>
  </div>
</template>

<style scoped>
.btw-section { margin-bottom: 20px; }
.btw-title {
  font-size: 13px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 10px;
}
.btw-empty {
  font-size: 12px; color: var(--text-weak);
  padding: 8px 0;
}
.btw-card {
  margin-bottom: 10px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  overflow: hidden;
}
.btw-q {
  display: flex; align-items: baseline; gap: 6px;
  padding: 8px 10px;
  background: var(--bg-glass);
  font-size: 12px;
}
.btw-q-label {
  flex-shrink: 0; font-weight: 600; color: var(--crimson);
  font-size: 11px;
}
.btw-q-text { color: var(--text-primary); flex: 1; }
.btw-ts { font-size: 10px; color: var(--text-placeholder); flex-shrink: 0; }
.btw-a {
  padding: 8px 10px;
  font-size: 12px; color: var(--text-secondary);
  line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  max-height: 150px; overflow-y: auto;
}
</style>
