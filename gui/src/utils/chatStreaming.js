export const BOTTOM_FOLLOW_THRESHOLD = 24
export const SCROLL_BUTTON_THRESHOLD = 200

export function bottomDistance(scrollHeight, scrollTop, clientHeight) {
  return Math.max(0, scrollHeight - scrollTop - clientHeight)
}

export function isNearBottom(
  scrollHeight,
  scrollTop,
  clientHeight,
  threshold = BOTTOM_FOLLOW_THRESHOLD,
) {
  return bottomDistance(scrollHeight, scrollTop, clientHeight) <= threshold
}

export function shouldShowScrollButton(scrollHeight, scrollTop, clientHeight) {
  return bottomDistance(scrollHeight, scrollTop, clientHeight) > SCROLL_BUTTON_THRESHOLD
}

export function markAnswerStarted(message) {
  if (message._answerStarted) return false
  message._answerStarted = true
  if (message.reasoning) message.collapsed = true
  return true
}
