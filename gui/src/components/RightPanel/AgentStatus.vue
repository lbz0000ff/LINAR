<script setup>
// Placeholder — future multi-agent execution status
</script>

<template>
  <div class="as-section">
    <div class="as-title">{{ $t('agent.status') }}</div>
    <div class="as-placeholder">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity="0.3">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 6v6l4 2"/>
      </svg>
      <span>{{ $t('agent.comingSoon') }}</span>
    </div>
  </div>
</template>

<style scoped>
.as-section { margin-bottom: 20px; }
.as-title {
  font-size: 13px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 10px;
}
.as-placeholder {
  display: flex; align-items: center; gap: 8px;
  padding: 16px;
  border: 1px dashed var(--border-light);
  border-radius: 8px;
  font-size: 12px; color: var(--text-weak);
}
</style>
