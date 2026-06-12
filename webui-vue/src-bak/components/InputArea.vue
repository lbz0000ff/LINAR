<script setup>
import { ref } from 'vue'

const props = defineProps({ isProcessing: Boolean, permMode: String, connected: Boolean })
const emit = defineEmits(['send', 'stop', 'modeChange', 'settings'])

const inputText = ref('')
const attachments = ref([])
const cmdOpen = ref(false)
const fileInput = ref(null)

const MODES = ['safe', 'auto', 'review']
const MODE_LABELS = { safe: 'SAFE', auto: 'AUTO', review: 'REVIEW' }
const MODE_CLASS = { safe: 'mode-safe', auto: 'mode-auto', review: 'mode-review' }

const COMMANDS = [
  { cmd: '/help', desc: '显示帮助' },
  { cmd: '/reasoning', desc: '切换思考过程显示' },
  { cmd: '/reset', desc: '重置对话' },
  { cmd: '/stop', desc: '停止生成' },
  { cmd: '/jobs', desc: '查看后台任务' },
  { cmd: '/reload_mcp', desc: '重新加载 MCP 工具' },
]

function onSend() {
  if (!inputText.value.trim() || props.isProcessing) return
  // 上传附件
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
  <div id="input-area">
    <div v-if="attachments.length" id="attachments">
      <div v-for="(att, i) in attachments" :key="i" class="attach-chip">
        <img v-if="att.isImage && att.dataUrl" :src="att.dataUrl" class="chip-thumb">
        <span class="chip-name">{{ att.name }}</span>
        <span class="chip-remove" @click="removeAttach(i)">✕</span>
      </div>
    </div>
    <div id="input-row">
      <button id="attach-btn" @click="fileInput.click()" title="上传附件">📎</button>
      <input ref="fileInput" type="file" multiple style="display:none" @change="onFileChange">
      <textarea id="input" v-model="inputText" rows="1"
        :placeholder="connected ? '输入消息...' : '未连接 — 等待 WebSocket...'"
        :disabled="!connected"
        @keydown.enter.prevent="!isProcessing && connected && onSend()"></textarea>
      <button id="send-btn" :class="{ stop: isProcessing }" :disabled="(!inputText.trim() && !isProcessing) || !connected"
        @click="isProcessing ? emit('stop') : onSend()">
        {{ isProcessing ? '停止' : '发送' }}
      </button>
    </div>
    <div id="input-footer">
      <div style="position:relative">
        <button id="cmd-btn" @click="cmdOpen = !cmdOpen">/ 指令</button>
        <div v-if="cmdOpen" id="cmd-menu">
          <div v-for="c in COMMANDS" :key="c.cmd" class="cmd-item" @click="insertCmd(c.cmd)">
            {{ c.cmd }} <span class="cmd-desc">{{ c.desc }}</span>
          </div>
        </div>
      </div>
      <button id="perm-btn" :class="MODE_CLASS[permMode] || 'mode-safe'"
        @click="cycleMode">{{ permMode.toUpperCase() }}</button>
      <button id="settings-btn" @click="emit('settings')">⚙</button>
    </div>
  </div>
</template>

<style scoped>
#input-area {
  padding: 10px 20px 14px;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
  border-top: 1px solid var(--border-light);
}
#attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.attach-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  background: var(--bg-glass-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  font-size: 12px;
}
.chip-thumb { width: 24px; height: 24px; object-fit: cover; border-radius: 4px; }
.chip-remove { cursor: pointer; font-size: 14px; color: var(--text-weak); transition: color var(--transition-fast); }
.chip-remove:hover { color: var(--crimson); }
#input-row { display: flex; align-items: flex-end; gap: 8px; }
#attach-btn {
  cursor: pointer; background: var(--bg-glass-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 8px; font-size: 16px; line-height: 1;
  transition: all var(--transition-fast);
  width: 38px; height: 38px;
  display: flex; align-items: center; justify-content: center;
}
#attach-btn:hover { background: var(--bg-glass-hover); border-color: var(--crimson-alpha); }
#input {
  flex: 1; resize: none;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  font-size: 14px; font-family: var(--font-ui);
  line-height: 1.5; max-height: 25vh;
  background: var(--bg-glass-raised);
  color: var(--text-primary);
  outline: none;
  transition: border-color var(--transition-fast);
}
#input:focus { border-color: var(--crimson); box-shadow: 0 0 0 3px var(--crimson-alpha); }
#input:disabled { opacity: 0.5; cursor: not-allowed; }
#input::placeholder { color: var(--text-placeholder); }
#send-btn {
  padding: 0; width: 38px; height: 38px;
  border: none; border-radius: 50%;
  background: var(--crimson);
  color: var(--text-on-crimson);
  cursor: pointer; font-size: 16px;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}
#send-btn:hover { transform: scale(1.05); box-shadow: 0 2px 12px var(--crimson-glow); }
#send-btn.stop {
  background: var(--text-secondary);
  border-radius: var(--radius-md);
  width: auto; padding: 0 14px; font-size: 12px;
}
#send-btn.stop:hover { transform: none; box-shadow: none; }
#send-btn:disabled { background: var(--border-light); cursor: not-allowed; }
#send-btn:disabled:hover { transform: none; box-shadow: none; }
#input-footer {
  display: flex; align-items: center; gap: 6px;
  margin-top: 6px; font-size: 12px; color: var(--text-weak);
}
#cmd-btn {
  cursor: pointer; background: var(--bg-glass-raised);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 4px 10px; font-size: 12px; font-family: var(--font-ui);
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}
#cmd-btn:hover { background: var(--bg-glass-hover); color: var(--crimson); }
#cmd-menu {
  position: absolute; bottom: 100%; left: 0;
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  border: 1px solid var(--border-glass);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-raised);
  z-index: 100; max-height: 240px; overflow-y: auto;
  min-width: 200px;
}
.cmd-item {
  padding: 8px 14px; cursor: pointer; font-size: 13px;
  white-space: nowrap; color: var(--text-primary);
  transition: background var(--transition-fast);
}
.cmd-item:hover { background: var(--crimson-alpha); color: var(--crimson); }
.cmd-desc { color: var(--text-weak); margin-left: 8px; }
#perm-btn {
  font-size: 11px; padding: 4px 10px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  cursor: pointer; font-family: var(--font-ui);
  background: var(--bg-glass-raised);
  white-space: nowrap; color: var(--text-secondary);
  transition: all var(--transition-fast);
}
#perm-btn.mode-safe { color: var(--crimson); border-color: var(--crimson-alpha); }
#perm-btn.mode-auto { color: oklch(55% 0.12 75); border-color: oklch(55% 0.12 75 / 0.25); }
#perm-btn.mode-review { color: oklch(50% 0.12 30); border-color: oklch(50% 0.12 30 / 0.25); }
#settings-btn {
  cursor: pointer; background: none; border: none;
  font-size: 16px; margin-left: auto;
  color: var(--text-weak); transition: color var(--transition-fast);
  padding: 4px 8px; border-radius: var(--radius-sm);
}
#settings-btn:hover { color: var(--crimson); background: var(--crimson-alpha); }
</style>
