<script setup>
import { ref } from 'vue'

const props = defineProps({
  isProcessing: Boolean,
  permMode: String,
  connected: Boolean,
  usage: Object,
})
const emit = defineEmits(['send', 'stop', 'modeChange'])

const inputText = ref('')
const attachments = ref([])
const cmdOpen = ref(false)
const fileInput = ref(null)

const MODES = ['safe', 'auto', 'review']
const MODE_CLASS = { safe: 'mode-safe', auto: 'mode-auto', review: 'mode-review' }

const COMMANDS = [
  { cmd: '/help', desc: '显示帮助' },
  { cmd: '/reasoning', desc: '切换思考过程显示' },
  { cmd: '/reset', desc: '重置对话' },
  { cmd: '/stop', desc: '停止生成' },
  { cmd: '/jobs', desc: '查看后台任务' },
  { cmd: '/reload_mcp', desc: '重新加载 MCP 工具' },
]

function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

function onSend() {
  if (!inputText.value.trim() || props.isProcessing) return
  if (attachments.value.length) {
    const paths = []
    let pending = attachments.value.length
    attachments.value.forEach(att => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/upload', true)
      xhr.setRequestHeader('X-Filename', encodeURIComponent(att.file.name))
      xhr.onload = () => {
        if (xhr.status === 200) { try { const r = JSON.parse(xhr.responseText); if (r.path) paths.push(r.path) } catch (_) {} }
        pending--; if (!pending) { emit('send', inputText.value, paths); inputText.value = ''; attachments.value = [] }
      }
      xhr.onerror = () => { pending--; if (!pending) { emit('send', inputText.value, paths); inputText.value = ''; attachments.value = [] } }
      xhr.send(att.file._file || att.file)
    })
  } else {
    emit('send', inputText.value, [])
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

function insertCmd(cmd) {
  inputText.value = cmd + ' '
  cmdOpen.value = false
}
</script>

<template>
  <div id="input-area" class="glass-mac">
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

    <!-- Row 1: Input field only -->
    <textarea
      id="input" v-model="inputText" rows="1"
      :placeholder="connected ? '输入消息...' : '未连接 — 等待 WebSocket...'"
      :disabled="!connected"
      @keydown.enter.prevent="!isProcessing && connected && onSend()"
    ></textarea>

    <!-- Row 2: Toolbar -->
    <div id="input-toolbar">
      <div id="toolbar-left">
        <!-- 附件上传 (图标) -->
        <button class="tb-btn tb-icon" @click="fileInput.click()" title="添加附件">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        </button>
        <input ref="fileInput" type="file" multiple style="display:none" @change="onFileChange">

        <!-- 权限等级 (文字) -->
        <button class="tb-btn tb-text tb-perm" :class="MODE_CLASS[permMode] || 'mode-safe'" @click="cycleMode">
          {{ permMode.toUpperCase() }}
        </button>

        <!-- [/] 指令按钮 (斜杠图标) -->
        <div class="cmd-wrapper">
          <button class="tb-btn tb-icon" @click="cmdOpen = !cmdOpen" title="指令">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="4" x2="6" y2="20"/></svg>
          </button>
          <div v-if="cmdOpen" id="cmd-menu">
            <div v-for="c in COMMANDS" :key="c.cmd" class="cmd-item" @click="insertCmd(c.cmd)">
              {{ c.cmd }} <span class="cmd-desc">{{ c.desc }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 上下文用量条 (固定宽度，居中) -->
      <div id="usage-inline" v-if="usage?.prompt_tokens">
        <div class="usage-track"><div class="usage-fill" :style="{ width: Math.min(100, (usage.prompt_tokens / 1000000) * 100) + '%' }"></div></div>
        <span class="usage-val">{{ formatTokens(usage.prompt_tokens) }}<span class="usage-max"> / 1M</span></span>
      </div>

      <!-- 发送按钮 (极简上箭头) -->
      <button
        id="send-btn" :class="{ stop: isProcessing }"
        :disabled="!inputText.trim() && !isProcessing"
        @click="isProcessing ? emit('stop') : onSend()"
      >
        <svg v-if="!isProcessing" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
        <span v-else class="stop-text">停止</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* ── 输入区容器 — Big Sur 毛玻璃 ── */
#input-area {
  padding: 10px 20px 14px;
  border-top: 1px solid var(--border-light);
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

/* ── 上下文用量条 (固定宽度，居中常驻) ── */
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

/* ── 指令菜单 ── */
.cmd-wrapper { position: relative; }
#cmd-menu {
  position: absolute; bottom: 100%; left: 0; margin-bottom: 6px;
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  border: 1px solid var(--border-glass);
  border-radius: var(--radius-btn);
  box-shadow: var(--shadow-overlay);
  z-index: 100; max-height: 240px; overflow-y: auto;
  min-width: 210px;
}
.cmd-item {
  padding: 8px 14px; cursor: pointer; font-size: 13px;
  white-space: nowrap; color: var(--text-primary);
  transition: background var(--transition-fast);
}
.cmd-item:hover { background: var(--crimson-alpha); color: var(--crimson); }
.cmd-desc { color: var(--text-weak); margin-left: 8px; }

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
</style>
