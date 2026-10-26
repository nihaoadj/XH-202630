import { WORKFLOW_EVENT_TYPES as BACKEND_EVENT_TYPES } from '../../contracts/generated/constants.js'
import { isRecord, isJobStatus, isRunStatus } from '../../contracts/guards.js'

// Historical frontend receive aliases. Remove only with replay/caller evidence.
const LEGACY_EVENT_TYPES = [
  'resource_spec_created', 'resource_execution_state_changed', 'resource_execution_updated',
  'resource_review_started', 'resource_revision_requested', 'resource_claim_check_started',
  'resource_claim_checking', 'resource_approved', 'resource_execution_failed',
  'html_derivation_started', 'html_derivation_completed', 'html_derivation_failed',
]
const WORKFLOW_EVENT_TYPES = [...new Set([...BACKEND_EVENT_TYPES, ...LEGACY_EVENT_TYPES])]

const TERMINAL_EVENTS = new Set(['run_completed', 'run_failed', 'run_interrupted'])

/** @param {unknown} event @returns {unknown} */
function parseData(event) {
  try {
    if (!isRecord(event) || typeof event.data !== 'string') return null
    return JSON.parse(event.data)
  } catch {
    return null
  }
}

/** @param {unknown} value @param {string} expectedType @returns {value is import('../../contracts/ports').RunEventInput} */
export function isWorkflowEventPayload(value, expectedType = '') {
  if (!isRecord(value)) return false
  if (value.run_id != null && typeof value.run_id !== 'string') return false
  const sequence = value.sequence ?? value.event_sequence
  if (typeof sequence !== 'number' || !Number.isInteger(sequence) || sequence <= 0) return false
  const eventType = value.event_type || expectedType
  if (typeof eventType !== 'string' || !eventType) return false
  return value.payload == null || isRecord(value.payload)
}

/** @param {unknown} value @returns {value is import('../../contracts/ports').RunSnapshotInput} */
export function isRunSnapshotPayload(value) {
  return isRecord(value)
    && (value.run_id == null || typeof value.run_id === 'string')
    && (value.run_status == null || isRunStatus(value.run_status))
    && (value.status == null || isRunStatus(value.status))
    && (value.job_status == null || isJobStatus(value.job_status)) && (
    typeof value.run_id === 'string'
      || typeof value.run_status === 'string'
      || typeof value.status === 'string'
  ) && (value.is_terminal == null || typeof value.is_terminal === 'boolean')
    && (value.last_event_sequence == null || typeof value.last_event_sequence === 'number' && Number.isInteger(value.last_event_sequence) && value.last_event_sequence >= 0)
}

/** @param {string} runId @param {number} afterSequence */
export function runEventsUrl(runId, afterSequence = 0) {
  const query = afterSequence > 0 ? `?after_sequence=${encodeURIComponent(afterSequence)}` : ''
  return `/api/runs/${encodeURIComponent(runId)}/events${query}`
}

/** @param {import('../../contracts/ports').RunClientOptions} options */
export function createRunEventClient({
  runId,
  afterSequence = 0,
  maxConsecutiveErrors = 3,
  onSnapshot = () => {},
  onWorkflowEvent = () => {},
  onPing = () => {},
  onTerminal = () => {},
  onError = () => {},
  onFallback = () => {},
}) {
  /** @type {EventSource | null} */
  let source = null
  let closed = false
  let lastSequence = Math.max(0, Number(afterSequence) || 0)
  const seenSequences = new Set()
  let consecutiveErrors = 0

  function close() {
    closed = true
    source?.close()
    source = null
  }

  /** @param {import('../../contracts/ports').RunEventInput | import('../../contracts/ports').RunSnapshotInput} payload */
  function terminal(payload) {
    onTerminal(payload)
    close()
  }

  function connect() {
    close()
    closed = false
    source = new EventSource(runEventsUrl(runId, lastSequence))

    source.addEventListener('snapshot', (event) => {
      const payload = parseData(event)
      if (!isRunSnapshotPayload(payload)) return
      if (payload.run_id && payload.run_id !== runId) return
      consecutiveErrors = 0
      onSnapshot(payload)
      if (payload.is_terminal && lastSequence >= (payload.last_event_sequence || 0)) {
        terminal(payload)
      }
    })

    source.addEventListener('ping', (event) => {
      const payload = parseData(event)
      if (payload) onPing(payload)
    })

    source.addEventListener('stream_error', (event) => {
      const data = parseData(event)
      const payload = { code: isRecord(data) && typeof data.code === 'string' ? data.code : 'WORKFLOW_STREAM_UNAVAILABLE' }
      onError(payload)
      onFallback(payload)
      close()
    })

    for (const eventType of WORKFLOW_EVENT_TYPES) {
      source.addEventListener(eventType, (event) => {
        const payload = parseData(event)
        if (!isWorkflowEventPayload(payload, eventType)) return
        if (payload.run_id && payload.run_id !== runId) return
        const normalized = payload.event_type ? payload : { ...payload, event_type: eventType }
        const sequence = Number(normalized.sequence ?? normalized.event_sequence)
        if (seenSequences.has(sequence)) return
        // Native EventSource can briefly replay older durable events after a
        // reconnect. Forward an unseen backfill once; the reducer performs
        // resource-scoped monotonic merging and the cursor remains the max.
        seenSequences.add(sequence)
        if (seenSequences.size > 2000) {
          const floor = Math.max(0, lastSequence - 1000)
          for (const item of seenSequences) if (item < floor) seenSequences.delete(item)
        }
        lastSequence = Math.max(lastSequence, sequence)
        consecutiveErrors = 0
        onWorkflowEvent(normalized)
        if (TERMINAL_EVENTS.has(normalized.event_type)) terminal(normalized)
      })
    }

    source.onerror = () => {
      if (closed) return
      consecutiveErrors += 1
      onError({ code: 'SSE_TRANSPORT_DISCONNECTED', consecutive_errors: consecutiveErrors })
      if (consecutiveErrors >= maxConsecutiveErrors) {
        onFallback({ code: 'SSE_FALLBACK_POLLING' })
        close()
      }
      // Before the threshold, native EventSource reconnects and sends its
      // Last-Event-ID. The reducer still de-duplicates by durable sequence.
    }
    return source
  }

  return {
    connect,
    close,
    getLastSequence: () => lastSequence,
    isClosed: () => closed,
  }
}
