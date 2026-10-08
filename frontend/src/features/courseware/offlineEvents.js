const STORAGE_KEY = 'zhiyu.courseware.learning-events.v1'
const SAFE_STATE_KEYS = new Set(['scene_index', 'scene_count', 'correct', 'completed', 'attempt', 'duration_ms', 'component_state'])

function readQueue(storage = globalThis.localStorage) {
  try { return JSON.parse(storage?.getItem(STORAGE_KEY) || '[]') } catch (_) { return [] }
}

function writeQueue(events, storage = globalThis.localStorage) {
  try { storage?.setItem(STORAGE_KEY, JSON.stringify(events)) } catch (_) { /* offline storage is best effort */ }
}

function stableEventId(event) {
  const raw = [event.event_type, event.resource_id, event.release_id, event.scene_id || '', event.component_id || '', JSON.stringify(event.state || {})].join('|')
  let hash = 2166136261
  for (let index = 0; index < raw.length; index += 1) hash = Math.imul(hash ^ raw.charCodeAt(index), 16777619)
  return `evt_${(hash >>> 0).toString(16)}`
}

export function createCoursewareEvent({ event_type, resource_id, release_id, scene_id = null, component_id = null, component_version = '1.0', state = {} }) {
  const safeState = Object.fromEntries(Object.entries(state || {}).filter(([key]) => SAFE_STATE_KEYS.has(key)))
  const event = { event_type, resource_id, release_id, scene_id, component_id, component_version, state: safeState }
  const occurrence_id = `occ_${globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(16).slice(2)}`}`
  return { event_id: occurrence_id, occurrence_id, ...event, created_at: new Date().toISOString(), occurred_at: new Date().toISOString() }
}

export function enqueueCoursewareEvent(event, storage = globalThis.localStorage) {
  const queue = readQueue(storage)
  if (!queue.some((item) => item.event_id === event.event_id)) queue.push(event)
  writeQueue(queue, storage)
  return queue
}

export function pendingCoursewareEvents(storage = globalThis.localStorage) { return readQueue(storage) }

export function acknowledgeCoursewareEvents(eventIds, storage = globalThis.localStorage) {
  const ids = new Set(eventIds || [])
  const queue = readQueue(storage).filter((item) => !ids.has(item.event_id))
  writeQueue(queue, storage)
  return queue
}

export function projectCoursewareProgress(events, { resource_id, release_id }) {
  const relevant = (events || []).filter((item) => item.resource_id === resource_id && item.release_id === release_id)
  return {
    resource_id,
    release_id,
    viewed_scene_ids: [...new Set(relevant.filter((item) => item.event_type === 'scene_viewed').map((item) => item.scene_id).filter(Boolean))].sort(),
    completed_scene_ids: [...new Set(relevant.filter((item) => item.event_type === 'scene_completed').map((item) => item.scene_id).filter(Boolean))].sort(),
    courseware_completed: relevant.some((item) => item.event_type === 'courseware_completed'),
    answer_count: relevant.filter((item) => item.event_type === 'answer_submitted').length,
  }
}
