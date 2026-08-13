const WORKFLOW_EVENT_TYPES = [
  'run_created',
  'run_started',
  'step_started',
  'step_succeeded',
  'step_degraded',
  'step_failed',
  'evidence_snapshot_saved',
  'checkpoint_saved',
  'run_finalizing',
  'resource_persisted',
  'workflow_finalization_failed',
  'resource_version_created',
  'review_persisted',
  'revision_requested',
  'claim_extraction_started',
  'claim_extraction_completed',
  'claim_judgement_completed',
  'claim_review_failed',
  'claim_metric_computed',
  'attempt_submitted',
  'feedback_decision_started',
  'feedback_decision_completed',
  'knowledge_state_updated',
  'profile_updated',
  'path_mutated',
  'followup_generation_created',
  'followup_generation_failed',
  'resource_published',
  'run_completed',
  'run_failed',
  'run_interrupted',
]

const TERMINAL_EVENTS = new Set(['run_completed', 'run_failed', 'run_interrupted'])

function parseData(event) {
  try {
    return JSON.parse(event.data)
  } catch {
    return null
  }
}

export function runEventsUrl(runId, afterSequence = 0) {
  const query = afterSequence > 0 ? `?after_sequence=${encodeURIComponent(afterSequence)}` : ''
  return `/api/runs/${encodeURIComponent(runId)}/events${query}`
}

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
  let source = null
  let closed = false
  let lastSequence = Math.max(0, Number(afterSequence) || 0)
  let consecutiveErrors = 0

  function close() {
    closed = true
    source?.close()
    source = null
  }

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
      if (!payload) return
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
      const payload = parseData(event) || { code: 'WORKFLOW_STREAM_UNAVAILABLE' }
      onError(payload)
      onFallback(payload)
      close()
    })

    for (const eventType of WORKFLOW_EVENT_TYPES) {
      source.addEventListener(eventType, (event) => {
        const payload = parseData(event)
        if (!payload) return
        const sequence = Number(payload.sequence)
        if (!Number.isInteger(sequence) || sequence <= lastSequence) return
        lastSequence = sequence
        consecutiveErrors = 0
        onWorkflowEvent(payload)
        if (TERMINAL_EVENTS.has(payload.event_type)) terminal(payload)
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
