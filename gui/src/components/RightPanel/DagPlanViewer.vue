<script setup>
defineProps({
  plans: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
})

defineEmits(['select'])

function nodeCount(plan) {
  return Object.keys(plan.nodes || {}).length
}
</script>

<template>
  <nav v-if="plans.length" class="dag-viewer" aria-label="DAG plans">
    <button
      v-for="(plan, index) in plans"
      :key="plan.id"
      class="dag-chip"
      :class="{ selected: plan.id === selectedId }"
      @click="$emit('select', plan.id)"
    >
      <span class="dag-chip-title">Wave {{ index + 1 }}</span>
      <span class="dag-chip-meta">{{ nodeCount(plan) }} agents · {{ plan.status }}</span>
    </button>
  </nav>
</template>

<style scoped>
.dag-viewer { display: flex; gap: 7px; overflow-x: auto; padding: 0 0 8px; margin-bottom: 10px; scrollbar-width: thin; }
.dag-chip { flex: 0 0 auto; min-width: 112px; max-width: 160px; border: 1px solid var(--border-light); border-radius: 7px; padding: 6px 8px; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.dag-chip:hover { background: var(--bg-glass); }
.dag-chip.selected { border-color: oklch(55% 0.12 240 / 0.65); background: oklch(55% 0.12 240 / 0.08); }
.dag-chip-title, .dag-chip-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dag-chip-title { font-size: 11px; font-weight: 600; }
.dag-chip-meta { margin-top: 2px; color: var(--text-weak); font-size: 9px; }
</style>
