/* LINAR — WebSocket composable (Vue reactive)
 * Connects to FastAPI backend via unified /ws endpoint. */

import { ref } from 'vue'

// Electron: direct backend; browser: via Vite proxy / same port
const WS_URL = window.electronAPI?.isElectron
  ? 'ws://127.0.0.1:8080/ws'
  : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`

let ws = null
let reconnectTimer = null
let isClosing = false

export const connected = ref(false)
export const status = ref('disconnected')  // 'connected' | 'disconnected' | 'reconnecting'

// Message handlers registered by components
const messageHandlers = []
export function onMessage(handler) { messageHandlers.push(handler) }
export function offMessage(handler) {
  const i = messageHandlers.indexOf(handler)
  if (i >= 0) messageHandlers.splice(i, 1)
}

function notify(msg) { messageHandlers.forEach(h => h(msg)) }

function _connect() {
  if (ws) { isClosing = true; try { ws.close() } catch (_) {} ws = null; isClosing = false }
  ws = new WebSocket(WS_URL)
  ws.onopen = () => { connected.value = true; status.value = 'connected'; send('list_sessions', {}) }
  ws.onmessage = (e) => { try { notify(JSON.parse(e.data)) } catch (_) {} }
  ws.onclose = () => {
    if (!isClosing) { status.value = 'reconnecting'; reconnectTimer = setTimeout(_connect, 2000) }
    else { connected.value = false; status.value = 'disconnected' }
  }
  ws.onerror = () => {}
}

export function connect() { isClosing = false; _connect() }
export function close() {
  isClosing = true
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) { try { ws.close() } catch (_) {} ws = null }
  connected.value = false; status.value = 'disconnected'
}

export function send(type, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false
  try { ws.send(JSON.stringify(Object.assign({ type }, payload || {}))); return true } catch (_) { return false }
}
