<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { onMessage, offMessage, send, connected } from './composables/useWebSocket.js'
import { marked } from 'marked'
import mermaid from 'mermaid'
import hljs from 'highlight.js'
import katex from 'katex'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'
import Sidebar from './components/Sidebar.vue'
import InputArea from './components/InputArea.vue'
import SettingsPage from './components/SettingsPage.vue'

marked.setOptions({ breaks: true, gfm: true })
mermaid.initialize({ startOnLoad: false, theme: 'base' })

// ── 状态 ──
const sessions = ref([])
const messages = ref([])
const currentSessionId = ref(null)
const isNewSession = ref(false)
const pendingMsg = ref('')
const isProcessing = ref(false)
const chatTitle = ref('选择会话')
const usage = ref(null)
const lastFilePaths = ref([])
const showSettings = ref(false)
const permMode = ref('safe')
const darkMode = ref(false)

// ── WS 消息分发 ──
function handleMessage(event) {
  const t = event.type
  if (t === 'sessions' && event.data) loadSessions(event.data)
  else if (t === 'session_msgs' && event.data) {
    messages.value = convertDbMessages(event.data).map(m => ({ ...m, collapsed: true }))
    if (event.title) chatTitle.value = event.title
    postRender()
  }
  else if (t === 'new_session_created') {
    if (isNewSession.value) { currentSessionId.value = event.session_id; isNewSession.value = false }
    send('list_sessions', {})
    send('switch_session', { id: event.session_id })
    if (pendingMsg.value) { send('message', { data: pendingMsg.value }); pendingMsg.value = '' }
  }
  else if (t === 'token') handleToken(event.data || '')
  else if (t === 'reasoning_token') handleReasoning(event.data || '')
  else if (t === 'tool_call') handleToolCall(event)
  else if (t === 'tool_result') handleToolResult(event)
  else if (t === 'error') addMessage({ role: 'system', text: '⚠ ' + (event.data || '') })
  else if (t === 'done') { /* streaming done, wait for complete */ }
  else if (t === 'complete') handleComplete()
  else if (t === 'usage') { usage.value = event.data }
  else if (t === 'skill_loaded') addMessage({ role: 'notification', text: '技能加载: ' + (event.data?.name || '') })
  else if (t === 'permission_request') handlePermission(event)
  else if (t === 'promise_resolved') addMessage({ role: 'notification', text: '异步任务完成: ' + (event.data?.id || '') })
  else if (t === 'plan_start') { planText.value = ''; addMessage({ role: 'plan', _text: '', _open: true }) }
  else if (t === 'plan') { const last = messages.value[messages.value.length - 1]; if (last?.role === 'plan') { last._text += (event.data || ''); messages.value = [...messages.value] } }
  else if (t === 'plan_complete') { const last = messages.value[messages.value.length - 1]; if (last?.role === 'plan') { last._open = false; messages.value = [...messages.value] } }
  else if (t === 'config_json') handleConfig(event.data || {})
}

function convertDbMessages(dbMsgs) {
  return (dbMsgs || []).map(m => {
    const text = m.content || ''
    const filePaths = extractFilePaths(text)
    const cleanText = stripFileTags(text)
    const role = m.role === 'agent' ? 'ai' : (m.role || 'user')
    const base = {
      role, text: cleanText, _rawText: text,
      tool_name: m.tool_name || '', reasoning: m.reasoning || '',
      tool_call_id: m.tool_call_id || '', tool_calls: m.tool_calls || '',
      created_at: m.created_at || '', _filePaths: filePaths,
    }
    // Reconstruct tool call state from stored JSON content
    if (role === 'tool' && text) {
      try {
        const parsed = JSON.parse(text)
        base.args = parsed.args || {}
        const r = typeof parsed.result === 'string' ? parsed.result : ''
        base.result = r.length > 2000 ? r.slice(0, 2000) + '...' : r
        base.status = 'done'
      } catch (_) {
        base.args = {}
        base.result = text.slice(0, 2000)
        base.status = 'done'
      }
    }
    // Render markdown for AI messages on load
    if (role === 'ai' && cleanText) {
      base.text = renderMd(cleanText)
    }
    return base
  })
}

function addMessage(msg) { messages.value.push(msg) }

// ── 渲染函数 ──
function renderMd(text) {
  if (!text) return ''
  // Pre-process: render block math $$...$$ before marked
  let processed = stripFileTags(text)
  processed = processed.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    try { return `<div class="math-block">${katex.renderToString(math.trim(), { displayMode: true, throwOnError: false })}</div>` }
    catch (_) { return `$$${math}$$` }
  })
  // Inline math $...$ (avoid matching dollars in code blocks)
  processed = processed.replace(/`[^`]*`/g, m => m.replace(/\$/g, '\x00')) // temporarily protect inline code
  processed = processed.replace(/(?<!\$)\$(\S[\s\S]*?\S)\$(?!\$)/g, (_, math) => {
    try { return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false }) }
    catch (_) { return `$${math}$` }
  })
  processed = processed.replace(/\x00/g, '$') // restore protected dollars
  try { return marked.parse(processed, { async: false }) } catch (_) { return escapeHtml(text) }
}
function escapeHtml(s) {
  if (!s) return ''
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}
function stripFileTags(text) { return (text || '').replace(/\[file:[^\]]*\]/g, '').trim() }

// ── DOM 后处理：高亮、复制按钮、Mermaid ──
function postRender() {
  nextTick(() => {
    try {
      // highlight.js
      document.querySelectorAll('.msg-content pre code').forEach(block => {
        hljs.highlightElement(block)
        // Copy button
        const pre = block.parentElement
        if (!pre.querySelector('.copy-btn')) {
          const btn = document.createElement('button')
          btn.className = 'copy-btn'
          btn.textContent = '📋'
          btn.title = '复制代码'
          btn.onclick = () => {
            navigator.clipboard.writeText(block.textContent)
            btn.textContent = '✓'
            setTimeout(() => btn.textContent = '📋', 2000)
          }
          pre.style.position = 'relative'
          pre.appendChild(btn)
        }
      })
    } catch (_) {}
    try { mermaid.run({ nodes: document.querySelectorAll('.mermaid') }) } catch (_) {}
  })
}
function extractFilePaths(text) {
  const r = []; const re = /\[file:([^\]]*)\]/g; let m
  while ((m = re.exec(text || '')) !== null) { const p = m[1].trim(); if (p) r.push(p) }
  return r
}
function renderFileAttachments(paths) {
  if (!paths || !paths.length) return ''
  return paths.map(p => {
    const isImg = /\.(png|jpg|jpeg|gif|webp|bmp|svg)$/i.test(p)
    if (isImg) {
      const url = '/raw-file/' + encodeURIComponent(p.replace(/\\/g, '/'))
      return '<div class="msg-image"><img src="' + url + '" style="max-width:100%;max-height:300px;border-radius:8px;cursor:pointer" onclick="window.open(this.src,\'_blank\')"></div>'
    }
    return '<div class="msg-image">📄 ' + escapeHtml(p) + '</div>'
  }).join('')
}

const planText = ref('')
const planEl = ref(null)

// ── 会话管理 ──
function loadSessions(data) {
  sessions.value = data || []
  if (!currentSessionId.value && sessions.value.length)
    switchSession(sessions.value[0].id)
}
function switchSession(id) {
  if (isProcessing.value) { send('stop', {}); isProcessing.value = false }
  currentSessionId.value = id; isNewSession.value = false
  messages.value = []
  chatTitle.value = sessions.value.find(s => s.id === id)?.title || '会话 #' + id
  usage.value = null
  send('switch_session', { id })
  send('get_session', { id })
}
function newSession() {
  if (isProcessing.value) return
  currentSessionId.value = null; isNewSession.value = true
  messages.value = []; chatTitle.value = '新对话'
}
function deleteSession(id) {
  send('delete_session', { id })
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) {
    currentSessionId.value = null; messages.value = []
    chatTitle.value = '选择会话'
    if (sessions.value.length) switchSession(sessions.value[0].id)
  }
}
function renameSession(id, title) {
  send('rename_session', { id, title })
  const s = sessions.value.find(s => s.id === id)
  if (s) s.title = title
  if (currentSessionId.value === id) chatTitle.value = title
}

// ── 流式处理 ──
function ensureAiMessage() {
  const last = messages.value[messages.value.length - 1]
  if (!last || (last.role !== 'ai' && last.role !== 'streaming')) {
    const msg = { role: 'streaming', text: '', reasoning: '', collapsed: true }
    messages.value.push(msg)
    return msg
  }
  return last
}

function handleToken(text) {
  isProcessing.value = true
  const msg = ensureAiMessage()
  if (!msg._fullText) msg._fullText = ''
  msg._fullText += text
  msg.text = renderMd(msg._fullText)
  messages.value = [...messages.value]
}

function handleReasoning(text) {
  isProcessing.value = true
  const msg = ensureAiMessage()
  if (!msg._reasonBuffer) msg._reasonBuffer = ''
  msg._reasonBuffer += text
  msg.reasoning = msg._reasonBuffer
  msg.collapsed = false
  messages.value = [...messages.value]
}

function handleToolCall(event) {
  isProcessing.value = true
  const name = event.name || '未知'
  let args = {}
  try { args = JSON.parse(event.arguments || '{}') } catch (_) { args = event.arguments || {} }
  if (name === 'ask_user') {
    messages.value.push({ role: 'ask_user', prompt: args.prompt || '', choices: args.choices || [], _answered: false, _customInput: '' })
    return
  }
  messages.value.push({ role: 'tool', tool_name: name, args, result: null, status: 'running' })
}

function handleToolResult(event) {
  let resultStr = typeof event.result === 'string' ? event.result : JSON.stringify(event.result || '')
  if (resultStr.length > 200) resultStr = resultStr.slice(0, 200) + '...'
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'tool' && m.tool_name === event.name && m.status === 'running') {
      m.result = resultStr; m.status = 'done'
      messages.value = [...messages.value]; return
    }
  }
}

function handleComplete() {
  isProcessing.value = false
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'streaming') {
    // 最终渲染：用完整的原始文本渲染 markdown
    const fullText = last._fullText || last._buffer || ''
    const filePaths = (lastFilePaths.value || []).concat(extractFilePaths(fullText))
    last.text = renderMd(fullText) + renderFileAttachments(filePaths)
    last.role = 'ai'
    messages.value = [...messages.value]
    postRender()
  }
  lastFilePaths.value = []
}

// ── 权限审批 ──
function handlePermission(event) {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'tool' && m.tool_name === event.tool_name && m.status === 'running') {
      m.needsApproval = true; messages.value = [...messages.value]; return
    }
  }
}
function approveTool(idx, action) {
  const m = messages.value[idx]
  if (!m) return
  m.needsApproval = false
  m.approveResult = action.includes('allow') ? '✓ 已允许' : '✗ 已拒绝'
  messages.value = [...messages.value]
  send('permission_response', { action })
}

// ── ask_user 回答 ──
function answerAskUser(idx, val) {
  const m = messages.value[idx]
  if (!m || m._answered) return
  m._answered = true
  if (m.choices?.length) m.choices = m.choices.map((c, i) => ({ text: c, selected: c === val }))
  send('ask_user_response', { response: val || m._customInput || '' })
  messages.value = [...messages.value]
}

// ── 发送/停止 ──
function onSend(text, files) {
  if (!text.trim() || isProcessing.value || !connected.value) return
  const filePaths = files || []
  let msgText = text
  if (filePaths.length) msgText += ' ' + filePaths.map(p => '[file:' + p + ']').join('')
  addMessage({ role: 'user', text })
  if (filePaths.length) lastFilePaths.value = filePaths
  if (isNewSession.value || !currentSessionId.value) {
    pendingMsg.value = msgText; send('new_session', { files: filePaths })
  } else {
    send('message', { data: msgText, files: filePaths })
  }
  isProcessing.value = true
}
function onStop() {
  send('stop', {}); isProcessing.value = false
}
function toggleDarkMode() {
  darkMode.value = !darkMode.value
  document.body.style.background = darkMode.value ? '#1a1a2e' : '#f5f5f5'
}

// ── 设置 ──
function handleConfig(cfg) {}

onMounted(() => onMessage(handleMessage))
onUnmounted(() => offMessage(handleMessage))
</script>

<template>
  <div id="app-layout" :class="{ dark: darkMode }">
    <Sidebar
      :sessions="sessions" :current-id="currentSessionId"
      @switch="switchSession" @new="newSession"
      @delete="deleteSession" @rename="renameSession"
      @dark-toggle="toggleDarkMode"
    />
    <main id="chat-area">
      <header id="chat-header">
        <span id="chat-title">{{ chatTitle }}</span>
        <span v-if="isProcessing" id="processing-hint">Agent 工作中...</span>
      </header>
      <div id="messages">
        <div v-for="(msg, idx) in messages" :key="idx" :class="'msg msg-' + (msg.role === 'streaming' ? 'ai' : msg.role)">

          <!-- 用户 -->
          <div v-if="msg.role === 'user'" class="msg-user-bubble">
            <div class="msg-content">{{ msg.text }}</div>
          </div>

          <!-- AI / streaming -->
          <div v-else-if="msg.role === 'ai' || msg.role === 'streaming'" class="msg-ai-bubble">
            <div v-if="msg.reasoning" class="msg-reasoning" :data-expanded="!msg.collapsed">
              <div class="reasoning-toggle" @click="msg.collapsed = !msg.collapsed; messages = [...messages]">💭 思考过程</div>
              <div v-show="!msg.collapsed" class="reasoning-text">{{ msg.reasoning }}</div>
            </div>
            <div v-if="msg.text" class="msg-content" v-html="msg.text"></div>
            <!-- 历史消息中的文件附件 -->
            <div v-if="msg._filePaths?.length" v-html="renderFileAttachments(msg._filePaths)"></div>
          </div>

          <!-- 工具调用 -->
          <div v-else-if="msg.role === 'tool'" class="msg-tool-bubble" :data-tool-name="msg.tool_name">
            <div class="tool-header">
              ⚙ {{ msg.tool_name }}
              <span v-if="msg.status === 'running'" class="tool-status">⟳ 处理中...</span>
              <span v-else class="tool-status done">✓ 完成</span>
            </div>
            <div v-if="msg.args && Object.keys(msg.args).length" class="tool-params">
              <span class="collapse-toggle" @click="msg._showArgs = !msg._showArgs">{{ msg._showArgs ? '▼' : '▶' }} 参数</span>
              <pre v-show="msg._showArgs">{{ JSON.stringify(msg.args, null, 2) }}</pre>
            </div>
            <div v-if="msg.needsApproval" class="tool-perm-section">
              <div class="tool-perm-label">🔑 需要审批</div>
              <div class="tool-perm-buttons">
                <button class="perm-btn allow" @click="approveTool(idx, 'allow_once')">✓</button>
                <button class="perm-btn deny" @click="approveTool(idx, 'deny_once')">✗</button>
                <button class="perm-btn allow" @click="approveTool(idx, 'allow_session')">✓✓</button>
                <button class="perm-btn deny" @click="approveTool(idx, 'deny_session')">✗✗</button>
              </div>
            </div>
            <div v-if="msg.approveResult" class="tool-perm-result" :class="msg.approveResult.includes('允许') ? 'approved' : 'denied'">{{ msg.approveResult }}</div>
            <div v-if="msg.result" class="tool-result-detail">
              <span class="collapse-toggle" @click="msg._showResult = !msg._showResult">{{ msg._showResult ? '▼' : '▶' }} 结果</span>
              <pre v-show="msg._showResult">{{ msg.result }}</pre>
            </div>
          </div>

          <!-- ask_user -->
          <div v-else-if="msg.role === 'ask_user'" class="msg-tool-bubble ask-card">
            <div class="tool-header">❓ ask_user</div>
            <div class="ask-prompt">{{ msg.prompt }}</div>
            <div v-if="msg.choices?.length" class="ask-options">
              <button v-for="(c, ci) in msg.choices" :key="ci" class="ask-option"
                :disabled="msg._answered" @click="answerAskUser(idx, c)">
                <span class="ask-num">{{ ci + 1 }}</span> {{ typeof c === 'string' ? c : c.text }}
              </button>
            </div>
            <div class="ask-custom">
              <input v-model="msg._customInput" placeholder="输入自定义回复..." :disabled="msg._answered" @keydown.enter="answerAskUser(idx, msg._customInput)">
              <button :disabled="msg._answered" @click="answerAskUser(idx, msg._customInput)">发送</button>
            </div>
          </div>

          <!-- 规划 -->
          <div v-else-if="msg.role === 'plan'" class="msg-plan">
            <div class="plan-toggle" @click="msg._open = !msg._open; messages = [...messages]">
              📋 {{ msg._open ? '收起规划' : '展开规划' }}
            </div>
            <div v-show="msg._open" class="plan-body"><pre>{{ msg._text }}</pre></div>
          </div>

          <!-- 系统 -->
          <div v-else-if="msg.role === 'system' || msg.role === 'notification'" class="msg-system">{{ msg.text }}</div>
        </div>
        <!-- Token 用量条 -->
        <div v-if="usage?.total_tokens" id="usage-bar">
          <span>{{ usage.total_tokens }} tokens</span>
          <div class="usage-track"><div class="usage-fill" :style="{ width: Math.min(100, (usage.total_tokens / 128000) * 100) + '%' }"></div></div>
          <span>{{ Math.min(100, Math.round((usage.total_tokens / 128000) * 100)) }}%</span>
        </div>
      </div>
      <InputArea
        :is-processing="isProcessing" :perm-mode="permMode"
        @send="onSend" @stop="onStop"
        @mode-change="permMode = $event; send('switch_permission_mode', { mode: $event })"
        @settings="showSettings = true"
      />
    </main>
    <SettingsPage v-if="showSettings" @close="showSettings = false" @dark-mode="toggleDarkMode" />
  </div>
</template>

<style>
/* ── 布局 ── */
#app-layout { display: flex; height: 100%; width: 100%; }

/* ── 聊天面板 ── */
#chat-area {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
  background: var(--bg-glass-raised); margin: 8px 8px 8px 0;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-glass);
  box-shadow: var(--shadow-glass);
  overflow: hidden;
}
#chat-header {
  display: flex; align-items: center; padding: 14px 20px;
  border-bottom: 1px solid var(--border-light); gap: 8px;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.3);
}
#chat-title { font-weight: 600; font-size: 15px; flex: 1; color: var(--text-primary); }
#processing-hint { font-size: 12px; color: var(--text-weak); }

/* ── 消息容器 ── */
#messages {
  flex: 1; overflow-y: auto; padding: 20px 24px;
  display: flex; flex-direction: column; gap: 16px; min-height: 0;
}

/* ── 消息通用 ── */
.msg { max-width: 82%; line-height: 1.6; animation: msgIn 300ms ease-out; }
@keyframes msgIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── 用户气泡 ── */
.msg-user-bubble {
  align-self: flex-end;
  background: var(--crimson); color: var(--text-on-crimson);
  padding: 10px 16px;
  border-radius: 16px 16px 4px 16px;
  white-space: pre-wrap; word-break: break-word;
  box-shadow: 0 2px 8px var(--crimson-glow);
}

/* ── AI 气泡 ── */
.msg-ai-bubble { align-self: flex-start; max-width: 85%; }
.msg-ai-bubble .msg-content {
  background: var(--bg-ai-bubble);
  padding: 12px 16px;
  border-radius: 16px 16px 16px 4px;
  border: 1px solid var(--border-light);
  font-family: var(--font-serif);
  font-size: 14.5px;
  line-height: 1.7;
}
.msg-content { white-space: pre-wrap; word-break: break-word; }
.msg-content p { margin: 6px 0; }
.msg-content p:first-child { margin-top: 0; }
.msg-content p:last-child { margin-bottom: 0; }
.msg-content pre {
  background: oklch(30% 0.005 250 / 0.06);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 12px 16px; overflow-x: auto; margin: 10px 0;
  font-family: var(--font-mono); font-size: 13px;
}
.msg-content code {
  font-family: var(--font-mono); font-size: 13px;
}
.msg-content p > code, .msg-content li > code {
  background: oklch(48% 0.165 27 / 0.08);
  color: var(--crimson);
  padding: 1px 6px; border-radius: 4px; font-size: 13px;
}

/* ── 思考过程 ── */
.msg-reasoning { margin-bottom: 6px; }
.reasoning-toggle {
  font-size: 12px; color: var(--text-weak);
  user-select: none; cursor: pointer;
  padding: 4px 8px; border-radius: var(--radius-sm);
  display: inline-block; transition: background var(--transition-fast);
}
.reasoning-toggle:hover { background: var(--crimson-alpha); }
.reasoning-text {
  font-size: 12.5px; color: var(--text-secondary);
  font-style: italic;
  padding: 6px 0 6px 14px;
  border-left: 2px solid var(--border-glass);
  margin-top: 4px; white-space: pre-wrap;
  font-family: var(--font-ui);
}

/* ── 工具调用气泡 ── */
.msg-tool-bubble {
  align-self: flex-start; max-width: 92%;
  background: var(--bg-tool-bubble);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 10px 14px; font-size: 13px;
}
.tool-header { font-weight: 500; margin-bottom: 4px; color: var(--text-primary); }
.tool-status { font-size: 12px; color: var(--text-weak); margin-left: 6px; }
.tool-status.done { color: var(--crimson); }
.tool-params {
  margin-top: 6px; padding-top: 6px;
  border-top: 1px solid var(--border-light);
}
.tool-params pre {
  font-size: 11.5px; background: oklch(0% 0 0 / 0.04);
  padding: 6px 8px; border-radius: var(--radius-sm);
  overflow-x: auto; font-family: var(--font-mono);
}

/* ── 权限审批 ── */
.tool-perm-section {
  margin-top: 8px; padding-top: 8px;
  border-top: 1px solid var(--border-light);
}
.tool-perm-label { font-size: 11px; color: var(--text-weak); margin-bottom: 6px; }
.tool-perm-buttons { display: flex; gap: 6px; }
.perm-btn {
  padding: 4px 12px; border: 1px solid var(--border-glass);
  border-radius: var(--radius-sm); cursor: pointer; font-size: 12px;
  background: var(--bg-glass); transition: all var(--transition-fast);
}
.perm-btn:hover { background: var(--bg-glass-hover); }
.perm-btn.allow { color: var(--crimson); border-color: var(--crimson-alpha); }
.perm-btn.deny { color: var(--text-primary); border-color: var(--border-glass); }
.tool-perm-result {
  font-size: 12px; margin-top: 6px; padding: 4px 10px;
  border-radius: var(--radius-sm);
}
.tool-perm-result.approved { color: var(--crimson); background: var(--crimson-alpha); }
.tool-perm-result.denied { color: var(--text-weak); background: oklch(0% 0 0 / 0.04); }

/* ── 工具结果 ── */
.tool-result-detail {
  margin-top: 6px; padding-top: 6px;
  border-top: 1px solid var(--border-light);
}
.tool-result-detail pre {
  font-size: 11.5px; background: oklch(0% 0 0 / 0.04);
  padding: 6px 8px; border-radius: var(--radius-sm);
  overflow-x: auto; font-family: var(--font-mono);
}

/* ── Collapse Toggle ── */
.collapse-toggle {
  cursor: pointer; font-size: 12px; color: var(--text-weak);
  user-select: none; transition: color var(--transition-fast);
}
.collapse-toggle:hover { color: var(--crimson); }

/* ── ask_user 卡片 ── */
.ask-card .ask-prompt { font-size: 14px; margin: 8px 0; color: var(--text-primary); }
.ask-options { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.ask-option {
  text-align: left; padding: 8px 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-glass);
  cursor: pointer; font-size: 13px; font-family: var(--font-ui);
  transition: all var(--transition-fast);
}
.ask-option:disabled { opacity: 0.35; cursor: default; }
.ask-option:hover:not(:disabled) {
  background: var(--crimson-alpha);
  border-color: var(--crimson-alpha);
  color: var(--crimson);
}
.ask-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--crimson-alpha);
  color: var(--crimson);
  font-size: 11px; font-weight: 600;
  margin-right: 8px;
}
.ask-custom { display: flex; gap: 8px; margin-top: 8px; }
.ask-custom input {
  flex: 1; padding: 8px 10px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  font-size: 13px; font-family: var(--font-ui);
  background: var(--bg-glass);
  color: var(--text-primary);
  outline: none; transition: border-color var(--transition-fast);
}
.ask-custom input:focus { border-color: var(--crimson); }
.ask-custom button {
  padding: 8px 16px;
  border: 1px solid var(--crimson);
  border-radius: var(--radius-md);
  background: var(--crimson);
  color: var(--text-on-crimson);
  cursor: pointer; font-size: 12px;
  transition: opacity var(--transition-fast);
}
.ask-custom button:hover { opacity: 0.9; }

/* ── 系统通知 ── */
.msg-system {
  align-self: center; font-size: 12px; color: var(--text-weak);
  text-align: center; padding: 2px 16px;
}

/* ── 规划气泡 ── */
.msg-plan {
  align-self: center; max-width: 90%;
  background: var(--bg-plan-bubble);
  border: 1px solid oklch(55% 0.03 220 / 0.2);
  border-radius: var(--radius-md);
  padding: 10px 14px; font-size: 12px;
}
.plan-toggle {
  cursor: pointer; font-size: 12px; color: var(--text-weak);
  user-select: none;
}
.plan-toggle:hover { color: oklch(45% 0.06 220); }
.plan-body pre {
  white-space: pre-wrap; font-size: 11.5px;
  margin-top: 6px; color: var(--text-secondary);
  font-family: var(--font-mono);
}

/* ── 用量条 ── */
#usage-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 20px; font-size: 11px; color: var(--text-weak);
  border-top: 1px solid var(--border-light);
  background: var(--bg-glass);
}
.usage-track { flex: 1; height: 3px; background: var(--border-light); border-radius: 2px; overflow: hidden; }
.usage-fill { height: 100%; background: var(--crimson); border-radius: 2px; transition: width 0.3s ease; }

/* ── 文件附件 ── */
.msg-image { margin-top: 6px; }
.msg-image img {
  max-width: 100%; max-height: 280px;
  border-radius: var(--radius-md);
  cursor: pointer;
  border: 1px solid var(--border-light);
  transition: opacity var(--transition-fast);
}
.msg-image img:hover { opacity: 0.9; }

/* ── Markdown 渲染 ── */
.msg-content ul, .msg-content ol { padding-left: 20px; margin: 6px 0; }
.msg-content li { margin: 3px 0; }
.msg-content blockquote {
  border-left: 3px solid var(--crimson);
  padding: 4px 12px; margin: 8px 0;
  color: var(--text-secondary);
  background: oklch(48% 0.165 27 / 0.04);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.msg-content table {
  border-collapse: collapse; margin: 8px 0; width: 100%;
  font-size: 13px;
}
.msg-content th, .msg-content td {
  border: 1px solid var(--border-light);
  padding: 6px 10px; text-align: left;
}
.msg-content th { background: oklch(0% 0 0 / 0.03); font-weight: 600; }
.msg-content hr { border: none; border-top: 1px solid var(--border-light); margin: 12px 0; }
.msg-content h1, .msg-content h2, .msg-content h3, .msg-content h4 {
  color: var(--text-primary); margin: 12px 0 6px; line-height: 1.3;
}
.msg-content h1 { font-size: 18px; }
.msg-content h2 { font-size: 16px; }
.msg-content h3 { font-size: 15px; }
.msg-content a { color: var(--crimson); text-decoration: none; }
.msg-content a:hover { text-decoration: underline; }

/* ── 复制按钮 ── */
.copy-btn {
  position: absolute; top: 6px; right: 6px;
  background: var(--bg-glass); border: 1px solid var(--border-light);
  border-radius: var(--radius-sm); cursor: pointer;
  padding: 2px 8px; font-size: 13px; line-height: 1.6;
  opacity: 0.5; transition: opacity var(--transition-fast);
  color: var(--text-primary); z-index: 1;
}
.copy-btn:hover { opacity: 1; background: var(--bg-glass-hover); }
.msg-content pre { position: relative; }

/* ── KaTeX 公式 ── */
.math-block { overflow-x: auto; padding: 8px 0; text-align: center; }
.katex { font-size: 1.05em; }
</style>
