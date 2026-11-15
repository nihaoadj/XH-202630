// Session-only drafts. No answers are sent to telemetry or shared across accounts.
const PREFIX = 'onboarding_draft_v1:'
const MAX_AGE = 24 * 60 * 60 * 1000
const MAX_SIZE = 512000
const memoryDrafts = new Map()
const stages = ['domain', 'track', 'questionnaire', 'diagnosis', 'review']
const object = value => value && typeof value === 'object' && !Array.isArray(value)
function sessionStore(storage) {
  if (storage !== undefined) return storage
  try { return globalThis.sessionStorage } catch { return null }
}

export const isDomainAvailable = domain => domain?.domain_id === 'ai_application' && domain.enabled !== false
export const isTrackAvailable = track => Boolean(track) && track.enabled !== false && track.metadata?.available !== false

export function optionsFor(question) {
  return (question.options || []).map(option => object(option)
    ? { label: option.label ?? option.value ?? '', value: option.value ?? option.label ?? '' }
    : { label: option, value: option })
}

export function exclusiveSelection(next, previous, question) {
  const options = optionsFor(question)
  const allowed = new Set(options.map(option => option.value))
  const values = [...new Set(Array.isArray(next) ? next.filter(value => allowed.has(value)) : [])]
  const exclusive = new Set(question.validation?.exclusive_option_values || [])
  for (const option of options) {
    if (/^(?:以上)?(?:都|均)不(?:了解|知道)$/.test(String(option.label).trim().replace(/^[A-Z][.、．:：)]\s*/i, ''))) exclusive.add(option.value)
  }
  const added = values.filter(value => !(Array.isArray(previous) && previous.includes(value)))
  const lastExclusive = added.filter(value => exclusive.has(value)).at(-1)
  if (lastExclusive !== undefined) return [lastExclusive]
  if (added.length) return values.filter(value => !exclusive.has(value))
  const selectedExclusive = values.find(value => exclusive.has(value))
  return selectedExclusive !== undefined ? [selectedExclusive] : values
}

export function answersFor(questions, saved = {}) {
  return Object.fromEntries(questions.map(question => {
    const value = saved[question.question_id]
    const multiple = (question.type || question.question_type) === 'multiple_choice'
    return [question.question_id, multiple ? exclusiveSelection(value, [], question) : typeof value === 'string' ? value : '']
  }))
}

export function profileMatchesDirection(profile, direction, userId) {
  if (!profile?.learner_id || profile.user_id !== userId || !direction) return false
  const previousDirection = profile.learning_preferences?.metadata?.onboarding?.learning_direction_id
  return profile.knowledge_base_id === (direction.knowledge_base_id || direction.track_id)
    && (!previousDirection || previousDirection === direction.track_id)
}

export async function findDirectionProfiles(list, direction, userId, isCurrent = () => true) {
  const found = new Map()
  const seen = new Set()
  for (let page = 1; page <= 100; page++) {
    const response = await list({ page, page_size: 100 })
    if (!isCurrent()) return null
    const { items, total } = response.data || {}
    if (!Array.isArray(items) || !Number.isInteger(total) || total < 0) throw new Error('学习记录响应不完整，请刷新后重试')
    for (const profile of items) {
      if (typeof profile?.learner_id !== 'string') throw new Error('学习记录响应不完整，请刷新后重试')
      seen.add(profile.learner_id)
      if (profileMatchesDirection(profile, direction, userId)) found.set(profile.learner_id, profile)
    }
    if (seen.size >= total) return [...found.values()].sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')) || a.learner_id.localeCompare(b.learner_id))
    if (!items.length) break
  }
  throw new Error('学习记录未能完整读取，请稍后重试')
}

export function writeDraft(userId, state, storage, now = Date.now()) {
  storage = sessionStore(storage)
  if (!userId) return false
  try {
    const raw = JSON.stringify({ version: 1, userId, savedAt: now, state })
    if (raw.length > MAX_SIZE) return false
    memoryDrafts.set(userId, raw)
    try { storage?.setItem(PREFIX + userId, raw) } catch { /* In-memory navigation recovery remains available. */ }
    return true
  } catch { return false }
}

export function clearDraft(userId, storage) {
  storage = sessionStore(storage)
  memoryDrafts.delete(userId)
  try { storage?.removeItem(PREFIX + userId) } catch { /* Storage may be disabled. */ }
}

export function readDraft(userId, storage, now = Date.now()) {
  storage = sessionStore(storage)
  try {
    let raw = memoryDrafts.get(userId)
    try { raw ||= storage?.getItem(PREFIX + userId) } catch { /* Use this tab's memory only. */ }
    if (!raw || raw.length > MAX_SIZE) return null
    const draft = JSON.parse(raw)
    if (draft.version !== 1 || draft.userId !== userId || !Number.isFinite(draft.savedAt) || now - draft.savedAt > MAX_AGE || draft.savedAt > now + 60000
      || !object(draft.state) || !stages.includes(draft.state.stage) || !object(draft.state.form) || !object(draft.state.diagnosticAnswers)) {
      clearDraft(userId, storage)
      return null
    }
    const questions = draft.state.diagnosticQuestions
    if (questions != null && (!Array.isArray(questions) || questions.length > 100 || questions.some(question => !object(question)
      || typeof question.question_id !== 'string' || typeof question.question !== 'string'
      || (question.options != null && (!Array.isArray(question.options) || question.options.some(option => typeof option !== 'string')))))) {
      clearDraft(userId, storage)
      return null
    }
    return draft.state
  } catch { clearDraft(userId, storage); return null }
}

export function clearAllDrafts(storage) {
  storage = sessionStore(storage)
  memoryDrafts.clear()
  try {
    for (let index = storage.length - 1; index >= 0; index--) {
      const key = storage.key(index)
      if (key?.startsWith(PREFIX)) storage.removeItem(key)
    }
  } catch { /* No storage is also a valid signed-out state. */ }
}

export function jobsAllowRestart(response, field) {
  const items = response?.data?.items
  const total = response?.data?.total
  return Array.isArray(items) && (total == null || total <= items.length)
    && items.every(job => ['completed', 'failed', 'published', 'published_with_warnings', 'rejected_admission', 'release_blocked', 'timed_out', 'cancelled', 'canceled', 'rejected', 'quarantined'].includes(job[field]))
}
