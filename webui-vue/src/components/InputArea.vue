<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  isProcessing: Boolean,
  permMode: String,
  connected: Boolean,
  usage: Object,
  skills: Array,
})
const emit = defineEmits(['send', 'stop', 'modeChange', 'toggleReasoning', 'reset', 'showHelp', 'steer', 'btw', 'refreshSessions', 'switchToSession', 'exitApp'])

const inputText = ref('')
const attachments = ref([])
const cmdOpen = ref(false)
const cmdHighlight = ref(0)
const fileInput = ref(null)
const inputAreaEl = ref(null)

const MODES = ['safe', 'auto', 'review']
const MODE_CLASS = { safe: 'mode-safe', auto: 'mode-auto', review: 'mode-review' }

const COMMANDS = [
  { cmd: '/help', desc: '显示帮助' },
  { cmd: '/reasoning', desc: '切换思考过程显示' },
  { cmd: '/reset', desc: '重置对话' },
  { cmd: '/stop', desc: '停止生成' },
  { cmd: '/steer', desc: '修正 Agent 行为（需参数）', hasArg: true },
  { cmd: '/btw', desc: '侧边查询（需参数）', hasArg: true },
  { cmd: '/workspace', desc: '显示当前工作区' },
  { cmd: '/workspace-create', desc: '创建工作区（需路径）', hasArg: true },
  { cmd: '/workspace-switch', desc: '切换工作区（需路径）', hasArg: true },
  { cmd: '/sessions', desc: '刷新会话列表' },
  { cmd: '/session', desc: '切换会话（需参数）', hasArg: true },
  { cmd: '/exit', desc: '关闭窗口' },
]

const SLASH_ACTIONS = {
  '/help': () => { emit('showHelp'); inputText.value = '' },
  '/reasoning': () => { emit('toggleReasoning'); inputText.value = '' },
  '/reset': () => { emit('reset'); inputText.value = '' },
  '/stop': () => { emit('stop'); inputText.value = '' },
  '/sessions': () => { emit('refreshSessions'); inputText.value = '' },
  '/exit': () => { emit('exitApp'); inputText.value = '' },
}

function handleSlashAction(text) {
  const spaceIdx = text.indexOf(' ')
  const cmd = spaceIdx > 0 ? text.slice(0, spaceIdx) : text
  const arg = spaceIdx > 0 ? text.slice(spaceIdx + 1).trim() : ''

  // Exact-match commands
  if (SLASH_ACTIONS[cmd]) { SLASH_ACTIONS[cmd](); return true }

  // Commands with arguments
  if (cmd === '/steer' && arg) { emit('steer', arg); inputText.value = ''; return true }
  if (cmd === '/btw' && arg) { emit('btw', arg); inputText.value = ''; return true }
  if (cmd === '/session' && arg) { emit('switchToSession', arg); inputText.value = ''; return true }

  // Skill commands — send as regular message (orchestrator handles skill invocation)
  const skillNames = (props.skills || []).map(s => s.name)
  if (skillNames.includes(cmd.slice(1))) {
    emit('send', text, [])
    inputText.value = ''
    return true
  }

  // Backend-routed commands — /workspace family (session_manager intercepts)
  if (cmd === '/workspace' || cmd === '/workspace-create' || cmd === '/workspace-switch') {
    emit('send', text, [])
    inputText.value = ''
    return true
  }

  return false
}

const allCommands = computed(() => {
  const skillCmds = (props.skills || []).map(s => ({
    cmd: '/' + s.name, desc: s.desc || '加载技能 ' + s.name, isSkill: true,
  }))
  return [...COMMANDS, ...skillCmds]
})

const filteredCommands = computed(() => {
  const q = inputText.value.trim().toLowerCase()
  if (!q.startsWith('/')) return allCommands.value
  return allCommands.value.filter(c => c.cmd.toLowerCase().startsWith(q))
})

// Auto-show menu when typing "/"
watch(inputText, (val) => {
  const trimmed = val.trim()
  if (trimmed.startsWith('/') && !trimmed.includes(' ')) {
    cmdOpen.value = true
    cmdHighlight.value = 0
  } else if (!trimmed.startsWith('/')) {
    cmdOpen.value = false
  }
})

function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

const backendOrigin = window.electronAPI?.isElectron ? 'http://127.0.0.1:8080' : ''

function onSend() {
  const text = inputText.value.trim()
  if (!text) return

  // Slash commands always work, even during processing
  if (text.startsWith('/')) {
    if (handleSlashAction(text)) { cmdOpen.value = false; return }
    // Commands needing args that weren't provided — ignore
    if (!text.includes(' ')) return
    // Slash with args but unknown command — ignore
    return
  }

  // Regular text blocked during processing
  if (props.isProcessing) return

  if (attachments.value.length) {
    const paths = []
    let pending = attachments.value.length
    attachments.value.forEach(att => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', backendOrigin + '/upload', true)
      xhr.setRequestHeader('X-Filename', encodeURIComponent(att.file.name))
      xhr.onload = () => {
        if (xhr.status === 200) { try { const r = JSON.parse(xhr.responseText); if (r.path) paths.push(r.path) } catch (_) {} }
        pending--; if (!pending) { emit('send', text, paths); inputText.value = ''; attachments.value = [] }
      }
      xhr.onerror = () => { pending--; if (!pending) { emit('send', text, paths); inputText.value = ''; attachments.value = [] } }
      xhr.send(att.file._file || att.file)
    })
  } else {
    emit('send', text, [])
    inputText.value = ''
  }
}

function onFileChange(e) {
  Array.from(e.target.files).forEach(file => {
    const isImage = file.type.startsWith('image/')
    const size = file.size > 1024 * 1024 ? (file.size / (1024 * 1024)).toFixed(1) + ' MB' : (file.size / 1024).toFixed(0) + ' KB'
    attachments.value.push({ name: file.name, size, isImage, file, dataUrl: isImage ? URL.createObjectURL(file) : null })
  })
  e.target.value = ''
}

function removeAttach(i) { attachments.value.splice(i, 1) }

function cycleMode() {
  const next = (MODES.indexOf(props.permMode) + 1) % MODES.length
  emit('modeChange', MODES[next])
}

function selectCmd(cmd) {
  inputText.value = cmd.cmd + ' '
  cmdOpen.value = false
}

function onCmdKeydown(e) {
  if (!cmdOpen.value) return
  const len = filteredCommands.value.length
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    cmdHighlight.value = (cmdHighlight.value + 1) % len
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    cmdHighlight.value = (cmdHighlight.value - 1 + len) % len
  } else if (e.key === 'Tab') {
    e.preventDefault()
    selectCmd(filteredCommands.value[cmdHighlight.value] || filteredCommands.value[0])
  } else if (e.key === 'Escape') {
    cmdOpen.value = false
  }
}

// ── Input resize handle ──
const inputEl = ref(null)
let inputHeight = null

function onInputResizeStart(e) {
  e.preventDefault()
  const startY = e.clientY
  const startH = inputEl.value?.clientHeight || 38
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'

  function onMove(ev) {
    const h = Math.max(38, Math.min(window.innerHeight * 0.5, startH - (ev.clientY - startY)))
    inputHeight = h
    if (inputEl.value) inputEl.value.style.height = h + 'px'
  }
  function onUp() {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>

<template>
  <div id="input-area" ref="inputAreaEl" class="glass-mac">
    <!-- Command menu — above textarea, full width -->
    <div v-if="cmdOpen" id="cmd-panel">
      <div class="cmd-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.5;flex-shrink:0"><line x1="18" y1="4" x2="6" y2="20"/></svg>
        <span class="cmd-search-text">{{ inputText || '/' }}</span>
      </div>
      <div class="cmd-list">
        <div v-for="(c, i) in filteredCommands" :key="c.cmd"
          class="cmd-item" :class="{ highlighted: i === cmdHighlight }"
          @click="selectCmd(c)" @mouseenter="cmdHighlight = i">
          <span class="cmd-name">{{ c.cmd }}</span>
          <span class="cmd-desc">{{ c.desc }}</span>
        </div>
        <div v-if="!filteredCommands.length" class="cmd-empty">无匹配指令</div>
      </div>
    </div>

    <!-- Attachments preview -->
    <div v-if="attachments.length" id="attachments">
      <div v-for="(att, i) in attachments" :key="i" class="attach-chip">
        <img v-if="att.isImage && att.dataUrl" :src="att.dataUrl" class="chip-thumb">
        <span class="chip-name">{{ att.name }}</span>
        <span class="chip-remove" @click="removeAttach(i)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </span>
      </div>
    </div>

    <!-- Input resize handle -->
    <div class="input-resize-handle" @mousedown="onInputResizeStart"></div>

    <!-- Row 1: Input field -->
    <textarea
      ref="inputEl"
      id="input" v-model="inputText" rows="1"
      :placeholder="connected ? '输入消息... ( / 查看指令)' : '未连接 — 等待 WebSocket...'"
      :disabled="!connected"
      @keydown="onCmdKeydown"
      @keydown.enter.prevent="!isProcessing && connected && onSend()"
    ></textarea>

    <!-- Row 2: Toolbar -->
    <div id="input-toolbar">
      <div id="toolbar-left">
        <button class="tb-btn tb-icon" @click="fileInput.click()" title="添加附件">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        </button>
        <input ref="fileInput" type="file" multiple style="display:none" @change="onFileChange">

        <button class="tb-btn tb-text tb-perm" :class="MODE_CLASS[permMode] || 'mode-safe'" @click="cycleMode">
          {{ permMode.toUpperCase() }}
        </button>

        <button class="tb-btn tb-icon" @click="cmdOpen = !cmdOpen" title="指令">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="4" x2="6" y2="20"/></svg>
        </button>
      </div>

      <div id="usage-inline">
        <template v-if="usage?.prompt_tokens">
        <div class="usage-track"><div class="usage-fill" :style="{ width: Math.min(100, (usage.prompt_tokens / 1000000) * 100) + '%' }"></div></div>
        <span class="usage-val">{{ formatTokens(usage.prompt_tokens) }}<span class="usage-max"> / 1M</span></span>
        </template>
      </div>

      <button
        id="send-btn" :class="{ stop: isProcessing && !inputText.trim() }"
        :disabled="!inputText.trim() && !isProcessing"
        @click="(isProcessing && !inputText.trim()) ? emit('stop') : onSend()"
      >
        <svg v-if="!isProcessing || inputText.trim()" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
        <span v-else class="stop-text">停止</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* ── 输入区容器 — Big Sur 毛玻璃 ── */
#input-area {
  position: relative;
  padding: 10px 20px 14px;
  border-top: 1px solid var(--border-light);
}

/* ── 指令面板 ── */
#cmd-panel {
  position: absolute; bottom: 100%; left: 0; right: 0;
  margin: 0 8px 6px 8px;
  background: var(--bg-glass-solid);
  border: 1px solid var(--border-glass);
  border-radius: var(--radius-btn);
  box-shadow: var(--shadow-overlay);
  z-index: 100;
  overflow: hidden;
}
.cmd-search {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border-light);
  font-size: 13px; color: var(--text-secondary);
  font-family: var(--font-mono);
}
.cmd-search-text { color: var(--text-primary); }
.cmd-list {
  max-height: 200px; overflow-y: auto;
}
.cmd-item {
  display: flex; align-items: baseline; gap: 12px;
  padding: 8px 14px; cursor: pointer; font-size: 13px;
  transition: background var(--transition-fast);
}
.cmd-item:hover,
.cmd-item.highlighted {
  background: var(--crimson-alpha);
  color: var(--crimson);
}
.cmd-name {
  font-family: var(--font-mono);
  white-space: nowrap; min-width: 80px;
}
.cmd-desc {
  color: var(--text-weak);
}
.cmd-item.highlighted .cmd-desc { color: var(--crimson); opacity: 0.7; }
.cmd-empty {
  padding: 12px 14px; font-size: 13px; color: var(--text-weak);
  text-align: center;
}

/* ── Row 1: 输入框 ── */
#input {
  width: 100%; resize: none;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-btn);
  padding: 10px 14px;
  font-size: 14px; font-family: var(--font-ui);
  line-height: 1.5; max-height: 25vh;
  background: var(--bg-glass-raised);
  color: var(--text-primary);
  outline: none;
  transition: border-color var(--transition-fast);
  display: block;
  margin-bottom: 8px;
}
#input:focus { border-color: var(--crimson); }
#input:disabled { opacity: 0.5; cursor: not-allowed; background: var(--bg-glass); }
#input::placeholder { color: var(--text-placeholder); }

/* ── Row 2: 工具栏 ── */
#input-toolbar {
  display: flex; align-items: center; gap: 0;
}

#toolbar-left {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
}

/* ── 工具栏按钮通用 ── */
.tb-btn {
  cursor: pointer; font-family: var(--font-ui);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-btn);
  background: var(--bg-glass-raised);
  color: var(--text-secondary);
  transition: all var(--transition-fast);
  display: flex; align-items: center; justify-content: center;
}
.tb-btn:hover { background: var(--bg-glass-hover); color: var(--crimson); border-color: var(--crimson-alpha); }

.tb-text {
  font-size: 12px; padding: 5px 10px; white-space: nowrap;
}

.tb-icon {
  width: 30px; height: 30px; padding: 0;
}

.tb-perm.mode-safe { color: var(--crimson); border-color: var(--crimson-alpha); }
.tb-perm.mode-auto { color: oklch(55% 0.12 75); border-color: oklch(55% 0.12 75 / 0.25); }
.tb-perm.mode-review { color: oklch(50% 0.12 30); border-color: oklch(50% 0.12 30 / 0.25); }

/* ── 上下文用量条 ── */
#usage-inline {
  flex: 0 1 140px; display: flex; align-items: center; gap: 6px;
  padding: 0 16px; min-width: 0;
  margin: 0 auto;
}
#usage-inline .usage-track {
  flex: 1; height: 4px;
  background: var(--border-light);
  border-radius: 2px; overflow: hidden; min-width: 30px;
}
#usage-inline .usage-fill {
  height: 100%;
  background: oklch(48% 0.165 27 / 0.6);
  border-radius: 2px; transition: width 0.4s ease;
}
#usage-inline .usage-val {
  font-size: 10px; color: var(--text-weak);
  font-family: var(--font-mono); white-space: nowrap;
}
#usage-inline .usage-max { color: var(--text-placeholder); }

/* ── 发送按钮 ── */
#send-btn {
  width: 34px; height: 34px; padding: 0; flex-shrink: 0;
  border: none; border-radius: var(--radius-btn);
  background: var(--crimson);
  color: var(--text-on-crimson);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
#send-btn:hover { background: var(--crimson-light); }
#send-btn:disabled { background: var(--border-light); cursor: not-allowed; }
#send-btn.stop {
  background: var(--text-secondary);
  width: auto; padding: 0 14px; font-size: 12px; border-radius: var(--radius-btn);
}
#send-btn.stop:hover { background: var(--text-primary); }

/* ── 附件预览 ── */
#attachments {
  display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px;
}
.attach-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  background: var(--bg-glass-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-btn);
  font-size: 12px;
}
.chip-thumb { width: 24px; height: 24px; object-fit: cover; border-radius: 4px; }
.chip-remove {
  cursor: pointer; color: var(--text-weak);
  display: flex; align-items: center;
  transition: color var(--transition-fast);
}
.chip-remove:hover { color: var(--crimson); }

/* ── Input resize handle ── */
.input-resize-handle {
  height: 4px; cursor: row-resize;
  transition: background var(--transition-fast);
  margin-bottom: 4px;
}
.input-resize-handle:hover,
.input-resize-handle:active {
  background: var(--crimson-alpha);
}
</style>
