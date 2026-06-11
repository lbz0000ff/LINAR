<script setup>
import { ref, computed } from 'vue'

const props = defineProps({ sessions: Array, currentId: [Number, String] })
const emit = defineEmits(['switch', 'new', 'delete', 'rename'])

const filter = ref('')

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
  <aside id="sidebar">
    <div id="sidebar-header">
      <span id="sidebar-title">EchoLily</span>
      <button id="dark-toggle" @click="$emit('darkToggle')" title="深色模式">🌙</button>
    </div>
    <div id="sidebar-body">
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
    <div id="sidebar-footer">
      <button @click="$emit('settings')">⚙ 设置</button>
    </div>
  </aside>
</template>

<style scoped>
#sidebar {
  width: var(--sidebar-width); min-width: 200px;
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  border-right: 1px solid var(--border-glass);
}
#sidebar-header {
  display: flex; align-items: center; gap: 8px;
  padding: 16px 16px 12px;
}
#sidebar-title {
  flex: 1; font-weight: 700; font-size: 16px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; letter-spacing: 0.5px;
}
#dark-toggle {
  cursor: pointer; background: var(--bg-glass); border: 1px solid var(--border-glass);
  border-radius: var(--radius-sm); padding: 4px 8px; font-size: 14px;
  transition: all var(--transition-fast); width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
}
#dark-toggle:hover { background: var(--bg-glass-hover); }
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
.session-item:hover .session-del { display: inline; }
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
