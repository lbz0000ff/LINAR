<script setup>
import { ref, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { onMessage, offMessage, send, connected, status } from './composables/useWebSocket.js'
import { marked } from 'marked'
import mermaid from 'mermaid'
import hljs from 'highlight.js'
import katex from 'katex'
import 'highlight.js/styles/github.css'
import 'katex/dist/katex.min.css'
import Sidebar from './components/Sidebar.vue'
import InputArea from './components/InputArea.vue'
import SettingsPage from './components/SettingsPage.vue'
import TitleBar from './components/TitleBar.vue'
import RightPanel from './components/RightPanel.vue'
import { applyDagNodeComplete, applyDagNodeStart, applySubagentEvent, appendDagPlan, updateDagPlan } from './utils/subagentTrace.js'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

marked.setOptions({ breaks: true, gfm: true })
// Custom renderer: detect ```mermaid blocks
marked.use({
  renderer: {
    code({ text, lang }) {
      if (lang === 'mermaid') return `<div class="mermaid-wrap"><div class="mermaid">${text}</div></div>`
      const langAttr = lang ? ` class="language-${lang}"` : ''
      return `<pre><code${langAttr}>${escapeHtml(text)}</code></pre>`
    }
  }
})
mermaid.initialize({ startOnLoad: false })
// ── 状态 ──
const sessions = ref([])
const messages = ref([])
const currentSessionId = ref(null)
const isNewSession = ref(true)
const pendingMsg = ref('')
const pendingFiles = ref([])
const isProcessing = ref(false)
const chatTitle = ref(t('chat.selectSession'))
const currentSkill = ref(null)
const skillsList = ref([])
const usage = ref(null)
const lastFilePaths = ref([])
const showSettings = ref(false)
const permMode = ref('safe')
const darkMode = ref(false)
// ── 右侧面板 ──
const showRightPanel = ref(false)
const dagNodes = ref({})
const dagGoal = ref('')
const dagActive = ref(false)
const dagPlans = ref([])
const activeDagId = ref('')
let dagSequence = 0
const btwResults = ref([])
const workspacePath = ref('')
const workspaceAssets = ref([])
const msgContainer = ref(null)
const showScrollBtn = ref(false)


function onMsgScroll() {
  if (!msgContainer.value) return
  const el = msgContainer.value
  showScrollBtn.value = el.scrollHeight - el.scrollTop - el.clientHeight > 200
}
function scrollToBottom() {
  if (!msgContainer.value) return
  msgContainer.value.scrollTo({ top: msgContainer.value.scrollHeight, behavior: 'smooth' })
}
// 新消息自动滚动（仅当用户未向上滚动时）
watch(messages, () => {
  nextTick(() => {
    if (!msgContainer.value || showScrollBtn.value) return
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  })
}, { deep: false })

// ── WS 消息分发 ──
function handleMessage(event) {
  const type = event.type
  const scopedTypes = new Set([
    'token', 'reasoning_token', 'tool_call', 'tool_result', 'error',
    'done', 'complete', 'usage', 'skill_loaded', 'permission_request',
    'promise_resolved', 'plan_start', 'plan', 'plan_nodes',
    'plan_execute', 'dag_node_start', 'dag_node_complete',
    'subagent_event',
    'plan_complete', 'plan_error', 'system', 'btw_result',
    'workspace_updated', 'ask_user_request', 'session_context_restored'
  ])
  if (
    event.session_id != null &&
    currentSessionId.value != null &&
    scopedTypes.has(type) &&
    Number(event.session_id) !== Number(currentSessionId.value)
  ) return
  if (type === 'sessions' && event.data) loadSessions(event.data)
  else if (type === 'session_msgs' && event.data) {
    messages.value = convertDbMessages(event.data).map(m => ({ ...m, collapsed: true }))
    if (event.title) chatTitle.value = event.title
    applySessionContext(event.session || {})
    postRender()
  }
  else if (type === 'new_session_created') {
    if (isNewSession.value) { currentSessionId.value = event.session_id; isNewSession.value = false }
    send('list_sessions', {})
    send('switch_session', { id: event.session_id })
    if (pendingMsg.value) { send('message', { data: pendingMsg.value, files: pendingFiles.value }); pendingMsg.value = ''; pendingFiles.value = [] }
  }
  else if (type === 'token') handleToken(event.data || '')
  else if (type === 'reasoning_token') handleReasoning(event.data || '')
  else if (type === 'tool_call') handleToolCall(event)
  else if (type === 'tool_result') handleToolResult(event)
  else if (type === 'error') addMessage({ role: 'system', text: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:-3px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> ' + (event.data || '') })
  else if (type === 'done') { /* streaming done, wait for complete */ }
  else if (type === 'complete') { handleComplete() }
  else if (type === 'usage') { usage.value = event.data }
  else if (type === 'skill_loaded') { currentSkill.value = event.data?.name || null; addMessage({ role: 'notification', text: t('chat.skillLoaded', { name: event.data?.name || '' }) }) }
  else if (type === 'permission_request') handlePermission(event)
  else if (type === 'promise_resolved') addMessage({ role: 'notification', text: t('chat.asyncDone', { id: event.data?.id || '' }) })
  else if (type === 'plan_start') { planText.value = ''; addMessage({ role: 'plan', _text: '', _open: true }); dagNodes.value = {}; dagActive.value = true; dagGoal.value = ''; activeDagId.value = `dag-${Date.now()}-${++dagSequence}`; dagPlans.value = appendDagPlan(dagPlans.value, { id: activeDagId.value }); showRightPanel.value = true }
  else if (type === 'plan') { const last = messages.value[messages.value.length - 1]; if (last?.role === 'plan') { last._text += (event.data || ''); messages.value = [...messages.value] }; dagGoal.value = (event.data || ''); syncActiveDag({ goal: dagGoal.value }) }
  else if (type === 'plan_nodes') { const nodes = event.data || []; const m = {}; nodes.forEach(n => { m[n.id] = { id: n.id, description: n.description, depends_on: n.depends_on || [], hint: n.hint, status: n.status || 'PENDING', result: '' } }); dagNodes.value = m; syncActiveDag({ nodes: m }) }
  else if (type === 'plan_execute') { /* DAG execution begins — nodes will follow */ }
  else if (type === 'dag_node_start') { dagNodes.value = applyDagNodeStart(dagNodes.value, event.data || {}); syncActiveDag({ nodes: dagNodes.value }) }
  else if (type === 'subagent_event') { dagNodes.value = applySubagentEvent(dagNodes.value, event.data || {}); syncActiveDag({ nodes: dagNodes.value }) }
  else if (type === 'dag_node_complete') { dagNodes.value = applyDagNodeComplete(dagNodes.value, event.data || {}); syncActiveDag({ nodes: dagNodes.value }) }
  else if (type === 'plan_complete') { const last = messages.value[messages.value.length - 1]; if (last?.role === 'plan') { last._open = false; messages.value = [...messages.value] }; dagActive.value = false; syncActiveDag({ status: 'COMPLETED', completedAt: Date.now() }) }
  else if (type === 'plan_error') { dagActive.value = false; syncActiveDag({ status: 'FAILED', completedAt: Date.now() }) }
  else if (type === 'skills') skillsList.value = event.data || []
  else if (type === 'system') { addMessage({ role: 'system', text: event.data || '' }) }
  else if (type === 'btw_result') { const d = event.data; btwResults.value = [{ question: d.question, answer: d.answer, ts: Date.now() }, ...btwResults.value]; showRightPanel.value = true }
  else if (type === 'session_context_restored') applySessionContext(event.data || {})
  else if (type === 'workspace_updated') {
    const p = event.data?.path || ''
    workspacePath.value = p
    showRightPanel.value = true
    if (p && window.electronAPI?.listFiles) {
      window.electronAPI.listFiles(p).then(files => { workspaceAssets.value = files })
      window.electronAPI.startWatching?.(p)
    } else {
      workspaceAssets.value = []
    }
  }
  else if (type === 'config_json') handleConfig(event.data || {})
}

function syncActiveDag(changes) {
  if (!activeDagId.value) return
  dagPlans.value = updateDagPlan(dagPlans.value, activeDagId.value, plan => ({ ...plan, ...changes }))
}

function resetDagPlans() {
  dagNodes.value = {}
  dagGoal.value = ''
  dagActive.value = false
  dagPlans.value = []
  activeDagId.value = ''
}

function applySessionContext(session) {
  workspacePath.value = session.workspace_path || ''
  currentSkill.value = session.active_skill || null
  if (!workspacePath.value) workspaceAssets.value = []
}

function convertDbMessages(dbMsgs) {
  return (dbMsgs || []).map(m => {
    const raw = m.content || ''
    let content = raw
    // Try to restore Content Block array stored as JSON
    try { if (typeof raw === 'string' && raw.startsWith('[')) { const p = JSON.parse(raw); if (Array.isArray(p)) content = p } } catch (_) {}
    const role = m.role === 'agent' ? 'ai' : (m.role || 'user')
    const base = {
      role, text: '', _content: content,
      tool_name: m.tool_name || '', reasoning: m.reasoning || '',
      tool_call_id: m.tool_call_id || '', tool_calls: m.tool_calls || '',
      created_at: m.created_at || '',
    }
    // Reconstruct tool call state from stored JSON content
    if (role === 'tool' && typeof raw === 'string') {
      try {
        const parsed = JSON.parse(raw)
        base.args = parsed.args || {}
        const r = typeof parsed.result === 'string' ? parsed.result : ''
        base.result = r.length > 2000 ? r.slice(0, 2000) + '...' : r
        base.status = 'done'
      } catch (_) {
        base.args = {}
        base.result = raw.slice(0, 2000)
        base.status = 'done'
      }
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
function stripFileTags(text) { return (text || '').replace(/\[file:[^\]]*\]/g, '').trim() }  // keep for backward compat
function renderContentBlocks(content) {
  // String (legacy): render as markdown
  if (typeof content === 'string') return renderMd(stripFileTags(content))
  // Content Block array
  if (!Array.isArray(content) || !content.length) return ''
  return content.map(b => {
    if (b.type === 'text') return renderMd(b.text || '')
    if (b.type === 'image_url') {
      const url = b.image_url?.url || ''
      if (url.startsWith('file://')) {
        const path = url.slice(7)
        const displayUrl = '/raw-file/' + encodeURIComponent(path.replace(/\\/g, '/'))
        return `<div class="msg-image"><img src="${displayUrl}" style="max-width:100%;max-height:300px;border-radius:8px;cursor:pointer" onclick="window.open(this.src,'_blank')"></div>`
      }
      if (url.startsWith('data:')) {
        return `<div class="msg-image"><img src="${url}" style="max-width:100%;max-height:300px;border-radius:8px;cursor:pointer"></div>`
      }
      return `<div class="msg-image"><a href="${escapeHtml(url)}" target="_blank">📷 ${escapeHtml(url.split('/').pop() || t('app.imageLabel'))}</a></div>`
    }
    return ''
  }).join('')
}
function formatTokens(n) {
  if (!n) return '0'; if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return String(n)
}
function cacheRate(u) {
  const hit = u?.prompt_cache_hit_tokens || 0; const miss = u?.prompt_cache_miss_tokens || 0
  return hit + miss === 0 ? 0 : Math.round(hit / (hit + miss) * 100)
}

// ── DOM 后处理：高亮、复制按钮、Mermaid ──
function postRender() {
  nextTick(() => {
    try {
      // Make all links open in external browser (not in LINAR's embedded view)
      document.querySelectorAll('.msg-content a[href]').forEach(a => {
        if (!a.getAttribute('target')) {
          a.setAttribute('target', '_blank')
          a.setAttribute('rel', 'noopener noreferrer')
        }
      })
      // highlight.js
      document.querySelectorAll('.msg-content pre code').forEach(block => {
        hljs.highlightElement(block)
        // Copy button
        const pre = block.parentElement
        if (!pre.querySelector('.copy-btn')) {
          const btn = document.createElement('button')
          btn.className = 'copy-btn'
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
          btn.title = t('app.copyCode')
          btn.onclick = () => {
            navigator.clipboard.writeText(block.textContent)
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
            setTimeout(() => btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>', 2000)
          }
          pre.style.position = 'relative'
          pre.appendChild(btn)
          // 语言标签
          if (!pre.querySelector('.code-lang')) {
            const m = block.className.match(/language-(\w+)/)
            if (m?.[1]) {
              const langLabel = document.createElement('span')
              langLabel.className = 'code-lang'
              langLabel.textContent = m[1]
              pre.appendChild(langLabel)
            }
          }
        }
      })
    } catch (_) {}
    try {
      document.querySelectorAll('.mermaid').forEach(el => {
        if (!el.dataset.original) el.dataset.original = el.textContent || ''
      })
      mermaid.run({ nodes: document.querySelectorAll('.mermaid') })
    } catch (_) {}
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
    return '<div class="msg-image"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:-3px;margin-right:4px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' + escapeHtml(p) + '</div>'
  }).join('')
}

const planText = ref('')
const planEl = ref(null)

// ── 会话管理 ──
function loadSessions(data) {
  sessions.value = data || []
  // Start fresh — don't auto-load last session
}
function switchSession(id) {
  if (isProcessing.value) { send('stop', {}); isProcessing.value = false }
  currentSessionId.value = id; isNewSession.value = false
  messages.value = []
  chatTitle.value = sessions.value.find(s => s.id === id)?.title || t('chat.sessionLabel', { id })
  usage.value = null
  currentSkill.value = null
  workspacePath.value = ''
  workspaceAssets.value = []
  resetDagPlans()
  send('switch_session', { id })
  send('get_session', { id })
}
function newSession() {
  if (isProcessing.value) return
  currentSessionId.value = null; isNewSession.value = true
  messages.value = []; chatTitle.value = t('sidebar.newSession')
  currentSkill.value = null
  workspacePath.value = ''
  workspaceAssets.value = []
  resetDagPlans()
}
function deleteSession(id) {
  send('delete_session', { id })
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentSessionId.value === id) {
    currentSessionId.value = null; messages.value = []
    chatTitle.value = t('chat.selectSession')
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
  const name = event.name || t('app.unknown')
  let args = {}
  try { args = JSON.parse(event.arguments || '{}') } catch (_) { args = event.arguments || {} }
  if (name === 'ask_user') {
    messages.value.push({ role: 'ask_user', prompt: args.prompt || '', choices: args.choices || [], _answered: false, _customInput: '' })
    return
  }
  messages.value.push({ role: 'tool', tool_name: name, tool_call_id: event.id || '', args, result: null, status: 'running' })
}

function handleToolResult(event) {
  let resultStr = typeof event.result === 'string' ? event.result : JSON.stringify(event.result || '')
  if (resultStr.length > 200) resultStr = resultStr.slice(0, 200) + '...'
  const id = event.id
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'tool') {
      if (id && m.tool_call_id && m.tool_call_id === id) {
        m.result = resultStr; m.status = 'done'
        messages.value = [...messages.value]; return
      }
      if (!id && m.tool_name === event.name && m.status === 'running') {
        m.result = resultStr; m.status = 'done'
        messages.value = [...messages.value]; return
      }
    }
  }
}

function handleComplete() {
  isProcessing.value = false
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'streaming') {
    const fullText = last._fullText || last._buffer || ''
    // Build Content Block array for rendering
    const blocks = [{ type: 'text', text: fullText }]
    if (lastFilePaths.value?.length) {
      lastFilePaths.value.forEach(p => {
        blocks.push({ type: 'image_url', image_url: { url: 'file://' + p.replace(/\\/g, '/') } })
      })
    }
    last._content = blocks
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
      m.needsApproval = true
      m.permissionSessionId = event.session_id ?? currentSessionId.value
      messages.value = [...messages.value]
      return
    }
  }
}
function approveTool(idx, action) {
  const m = messages.value[idx]
  if (!m) return
  m.needsApproval = false
  const isAllowed = action.includes('allow')
  m.approveResult = isAllowed
    ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:-2px"><polyline points="20 6 9 17 4 12"/></svg> ' + t('chat.permissionAllowed')
    : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="display:inline;vertical-align:-2px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> ' + t('chat.permissionDenied')
  m._isApproved = isAllowed
  messages.value = [...messages.value]
  send('permission_response', {
    action,
    session_id: m.permissionSessionId ?? currentSessionId.value,
  })
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
  const userMsg = { role: 'user', text }
  if (filePaths.length) {
    const blocks = [{ type: 'text', text: text.trim() }]
    filePaths.forEach(p => {
      blocks.push({ type: 'image_url', image_url: { url: 'file://' + p.replace(/\\/g, '/') } })
    })
    userMsg._content = blocks
    lastFilePaths.value = filePaths
  }
  addMessage(userMsg)
  if (isNewSession.value || !currentSessionId.value) {
    pendingMsg.value = text; pendingFiles.value = filePaths
    send('new_session', { files: filePaths })
  } else {
    send('message', { data: text, files: filePaths })
  }
  isProcessing.value = true
}
function onStop() {
  send('stop', {}); isProcessing.value = false
}
function onShowHelp() {
  addMessage({ role: 'system', text: t('chat.availableCommands') })
}
function onToggleReasoning() {
  messages.value.forEach(m => {
    if (m.role === 'ai' || m.role === 'streaming') m.collapsed = !m.collapsed
  })
  messages.value = [...messages.value]
}
function onReset() {
  messages.value = []
  isProcessing.value = false
  usage.value = null
  if (currentSessionId.value) { send('stop', {}); newSession() }
}
function onJobs() {
  send('message', { data: '/jobs' })
  isProcessing.value = true
}
function onReloadMCP() {
  send('reload_mcp', {})
  addMessage({ role: 'notification', text: t('chat.mcpReloading') })
}
function onSteer(msg) {
  send('stop', {})
  send('steer', { data: msg })
  addMessage({ role: 'notification', text: t('chat.steerSent', { msg }) })
  isProcessing.value = false
}
function onBtw(msg) {
  send('btw', { data: msg })
  addMessage({ role: 'notification', text: t('chat.btwSent', { msg }) })
}
function onRefreshSessions() { send('list_sessions', {}) }
function onSwitchToSession(id) {
  const n = Number(id)
  if (n && sessions.value.find(s => s.id === n)) switchSession(n)
}
function onExitApp() {
  if (window.electronAPI?.isElectron) window.electronAPI.close()
}
function toggleDarkMode() {
  darkMode.value = !darkMode.value
  document.body.classList.toggle('dark', darkMode.value)
  try { localStorage.setItem('linar:darkMode', String(darkMode.value)) } catch (_) {}
}

// ── 设置 ──
function handleConfig(cfg) {}

// Request skills when WS connects
watch(connected, (val) => { if (val) send('list_skills', {}) })

onMounted(() => {
  // 恢复深色模式偏好
  try {
    const saved = localStorage.getItem('linar:darkMode')
    if (saved === 'true' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      darkMode.value = true
      document.body.classList.add('dark')
    }
  } catch (_) {}
  onMessage(handleMessage)
  // 监听 workspace 文件变更，自动刷新列表
  if (window.electronAPI?.onFilesChanged) {
    window.electronAPI.onFilesChanged(() => {
      if (workspacePath.value && window.electronAPI?.listFiles) {
        window.electronAPI.listFiles(workspacePath.value).then(files => {
          workspaceAssets.value = files
        })
      }
    })
  }
})
onUnmounted(() => offMessage(handleMessage))
</script>

<template>
  <div id="app-root" :class="{ dark: darkMode }">
    <TitleBar />
    <div id="app-layout">
      <Sidebar
      :sessions="sessions" :current-id="currentSessionId"
      :status="status" :dark-mode="darkMode"
      @switch="switchSession" @new="newSession"
      @delete="deleteSession" @rename="renameSession"
      @dark-toggle="toggleDarkMode"
      @settings="showSettings = true"
    />
    <main id="chat-area" :class="{ 'has-right-panel': showRightPanel }">
      <header id="chat-header">
        <span id="chat-title">{{ chatTitle }}</span>
        <span v-if="currentSkill" id="skill-badge">{{ currentSkill }}</span>
        <button id="panel-toggle" @click="showRightPanel = !showRightPanel"
          :title="showRightPanel ? $t('panel.hide') : $t('panel.show')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline v-if="showRightPanel" points="15 18 9 12 15 6"/>
            <polyline v-else points="9 18 15 12 9 6"/>
          </svg>
        </button>
        <span v-if="isProcessing" id="processing-hint">
          <span class="pulse-dots">
            <span class="pulse-dot"></span><span class="pulse-dot"></span><span class="pulse-dot"></span>
          </span>
          {{ $t('chat.processing') }}
        </span>
      </header>
      <div id="messages" ref="msgContainer" @scroll="onMsgScroll">
        <!-- 空状态 -->
        <div v-if="!currentSessionId && messages.length === 0" class="empty-state">
          <div class="empty-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--crimson)" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" opacity="0.6">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              <line x1="9" y1="9" x2="15" y2="9" stroke="var(--text-weak)"/>
              <line x1="9" y1="13" x2="13" y2="13" stroke="var(--text-weak)"/>
            </svg>
          </div>
          <h2 class="empty-title">LINAR</h2>
          <p class="empty-desc">{{ $t('chat.emptySelect') }}</p>
          <p class="empty-hint">{{ $t('chat.emptyHint') }}</p>
        </div>
        <!-- 消息列表 -->
        <template v-else>
        <div v-for="(msg, idx) in messages" :key="idx" :class="'msg msg-' + (msg.role === 'streaming' ? 'ai' : msg.role)">

          <!-- 用户 -->
          <div v-if="msg.role === 'user'" class="msg-user-bubble">
            <div class="msg-content" v-html="renderContentBlocks(msg._content || msg.text)"></div>
          </div>

          <!-- AI / streaming -->
          <div v-else-if="msg.role === 'ai' || msg.role === 'streaming'" class="msg-ai-bubble">
            <div v-if="msg.reasoning" class="msg-reasoning" :data-expanded="!msg.collapsed">
              <div class="reasoning-toggle" @click="msg.collapsed = !msg.collapsed; messages = [...messages]">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                {{ $t('chat.reasoning') }}
              </div>
              <div v-show="!msg.collapsed" class="reasoning-text">{{ msg.reasoning }}</div>
            </div>
            <div v-if="msg.text || msg._content" class="msg-content" v-html="renderContentBlocks(msg._content || msg.text)"></div>
          </div>

          <!-- 工具调用 -->
          <div v-else-if="msg.role === 'tool'" class="msg-tool-bubble" :data-tool-name="msg.tool_name">
            <div class="tool-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              {{ msg.tool_name }}
              <span v-if="msg.status === 'running'" class="tool-status">{{ $t('chat.toolProcessing') }}</span>
              <span v-else class="tool-status done">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                {{ $t('chat.toolDone') }}
              </span>
            </div>
            <div v-if="msg.args && Object.keys(msg.args).length" class="tool-params">
              <span class="collapse-toggle" @click="msg._showArgs = !msg._showArgs">{{ msg._showArgs ? '▼' : '▶' }} {{ $t('chat.args') }}</span>
              <pre v-show="msg._showArgs">{{ JSON.stringify(msg.args, null, 2) }}</pre>
            </div>
            <div v-if="msg.needsApproval" class="tool-perm-section">
              <div class="tool-perm-label">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777z"/><path d="M12 2v4M12 22v-4M2 12h4M22 12h-4"/></svg>
                {{ $t('chat.needsApproval') }}
              </div>
              <div class="tool-perm-buttons">
                <button class="perm-btn allow" @click="approveTool(idx, 'allow_once')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
                <button class="perm-btn deny" @click="approveTool(idx, 'deny_once')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
                <button class="perm-btn allow" @click="approveTool(idx, 'allow_session')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/><polyline points="20 6 9 17 4 12" transform="translate(3,0)"/></svg>
                </button>
                <button class="perm-btn deny" @click="approveTool(idx, 'deny_session')">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/><line x1="15" y1="3" x2="9" y2="3" transform="translate(3,0)"/><line x1="9" y1="3" x2="15" y2="3" transform="translate(3,0)"/></svg>
                </button>
              </div>
            </div>
            <div v-if="msg.approveResult" class="tool-perm-result" :class="msg._isApproved ? 'approved' : 'denied'" v-html="msg.approveResult"></div>
            <div v-if="msg.result" class="tool-result-detail">
              <span class="collapse-toggle" @click="msg._showResult = !msg._showResult">{{ msg._showResult ? '▼' : '▶' }} {{ $t('chat.result') }}</span>
              <pre v-show="msg._showResult">{{ msg.result }}</pre>
            </div>
          </div>

          <!-- ask_user -->
          <div v-else-if="msg.role === 'ask_user'" class="msg-tool-bubble ask-card">
            <div class="tool-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              ask_user
            </div>
            <div class="ask-prompt">{{ msg.prompt }}</div>
            <div v-if="msg.choices?.length" class="ask-options">
              <button v-for="(c, ci) in msg.choices" :key="ci" class="ask-option"
                :disabled="msg._answered" @click="answerAskUser(idx, c)">
                <span class="ask-num">{{ ci + 1 }}</span> {{ typeof c === 'string' ? c : c.text }}
              </button>
            </div>
            <div class="ask-custom">
              <input v-model="msg._customInput" :placeholder="$t('chat.customReplyPlaceholder')" :disabled="msg._answered" @keydown.enter="answerAskUser(idx, msg._customInput)">
              <button :disabled="msg._answered" @click="answerAskUser(idx, msg._customInput)">{{ $t('chat.send') }}</button>
            </div>
          </div>

          <!-- 规划 -->
          <div v-else-if="msg.role === 'plan'" class="msg-plan">
            <div class="plan-toggle" @click="msg._open = !msg._open; messages = [...messages]">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              {{ msg._open ? $t('chat.planCollapse') : $t('chat.planExpand') }}
            </div>
            <div v-show="msg._open" class="plan-body"><pre>{{ msg._text }}</pre></div>
          </div>

          <!-- 系统 -->
          <div v-else-if="msg.role === 'system' || msg.role === 'notification'" class="msg-system">{{ msg.text }}</div>
        </div>
        <!-- 滚动到底部 FAB -->
        <button v-if="showScrollBtn" class="scroll-bottom-fab" @click="scrollToBottom" :title="$t('chat.scrollToBottom')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        </template>
      </div>
      <InputArea
        :is-processing="isProcessing" :perm-mode="permMode" :connected="connected"
        :usage="usage" :skills="skillsList"
        @send="onSend" @stop="onStop" @show-help="onShowHelp"
        @toggle-reasoning="onToggleReasoning" @reset="onReset"
        @steer="onSteer" @btw="onBtw"
        @refresh-sessions="onRefreshSessions" @switch-to-session="onSwitchToSession"
        @exit-app="onExitApp"
        @mode-change="permMode = $event; send('switch_permission_mode', { mode: $event })"
      />
    </main>
    <RightPanel
      v-if="showRightPanel"
      :dag-nodes="dagNodes" :dag-goal="dagGoal"
      :dag-active="dagActive" :btw-results="btwResults"
      :dag-plans="dagPlans" :active-dag-id="activeDagId"
      :workspace-path="workspacePath"
      :workspace-assets="workspaceAssets"
      @close="showRightPanel = false"
    />
    <SettingsPage v-if="showSettings" @close="showSettings = false" @dark-mode="toggleDarkMode" :dark-mode="darkMode" />
    </div>
  </div>
</template>

<style>
/* ── 布局 ── */
#app-root { display: flex; flex-direction: column; height: 100%; width: 100%; }
#app-layout { display: flex; flex: 1; min-height: 0; }

/* ── 聊天面板 ── */
#chat-area {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
  background: var(--bg-glass); margin: 8px 8px 8px 0;
  border-radius: 0;
  border-top: 1px solid oklch(100% 0 0 / 0.3);
  border-left: 1px solid oklch(100% 0 0 / 0.2);
  border-right: 1px solid oklch(0% 0 0 / 0.06);
  border-bottom: 1px solid oklch(0% 0 0 / 0.08);
  box-shadow: var(--shadow-raised);
  overflow: hidden;
  backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
}
body.dark #chat-area {
  border-top: 1px solid oklch(100% 0 0 / 0.08);
  border-left: 1px solid oklch(100% 0 0 / 0.05);
  border-right: 1px solid oklch(0% 0 0 / 0.15);
  border-bottom: 1px solid oklch(0% 0 0 / 0.2);
}
#chat-area.has-right-panel {
  margin-right: 0;
}
#panel-toggle {
  width: 30px; height: 30px; border-radius: var(--radius-btn);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; background: transparent; border: 1px solid var(--border-light);
  color: var(--text-weak); flex-shrink: 0;
  transition: all var(--transition-fast);
}
#panel-toggle:hover { background: var(--bg-glass-raised); color: var(--crimson); border-color: var(--crimson-alpha); }
#chat-header {
  display: flex; align-items: center; padding: 14px 20px;
  border-bottom: 1px solid var(--border-light); gap: 8px;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.8);
}
#chat-title { font-weight: 600; font-size: 15px; flex: 1; color: var(--text-primary); }
#skill-badge {
  font-size: 11px; font-weight: 600; padding: 2px 8px;
  border-radius: var(--radius-btn);
  background: var(--crimson-alpha);
  color: var(--crimson);
  font-family: var(--font-mono);
}
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
  border-radius: var(--radius-bubble) var(--radius-bubble) 4px var(--radius-bubble);
  white-space: pre-wrap; word-break: break-word;
  box-shadow: 0 2px 8px var(--crimson-glow);
}

/* ── AI 气泡 ── */
.msg-ai-bubble { align-self: flex-start; max-width: 85%; }
.msg-ai-bubble .msg-content {
  background: var(--bg-ai-bubble);
  padding: 12px 16px;
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble) 4px;
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
  border-radius: var(--radius-btn);
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
  padding: 4px 8px; border-radius: var(--radius-btn);
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
  border-radius: var(--radius-bubble);
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
  padding: 6px 8px; border-radius: var(--radius-btn);
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
  border-radius: var(--radius-btn); cursor: pointer; font-size: 12px;
  background: var(--bg-glass); transition: all var(--transition-fast);
}
.perm-btn:hover { background: var(--bg-glass-hover); }
.perm-btn.allow { color: var(--crimson); border-color: var(--crimson-alpha); }
.perm-btn.deny { color: var(--text-primary); border-color: var(--border-glass); }
.tool-perm-result {
  font-size: 12px; margin-top: 6px; padding: 4px 10px;
  border-radius: var(--radius-btn);
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
  padding: 6px 8px; border-radius: var(--radius-btn);
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
  border-radius: var(--radius-btn);
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
  border-radius: var(--radius-btn);
  font-size: 13px; font-family: var(--font-ui);
  background: var(--bg-glass);
  color: var(--text-primary);
  outline: none; transition: border-color var(--transition-fast);
}
.ask-custom input:focus { border-color: var(--crimson); }
.ask-custom button {
  padding: 8px 16px;
  border: 1px solid var(--crimson);
  border-radius: var(--radius-btn);
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
  border-radius: var(--radius-btn);
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
  border-radius: var(--radius-btn);
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
.msg-content a { color: var(--crimson); text-decoration: underline; }
.msg-content a:hover { opacity: 0.8; }
.msg-user-bubble .msg-content a { color: var(--text-on-crimson); }

/* ── 复制按钮 ── */
.copy-btn {
  position: absolute; top: 6px; right: 6px;
  background: var(--bg-glass); border: 1px solid var(--border-light);
  border-radius: var(--radius-btn); cursor: pointer;
  padding: 2px 8px; font-size: 13px; line-height: 1.6;
  opacity: 0.5; transition: opacity var(--transition-fast);
  color: var(--text-primary); z-index: 1;
}
.copy-btn:hover { opacity: 1; background: var(--bg-glass-hover); }
.msg-content pre { position: relative; }

/* ── KaTeX 公式 ── */
.math-block { overflow-x: auto; padding: 8px 0; text-align: center; }
.katex { font-size: 1.05em; }

/* ── Mermaid 固定背景容器（不受暗色模式影响）── */
.mermaid-wrap {
  background: oklch(98% 0.003 60);
  border-radius: var(--radius-md);
  padding: 12px;
  margin: 10px 0;
  overflow-x: auto;
}
body.dark .mermaid-wrap {
  background: oklch(96% 0.004 60);
}

/* ── 空状态 ── */
.empty-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  text-align: center; user-select: none;
  animation: msgIn 400ms ease-out;
  padding: 40px;
}
.empty-icon { margin-bottom: 20px; opacity: 0.7; }
.empty-title {
  font-family: var(--font-serif);
  font-size: 28px; font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 10px; letter-spacing: 0.5px;
}
.empty-desc { font-size: 14px; color: var(--text-secondary); margin-bottom: 6px; }
.empty-hint { font-size: 12px; color: var(--text-weak); }

/* ── 脉冲三点 Agent 指示器 ── */
#processing-hint {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-weak);
}
.pulse-dots { display: flex; gap: 4px; align-items: center; }
.pulse-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--crimson);
  opacity: 0.4;
  animation: dotPulse 1.2s ease-in-out infinite;
}
.pulse-dot:nth-child(2) { animation-delay: 0.2s; }
.pulse-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1.3); }
}

/* ── 滚动到底部 FAB ── */
.scroll-bottom-fab {
  position: sticky; bottom: 8px;
  align-self: center;
  width: 36px; height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border-glass);
  background: var(--bg-glass-raised);
  backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--blur-glass)) saturate(1.4);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-glass);
  transition: all var(--transition-fast);
  z-index: 5;
  animation: msgIn 200ms ease-out;
}
.scroll-bottom-fab:hover {
  background: var(--bg-glass-hover);
  color: var(--crimson);
  border-color: var(--crimson-alpha);
  transform: translateY(-1px);
  box-shadow: var(--shadow-raised);
}

/* ── 代码块语言标签 ── */
.code-lang {
  position: absolute; bottom: 4px; right: 40px;
  font-size: 10px; color: var(--text-weak);
  font-family: var(--font-ui);
  text-transform: uppercase; letter-spacing: 0.08em;
  pointer-events: none; opacity: 0.5;
}

/* ── 代码高亮 — 暗色模式 VSCode 风格 ── */
body.dark .msg-content pre {
  background: oklch(20% 0.005 250);
  border-color: oklch(70% 0.005 250 / 0.1);
}
body.dark .hljs { color: oklch(85% 0.005 250); background: oklch(20% 0.005 250); }
body.dark .hljs-keyword,
body.dark .hljs-selector-tag,
body.dark .hljs-literal,
body.dark .hljs-section,
body.dark .hljs-link { color: oklch(65% 0.15 310); } /* 紫 — 关键字 */
body.dark .hljs-string,
body.dark .hljs-title,
body.dark .hljs-name,
body.dark .hljs-type,
body.dark .hljs-attribute,
body.dark .hljs-symbol,
body.dark .hljs-bullet,
body.dark .hljs-addition,
body.dark .hljs-variable,
body.dark .hljs-template-tag,
body.dark .hljs-template-variable { color: oklch(60% 0.14 145); } /* 青绿 — 字符串 */
body.dark .hljs-comment,
body.dark .hljs-quote,
body.dark .hljs-deletion,
body.dark .hljs-meta { color: oklch(50% 0.005 250); } /* 灰 — 注释 */
body.dark .hljs-number,
body.dark .hljs-regexp,
body.dark .hljs-built_in,
body.dark .hljs-selector-id,
body.dark .hljs-selector-class { color: oklch(60% 0.12 40); } /* 橙 — 数字 */
body.dark .hljs-attr,
body.dark .hljs-params { color: oklch(68% 0.12 85); } /* 黄 — 属性 */
body.dark .hljs-function,
body.dark .hljs-title.function_ { color: oklch(60% 0.15 255); } /* 蓝 — 函数 */
body.dark .hljs-property,
body.dark .hljs-tag { color: oklch(65% 0.08 200); } /* 浅青 — 属性 */
body.dark .hljs-emphasis { font-style: italic; }
body.dark .hljs-strong { font-weight: 600; }
body.dark .msg-content p > code,
body.dark .msg-content li > code {
  background: oklch(58% 0.165 27 / 0.15);
  color: oklch(65% 0.15 25);
}
</style>
