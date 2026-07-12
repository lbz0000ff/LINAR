import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BOTTOM_FOLLOW_THRESHOLD,
  SCROLL_BUTTON_THRESHOLD,
  isNearBottom,
  markAnswerStarted,
  shouldShowScrollButton,
} from './chatStreaming.js'

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
