<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  sessions: Array,
  currentId: [Number, String],
  connected: Boolean,
  wsStatus: String,
  darkMode: Boolean
})
const emit = defineEmits(['switch', 'new', 'delete', 'rename', 'darkToggle', 'settings'])

const filter = ref('')
const collapsed = ref(false)

const filtered = computed(() => {
  const f = filter.value.toLowerCase().trim()
  return f ? props.sessions.filter(s => (s.title || '').toLowerCase().includes(f)) : props.sessions
})

let renamingId = ref(null)
let renameValue = ref('')

function startRename(id, title) {
  renamingId.value = id; renameValue.value = title
  setTimeout(() => document.getElementById('rename-' + id)?.select(), 50)
}
function commitRename(id) {
  if (renameValue.value.trim()) emit('rename', id, renameValue.value.trim())
  renamingId.value = null
}
</script>

<template>
  <aside id="sidebar" :class="{ collapsed }">
    <div id="sidebar-header">
      <div id="connection-dot" :class="wsStatus || 'disconnected'" :title="wsStatus === 'connected' ? '已连接' : wsStatus === 'reconnecting' ? '重连中...' : '未连接'"></div>
      <span v-if="!collapsed" id="sidebar-title">EchoLily</span>
      <button id="dark-toggle" @click="emit('darkToggle')" :title="darkMode ? '切换亮色模式' : '切换暗色模式'">
        <svg v-if="!darkMode" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>
      <button v-if="!collapsed" id="collapse-btn" @click="collapsed = !collapsed" title="收起侧边栏">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
    </div>
    <div v-show="!collapsed" id="sidebar-body">
      <input id="search-input" v-model="filter" placeholder="搜索会话..." />
      <button id="new-btn" @click="emit('new')">+ 新建对话</button>
      <div id="session-list">
        <div v-for="s in filtered" :key="s.id"
          class="session-item" :class="{ active: s.id === currentId }"
          @click="emit('switch', s.id)">
          <template v-if="renamingId === s.id">
            <input :id="'rename-' + s.id" v-model="renameValue" class="rename-input"
              @blur="commitRename(s.id)" @keydown.enter="commitRename(s.id)"
              @keydown.escape="renamingId = null" @click.stop>
          </template>
          <template v-else>
            <span class="session-title" @dblclick.stop="startRename(s.id, s.title || '会话 #' + s.id)">
              {{ s.title || '会话 #' + s.id }}
            </span>
          </template>
          <span class="session-del" @click.stop="emit('delete', s.id)">✕</span>
        </div>
      </div>
    </div>
    <!-- collapsed icons -->
    <div v-if="collapsed" id="collapsed-icons">
      <button class="collapsed-icon-btn" @click="emit('new')" title="新建对话">+</button>
      <button class="collapsed-icon-btn" @click="collapsed = false" title="展开侧边栏">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
      </button>
    </div>
    <div v-show="!collapsed" id="sidebar-footer">
      <button @click="emit('settings')">⚙ 设置</button>
    </div>
  </aside>
</template>

<style scoped>
#sidebar {
  width: var(--sidebar-width); min-width: 200px;
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  border-right: 1px solid var(--border-glass);
  transition: width var(--transition-normal);
}
#sidebar.collapsed { width: var(--sidebar-collapsed); min-width: var(--sidebar-collapsed); }

/* ── Header ── */
#sidebar-header {
  display: flex; align-items: center; gap: 8px;
  padding: 16px 14px 12px;
}
#sidebar.collapsed #sidebar-header { justify-content: center; padding: 16px 8px; }

/* ── 连接指示灯 ── */
#connection-dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0;
  background: oklch(65% 0.12 145);
  box-shadow: 0 0 6px oklch(65% 0.12 145 / 0.5);
  transition: all var(--transition-normal);
}
#connection-dot.connected {
  background: oklch(62% 0.15 145);
  box-shadow: 0 0 6px oklch(62% 0.15 145 / 0.6);
  animation: connPulse 2s ease-in-out infinite;
}
#connection-dot.reconnecting {
  background: oklch(65% 0.12 75);
  box-shadow: 0 0 6px oklch(65% 0.12 75 / 0.5);
  animation: connPulse 0.8s ease-in-out infinite;
}
#connection-dot.disconnected {
  background: oklch(55% 0.01 250);
  box-shadow: none;
}
@keyframes connPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

#sidebar-title {
  flex: 1; font-weight: 700; font-size: 16px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; letter-spacing: 0.5px;
}

/* ── 暗色模式 & 折叠按钮 ── */
#dark-toggle, #collapse-btn {
  cursor: pointer; background: var(--bg-glass); border: 1px solid var(--border-glass);
  border-radius: var(--radius-sm); width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
  flex-shrink: 0;
}
#dark-toggle:hover, #collapse-btn:hover {
  background: var(--bg-glass-hover);
  color: var(--crimson);
}

#sidebar-body {
  flex: 1; overflow-y: auto; padding: 0 12px 8px;
}
#search-input {
  width: 100%; padding: 8px 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  font-size: 13px; font-family: var(--font-ui);
  background: var(--bg-glass-raised);
  color: var(--text-primary);
  outline: none; margin-bottom: 8px;
  transition: border-color var(--transition-fast);
}
#search-input:focus { border-color: var(--crimson); }
#search-input::placeholder { color: var(--text-placeholder); }
#new-btn {
  width: 100%; padding: 8px;
  border: 1px dashed var(--border-glass);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer; margin-bottom: 8px; font-size: 13px;
  transition: all var(--transition-fast);
  font-family: var(--font-ui);
}
#new-btn:hover {
  background: var(--crimson-alpha);
  border-color: var(--crimson-alpha);
  color: var(--crimson);
}
#session-list { display: flex; flex-direction: column; gap: 2px; }
.session-item {
  display: flex; align-items: center; padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer; font-size: 13px;
  transition: all var(--transition-fast);
  position: relative;
}
.session-item:hover { background: var(--crimson-alpha); }
.session-item.active {
  background: var(--crimson-alpha);
  font-weight: 500;
  color: var(--crimson);
}
.session-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--text-primary);
}
.session-item.active .session-title { color: var(--crimson); }
.session-del {
  cursor: pointer; color: var(--text-weak); font-size: 12px;
  opacity: 0; padding: 0 4px;
  transition: all var(--transition-fast);
}
.session-item:hover .session-del { opacity: 1; }
.session-del:hover { color: var(--crimson); }
.rename-input {
  width: 100%; padding: 4px 6px;
  border: 1px solid var(--crimson);
  border-radius: var(--radius-sm); font-size: 13px;
  font-family: var(--font-ui);
  outline: none;
  background: var(--bg-glass-raised);
  color: var(--text-primary);
}

/* ── Collapsed icons ── */
#collapsed-icons {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  gap: 8px; padding: 12px 0;
}
.collapsed-icon-btn {
  width: 36px; height: 36px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-glass);
  background: var(--bg-glass-raised);
  color: var(--text-secondary);
  cursor: pointer; font-size: 18px;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.collapsed-icon-btn:hover {
  background: var(--crimson-alpha);
  color: var(--crimson);
  border-color: var(--crimson-alpha);
}

/* ── Footer ── */
#sidebar-footer {
  padding: 10px 12px 14px;
  border-top: 1px solid var(--border-light);
  display: flex; flex-direction: column; gap: 4px;
  background: var(--bg-glass);
}
#sidebar-footer button {
  width: 100%; padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-glass-raised);
  color: var(--text-secondary);
  cursor: pointer; font-size: 13px; font-family: var(--font-ui);
  transition: all var(--transition-fast);
  text-align: center;
}
#sidebar-footer button:hover {
  background: var(--crimson-alpha);
  color: var(--crimson);
  border-color: var(--crimson-alpha);
}
</style>
