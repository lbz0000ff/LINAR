<script setup>
import { ref } from 'vue'

const props = defineProps({ darkMode: Boolean })
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
  <teleport to="body">
    <div id="settings-backdrop" @click.self="emit('close')">
      <div id="settings-panel">
        <button id="settings-close" @click="emit('close')" title="关闭">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
        <!-- Tabs -->
        <div id="settings-nav">
          <button v-for="sec in sections" :key="sec.id"
            :class="['nav-item', { active: activeSection === sec.id }]"
            @click="switchSection(sec.id)">{{ sec.label }}</button>
        </div>
        <!-- 内容 -->
        <div id="settings-body">
          <div v-show="activeSection === 'general'" class="section">
            <h3>通用</h3>
            <label class="setting-row"><input type="checkbox" checked><span>显示思考过程</span></label>
            <label class="setting-row"><input type="checkbox" checked><span>显示工具调用详情</span></label>
            <label class="setting-row"><input type="checkbox" checked><span>自动滚动到最新</span></label>
          </div>
          <div v-show="activeSection === 'model'" class="section">
            <h3>模型 / 连接</h3>
            <p class="section-hint">WebSocket URL 在 useWebSocket.js 中配置</p>
          </div>
          <div v-show="activeSection === 'appearance'" class="section">
            <h3>外观</h3>
            <label class="setting-row">
              <input type="checkbox" :checked="darkMode" @change="emit('darkMode')">
              <span>深色模式</span>
            </label>
          </div>
          <div v-show="activeSection === 'about'" class="section">
            <h3>关于 EchoLily</h3>
            <p class="section-hint">Vue 3 + Vite 重构版</p>
            <p class="section-hint">雪覆红玫 · 毛玻璃设计系统</p>
          </div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
/* ── 遮罩 ── */
#settings-backdrop {
  position: fixed; inset: 0; z-index: 100;
  background: oklch(0% 0 0 / 0.35);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: backdropIn 200ms ease-out;
  display: flex; justify-content: center; align-items: center;
}
@keyframes backdropIn { from { opacity: 0; } to { opacity: 1; } }

/* ── 面板（居中对话框）── */
#settings-panel {
  position: relative;
  width: 440px; max-width: 90vw; max-height: 80vh;
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  border: 1px solid var(--border-glass);
  border-radius: 12px;
  box-shadow: 0 8px 40px oklch(0% 0 0 / 0.2);
  display: flex; flex-direction: column;
  overflow: hidden;
  animation: modalIn 250ms ease-out;
}
@keyframes modalIn {
  from { opacity: 0; transform: scale(0.92) translateY(-12px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

/* ── 关闭按钮（边框右上角）── */
#settings-close {
  position: absolute; top: 8px; right: 8px; z-index: 1;
  width: 28px; height: 28px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; background: transparent;
  border: none;
  color: var(--text-weak);
  transition: all var(--transition-fast);
}
#settings-close:hover { background: oklch(0% 0 0 / 0.08); color: var(--crimson); }

/* ── Tab 导航 ── */
#settings-nav {
  display: flex; gap: 2px;
  padding: 10px 20px 0;
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

/* ── 内容 ── */
#settings-body {
  flex: 1; overflow-y: auto; padding: 24px 20px;
}
.section {
  animation: msgIn 200ms ease-out;
}
.section h3 { margin-bottom: 16px; font-size: 15px; color: var(--text-primary); }
.section-hint { color: var(--text-weak); font-size: 13px; margin: 8px 0; }

.setting-row {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 8px; font-size: 13px; cursor: pointer;
  color: var(--text-secondary); padding: 10px 14px;
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
}
.setting-row:hover { background: var(--crimson-alpha); }
.setting-row span { flex: 1; }
.setting-row input[type="checkbox"] {
  accent-color: var(--crimson);
  width: 16px; height: 16px; flex-shrink: 0;
}
</style>
