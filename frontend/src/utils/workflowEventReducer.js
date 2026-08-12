const TERMINAL_STATUSES = new Set(['completed', 'degraded', 'human_review', 'failed', 'interrupted'])
const MARKER_EVENTS = new Set([
  'run_created', 'run_started', 'evidence_snapshot_saved', 'resource_version_created',
  'review_persisted', 'revision_requested', 'claim_extraction_started',
  'claim_extraction_completed', 'claim_judgement_completed', 'claim_review_failed',
  'claim_metric_computed', 'resource_published', 'workflow_finalization_failed',
  'run_finalizing', 'run_completed', 'run_failed', 'run_interrupted',
  'attempt_submitted', 'feedback_decision_completed', 'knowledge_state_updated',
  'profile_updated', 'path_mutated', 'followup_generation_created',
  'followup_generation_failed',
])

const EVENT_LABELS = {
  run_created: '任务已创建',
  run_started: '工作流开始',
  evidence_snapshot_saved: 'Evidence Gate',
  resource_version_created: '资源版本',
  review_persisted: 'Reviewer',
  revision_requested: '定向返工',
  claim_extraction_started: 'Claim Extractor',
  claim_extraction_completed: 'Claim Extractor',
  claim_judgement_completed: 'Claim Judge',
  claim_review_failed: 'Claim Audit',
  claim_metric_computed: 'Claim Metric',
  resource_published: 'Publication Gate',
  run_finalizing: 'Supervisor',
  run_completed: '任务完成',
  run_failed: '任务失败',
  run_interrupted: '任务中断',
  attempt_submitted: 'Feedback Attempt',
  feedback_decision_completed: 'Feedback Decision',
  knowledge_state_updated: 'Knowledge State',
  profile_updated: 'Learner Profile',
  path_mutated: 'Learning Path',
  followup_generation_created: 'Follow-up Run',
  followup_generation_failed: 'Follow-up Run',
}

export function createInitialTimelineState() {
  return {
    runSummary: null,
    steps: [],
    markers: [],
    childRuns: [],
    lastSequence: 0,
    seenEventIds: [],
    replayCompleteness: 'complete',
    terminal: false,
  }
}

export function applyRunSnapshot(state, snapshot) {
  return {
    ...state,
    runSummary: { ...(state.runSummary || {}), ...snapshot },
    replayCompleteness: snapshot.replay_completeness || state.replayCompleteness,
    terminal: Boolean(snapshot.is_terminal || TERMINAL_STATUSES.has(snapshot.run_status)),
  }
}

function normalizeEvent(event) {
  return {
    ...event,
    sequence: Number(event.sequence ?? event.event_sequence ?? 0),
    event_type: event.event_type,
    payload: event.payload || {},
  }
}

function stepKey(event) {
  return event.step_id || `${event.step_sequence || 0}:${event.node_name || 'workflow'}`
}

function stepStatus(event) {
  if (event.event_type === 'step_started') return 'running'
  if (event.event_type === 'step_succeeded') return event.status || 'success'
  if (event.event_type === 'step_degraded') return 'degraded'
  if (event.event_type === 'step_failed') return 'failed'
  return event.status || 'success'
}

function upsertStep(steps, event) {
  const key = stepKey(event)
  const index = steps.findIndex((item) => item.key === key)
  const current = index >= 0 ? steps[index] : {}
  const next = {
    ...current,
    key,
    step_id: event.step_id,
    sequence: event.step_sequence || current.sequence || event.sequence,
    agent_name: event.node_name || current.agent_name || 'workflow',
    action: event.summary || current.action || EVENT_LABELS[event.event_type] || event.event_type,
    output_summary: event.summary || current.output_summary || '',
    status: stepStatus(event),
    retry_count: event.payload.retry_count ?? current.retry_count ?? 0,
    duration_ms: event.payload.duration_ms ?? current.duration_ms,
    evidence_count: event.payload.valid_evidence_count ?? current.evidence_count,
    claim_count: event.payload.claim_count ?? current.claim_count,
    revision_count: event.payload.revision_count ?? current.revision_count,
    occurred_at: event.occurred_at || current.occurred_at,
  }
  if (index < 0) return [...steps, next].sort((a, b) => a.sequence - b.sequence)
  const copy = [...steps]
  copy[index] = next
  return copy
}

function updateStepMetrics(steps, event) {
  if (!event.step_id) return steps
  const index = steps.findIndex((item) => item.step_id === event.step_id)
  if (index < 0) return steps
  const copy = [...steps]
  copy[index] = {
    ...copy[index],
    evidence_count: event.payload.valid_evidence_count ?? event.payload.count ?? copy[index].evidence_count,
    claim_count: event.payload.claim_count ?? copy[index].claim_count,
    revision_count: event.payload.revision_count ?? copy[index].revision_count,
  }
  return copy
}

export function reduceWorkflowEvent(state, rawEvent) {
  const event = normalizeEvent(rawEvent)
  if (!Number.isInteger(event.sequence) || event.sequence <= state.lastSequence) return state
  if (event.event_id && state.seenEventIds.includes(event.event_id)) return state

  let steps = state.steps
  let markers = state.markers
  let childRuns = state.childRuns
  if (event.event_type.startsWith('step_')) {
    steps = upsertStep(steps, event)
  } else {
    steps = updateStepMetrics(steps, event)
    if (MARKER_EVENTS.has(event.event_type)) {
      const marker = {
        key: event.event_id || `event:${event.sequence}`,
        event_type: event.event_type,
        label: EVENT_LABELS[event.event_type] || event.summary || event.event_type,
        status: event.status || (event.event_type.endsWith('_failed') ? 'failed' : 'success'),
        sequence: event.sequence,
        step_sequence: event.step_sequence,
        node_name: event.node_name,
        summary: event.summary,
        payload: event.payload,
        occurred_at: event.occurred_at,
      }
      markers = [...markers, marker]
    }
    if (event.event_type === 'followup_generation_created' && event.payload.child_run_id) {
      childRuns = [...childRuns.filter((item) => item.run_id !== event.payload.child_run_id), {
        run_id: event.payload.child_run_id,
        action: event.payload.action || 'followup',
        attempt_id: event.payload.attempt_id,
      }]
    }
  }

  return {
    ...state,
    steps,
    markers,
    childRuns,
    lastSequence: event.sequence,
    seenEventIds: event.event_id ? [...state.seenEventIds, event.event_id].slice(-1000) : state.seenEventIds,
    terminal: state.terminal || ['run_completed', 'run_failed', 'run_interrupted'].includes(event.event_type),
  }
}

export function hydrateWorkflowTimeline(timeline) {
  let state = createInitialTimelineState()
  state = applyRunSnapshot(state, {
    ...timeline.run,
    run_status: timeline.run?.status,
    last_event_sequence: timeline.run?.last_event_sequence || 0,
    replay_completeness: timeline.replay_completeness,
    is_terminal: TERMINAL_STATUSES.has(timeline.run?.status),
  })
  for (const step of timeline.steps || []) {
    state.steps.push({
      key: step.step_id,
      step_id: step.step_id,
      sequence: step.step_sequence,
      agent_name: step.agent_name || step.node_name,
      action: step.action,
      output_summary: step.output_summary,
      status: step.status,
      retry_count: step.retry_count || 0,
      duration_ms: step.duration_ms,
      evidence_count: step.retrieval_candidate_count,
      occurred_at: step.started_at,
    })
  }
  state.steps.sort((a, b) => a.sequence - b.sequence)
  for (const event of timeline.events || []) state = reduceWorkflowEvent(state, event)
  return state
}
