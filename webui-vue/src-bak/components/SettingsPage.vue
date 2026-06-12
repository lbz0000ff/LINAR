<script setup>
import { ref } from 'vue'

const emit = defineEmits(['close', 'darkMode'])

const activeSection = ref('general')
const sections = [
  { id: 'general', label: '通用' },
  { id: 'model', label: '模型' },
  { id: 'appearance', label: '外观' },
  { id: 'about', label: '关于' },
]

function switchSection(id) { activeSection.value = id }
</script>

<template>
  <!-- 遮罩 -->
  <div id="settings-backdrop" @click="emit('close')"></div>
  <!-- 滑出面板 -->
  <div id="settings-panel">
    <div id="settings-header">
      <button @click="emit('close')" title="关闭">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <h2>设置</h2>
    </div>
    <div id="settings-nav">
      <button v-for="sec in sections" :key="sec.id"
        :class="['nav-item', { active: activeSection === sec.id }]"
        @click="switchSection(sec.id)">{{ sec.label }}</button>
    </div>
    <div id="settings-body">
      <!-- 通用 -->
      <div v-show="activeSection === 'general'" class="section">
        <h3>通用</h3>
        <label><input type="checkbox" checked> 显示思考过程</label>
        <label><input type="checkbox" checked> 显示工具调用详情</label>
        <label><input type="checkbox" checked> 自动滚动到最新</label>
      </div>
      <!-- 模型 -->
      <div v-show="activeSection === 'model'" class="section">
        <h3>模型 / 连接</h3>
        <p class="hint">WebSocket 连接地址在 useWebSocket.js 中配置</p>
      </div>
      <!-- 外观 -->
      <div v-show="activeSection === 'appearance'" class="section">
        <h3>外观</h3>
        <label class="toggle-row">
          <span>深色模式</span>
          <input type="checkbox" @change="emit('darkMode')">
        </label>
      </div>
      <!-- 关于 -->
      <div v-show="activeSection === 'about'" class="section">
        <h3>关于 EchoLily</h3>
        <p class="hint">Vue 3 + Vite · 雪覆红玫设计 · 毛玻璃质感</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
#settings-backdrop {
  position: fixed; inset: 0;
  background: oklch(0% 0 0 / 0.15);
  z-index: 50;
  animation: fadeIn 200ms ease-out;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

#settings-panel {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: 380px; max-width: 90vw;
  z-index: 51;
  display: flex; flex-direction: column;
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  border-left: 1px solid var(--border-glass);
  box-shadow: var(--shadow-raised);
  animation: slideIn 250ms ease-out;
}
@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

#settings-header {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
}
#settings-header h2 {
  font-size: 16px; font-weight: 600; color: var(--text-primary);
}
#settings-header button {
  cursor: pointer; background: var(--bg-glass);
  border: 1px solid var(--border-glass);
  border-radius: var(--radius-sm);
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}
#settings-header button:hover { background: var(--bg-glass-hover); color: var(--crimson); }

#settings-nav {
  display: flex; gap: 2px;
  padding: 10px 20px 0;
  border-bottom: 1px solid var(--border-light);
}
.nav-item {
  padding: 8px 16px; border: none; background: none;
  cursor: pointer; font-size: 13px; font-family: var(--font-ui);
  color: var(--text-secondary);
  border-bottom: 2px solid transparent;
  transition: all var(--transition-fast);
}
.nav-item:hover { color: var(--crimson); background: var(--crimson-alpha); border-radius: var(--radius-sm) var(--radius-sm) 0 0; }
.nav-item.active {
  border-bottom-color: var(--crimson);
  color: var(--crimson);
  font-weight: 500;
}
#settings-body {
  flex: 1; overflow-y: auto; padding: 20px;
}
.section {
  animation: msgIn 200ms ease-out;
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.section h3 { margin-bottom: 14px; font-size: 15px; color: var(--text-primary); }
.section label {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 6px; font-size: 13px; cursor: pointer;
  color: var(--text-secondary); padding: 10px 12px;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}
.section label:hover { background: var(--crimson-alpha); }
.section .toggle-row {
  justify-content: space-between;
}
.section input[type="checkbox"] {
  accent-color: var(--crimson);
  width: 16px; height: 16px;
}
.hint { color: var(--text-weak); font-size: 13px; margin: 8px 0; }
</style>
