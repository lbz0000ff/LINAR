<script setup>
import { ref } from 'vue'
import { send } from '../composables/useWebSocket.js'

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
  <div id="settings-overlay">
    <div id="settings-page">
      <div id="settings-header">
        <button @click="emit('close')">← 返回</button>
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
          <label><input type="checkbox" checked> 显示思考过程</label><br>
          <label><input type="checkbox" checked> 显示工具调用详情</label><br>
          <label><input type="checkbox" checked> 自动滚动到最新</label>
        </div>
        <!-- 模型 -->
        <div v-show="activeSection === 'model'" class="section">
          <h3>模型/连接</h3>
          <p style="color:#999;font-size:13px;">WebSocket URL 在 useWebSocket.js 中配置</p>
        </div>
        <!-- 外观 -->
        <div v-show="activeSection === 'appearance'" class="section">
          <h3>外观</h3>
          <label><input type="checkbox" @change="emit('darkMode')"> 深色模式</label>
        </div>
        <!-- 关于 -->
        <div v-show="activeSection === 'about'" class="section">
          <h3>关于 EchoLily</h3>
          <p style="color:#666;">Vue 3 + Vite 重构版</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
#settings-overlay {
  position: fixed; inset: 0;
  background: var(--bg-page);
  z-index: 50; display: flex; flex-direction: column;
  animation: settingsIn 250ms ease-out;
}
@keyframes settingsIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
#settings-header {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
}
#settings-header h2 { font-size: 16px; font-weight: 600; color: var(--text-primary); }
#settings-header button {
  cursor: pointer; background: var(--bg-glass-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 6px 14px; font-size: 13px; font-family: var(--font-ui);
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}
#settings-header button:hover { background: var(--bg-glass-hover); color: var(--crimson); }
#settings-nav {
  display: flex; gap: 2px;
  padding: 10px 24px 0;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-glass);
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
  flex: 1; overflow-y: auto; padding: 24px;
}
.section {
  max-width: 640px; animation: msgIn 200ms ease-out;
}
.section h3 { margin-bottom: 16px; font-size: 15px; color: var(--text-primary); }
.section label {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px; font-size: 13px; cursor: pointer;
  color: var(--text-secondary); padding: 8px 12px;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}
.section label:hover { background: var(--crimson-alpha); }
.section input[type="checkbox"] {
  accent-color: var(--crimson);
  width: 16px; height: 16px;
}
.section p { color: var(--text-weak); font-size: 13px; margin: 8px 0; }
</style>
