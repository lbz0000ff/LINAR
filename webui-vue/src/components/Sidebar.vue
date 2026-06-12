<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  sessions: Array,
  currentId: [Number, String],
  status: { type: String, default: 'disconnected' },  // connected | disconnected | reconnecting
  darkMode: Boolean,
})
const emit = defineEmits(['switch', 'new', 'delete', 'rename', 'darkToggle', 'settings'])

const filter = ref('')
const collapsed = ref(false)  // 折叠状态

const filtered = computed(() => {
  const f = filter.value.toLowerCase().trim()
  return f ? props.sessions.filter(s => (s.title || '').toLowerCase().includes(f)) : props.sessions
})

const statusLabel = computed(() => {
  if (props.status === 'connected') return '已连接'
  if (props.status === 'reconnecting') return '重连中...'
  return '未连接'
})

const statusClass = computed(() => 'status-' + props.status)

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
function toggleCollapse() { collapsed.value = !collapsed.value }
</script>

<template>
  <aside id="sidebar" :class="{ collapsed }">
    <!-- ── 顶部：品牌 + 连接灯 + 暗色切换 + 折叠 ── -->
    <div id="sidebar-header">
      <div id="sidebar-brand">
        <span id="sidebar-title" v-show="!collapsed">EchoLily</span>
        <!-- 连接状态灯 -->
        <span class="conn-dot" :class="statusClass" :title="statusLabel">
          <span class="conn-pulse"></span>
        </span>
        <span v-show="!collapsed" class="conn-label">{{ statusLabel }}</span>
      </div>
      <div id="sidebar-header-actions" v-show="!collapsed">
        <button id="dark-toggle" @click="emit('darkToggle')" :title="darkMode ? '亮色模式' : '深色模式'">
          <!-- 太阳 SVG -->
          <svg v-if="darkMode" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
          <!-- 月亮 SVG -->
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        </button>
        <button id="collapse-btn" @click="toggleCollapse" title="收起侧边栏">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- ── 机身：搜索 + 新建 + 会话列表 ── -->
    <div id="sidebar-body" v-show="!collapsed">
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
          <span class="session-del" @click.stop="emit('delete', s.id)">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </span>
        </div>
      </div>
    </div>

    <!-- 折叠模式：图标列表 -->
    <div id="sidebar-collapsed" v-show="collapsed">
      <button class="collapsed-icon" @click="emit('new')" title="新建对话">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      </button>
      <button class="collapsed-icon" @click="emit('settings')" title="设置">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      </button>
      <button id="dark-toggle-collapsed" class="collapsed-icon" @click="emit('darkToggle')" :title="darkMode ? '亮色模式' : '深色模式'">
        <svg v-if="darkMode" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
        <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      </button>
      <button class="collapsed-icon" id="expand-btn" @click="toggleCollapse" title="展开侧边栏">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
      </button>
    </div>

    <!-- ── 底部：设置入口 ── -->
    <div id="sidebar-footer" v-show="!collapsed">
      <button @click="emit('settings')">⚙ 设置</button>
    </div>
  </aside>
</template>

<style scoped>
#sidebar {
  width: var(--sidebar-width);
  min-width: 200px;
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  border-right: 1px solid var(--border-glass);
  transition: width var(--transition-slow);
}
#sidebar.collapsed { width: 52px; min-width: 52px; }

/* ── 头部 ── */
#sidebar-header {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 16px 12px 12px 16px;
}
#sidebar.collapsed #sidebar-header {
  padding: 16px 0 12px; justify-content: center; flex-direction: column; gap: 12px;
}
#sidebar-brand { display: flex; align-items: center; gap: 8px; }
#sidebar-title {
  font-weight: 700; font-size: 16px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; letter-spacing: 0.5px;
}
#sidebar-header-actions { display: flex; align-items: center; gap: 4px; }

/* ── 连接状态灯 ── */
.conn-dot {
  width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
  position: relative;
  transition: background var(--transition-normal);
}
.conn-dot.status-connected { background: oklch(58% 0.16 145); }
.conn-dot.status-disconnected { background: oklch(60% 0.01 65); }
.conn-dot.status-reconnecting { background: oklch(68% 0.12 85); }
.conn-pulse {
  position: absolute; inset: -4px; border-radius: 50%;
  opacity: 0; animation: none;
}
.conn-dot.status-connected .conn-pulse {
  animation: connPulse 2s ease-in-out infinite;
  background: oklch(58% 0.16 145 / 0.3);
}
.conn-dot.status-reconnecting .conn-pulse {
  animation: connPulse 0.8s ease-in-out infinite;
  background: oklch(68% 0.12 85 / 0.3);
}
@keyframes connPulse {
  0% { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(2.2); opacity: 0; }
}
.conn-label {
  font-size: 11px; color: var(--text-weak); white-space: nowrap;
}

/* ── 按钮 ── */
#dark-toggle, #collapse-btn {
  cursor: pointer; background: var(--bg-glass); border: 1px solid var(--border-glass);
  border-radius: var(--radius-sm); padding: 6px; width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}
#dark-toggle:hover, #collapse-btn:hover { background: var(--bg-glass-hover); color: var(--crimson); }

/* ── 折叠模式图标 ── */
#sidebar-collapsed {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  gap: 4px; padding: 8px 0; overflow-y: auto;
}
.collapsed-icon {
  width: 40px; height: 40px; border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; background: transparent; border: none;
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}
.collapsed-icon:hover { background: var(--crimson-alpha); color: var(--crimson); }
#expand-btn { margin-top: auto; }

/* ── 机身 ── */
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
  transition: background var(--transition-fast);
  position: relative;
}
.session-item:hover { background: var(--crimson-alpha); }
.session-item.active {
  background: var(--crimson-alpha);
  font-weight: 500;
  color: var(--crimson);
  border-left: 3px solid var(--crimson);
  padding-left: 9px;
}
.session-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--text-primary);
}
.session-item.active .session-title { color: var(--crimson); }
.session-del {
  cursor: pointer; color: var(--text-weak); font-size: 12px;
  display: none; padding: 0 4px;
  transition: color var(--transition-fast);
}
.session-item:hover .session-del { display: flex; }
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
