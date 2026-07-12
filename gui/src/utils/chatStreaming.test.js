import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  BOTTOM_FOLLOW_THRESHOLD,
  SCROLL_BUTTON_THRESHOLD,
  isNearBottom,
  markAnswerStarted,
  shouldShowScrollButton,
} from './chatStreaming.js'

const appVue = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')

test('session history accepts only the current concrete session', () => {
  const match = appVue.match(/else if \(type === 'session_msgs' && event\.data\) \{([\s\S]*?)\r?\n  \}\r?\n  else if \(type === 'new_session_created'/u)

  assert.ok(match, 'session_msgs branch should be present')
  assert.match(match[1], /if \(\s*event\.session_id == null \|\|\s*currentSessionId\.value == null \|\|\s*Number\(event\.session_id\) !== Number\(currentSessionId\.value\)\s*\) return/u)
})

test('addMessage replaces the messages array reference', () => {
  assert.match(appVue, /function addMessage\(msg\) \{ messages\.value = \[\.\.\.messages\.value, msg\] \}/u)
})

test('manual scroll recovery jumps directly to the latest content', () => {
  const match = appVue.match(/function scrollToBottom\(\) \{([\s\S]*?)\r?\n\}/u)

  assert.ok(match, 'scrollToBottom should be present')
  const scrollToBottom = match[1]

  assert.match(scrollToBottom, /msgContainer\.value\.scrollTop = msgContainer\.value\.scrollHeight/u)
  assert.doesNotMatch(scrollToBottom, /behavior:\s*['"]smooth['"]/u)
})

test('uses a 24 pixel bottom-follow threshold', () => {
  assert.equal(BOTTOM_FOLLOW_THRESHOLD, 24)
  assert.equal(isNearBottom(1000, 776, 200), true)
  assert.equal(isNearBottom(1000, 775, 200), false)
})

test('uses a 200 pixel scroll-button threshold', () => {
  assert.equal(SCROLL_BUTTON_THRESHOLD, 200)
  assert.equal(shouldShowScrollButton(1000, 600, 200), false)
  assert.equal(shouldShowScrollButton(1000, 599, 200), true)
})

test('first answer transition marks and collapses reasoning', () => {
  const message = { reasoning: 'Thinking', collapsed: false }

  assert.equal(markAnswerStarted(message), true)
  assert.equal(message._answerStarted, true)
  assert.equal(message.collapsed, true)
})

test('later answer transitions preserve manual reasoning reopening', () => {
  const message = { reasoning: 'Thinking', collapsed: false }
  markAnswerStarted(message)
  message.collapsed = false

  assert.equal(markAnswerStarted(message), false)
  assert.equal(message._answerStarted, true)
  assert.equal(message.collapsed, false)
})

test('first answer transition without reasoning leaves collapsed unchanged', () => {
  const message = { collapsed: false }

  assert.equal(markAnswerStarted(message), true)
  assert.equal(message._answerStarted, true)
  assert.equal(message.collapsed, false)
})
