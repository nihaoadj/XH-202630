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

const RESOURCE_EVENT_STATES = Object.freeze({
  resource_execution_queued: 'queued',
  resource_generation_started: 'generating',
  resource_generated: 'generated',
  resource_version_created: 'generated',
  resource_review_started: 'reviewing',
  resource_revision_requested: 'revision_requested',
  revision_requested: 'revision_requested',
  resource_claim_check_started: 'claim_checking',
  resource_claim_checking: 'claim_checking',
  claim_extraction_started: 'claim_checking',
  claim_extraction_completed: 'claim_checking',
  resource_approved: 'approved',
  resource_published: 'approved',
  resource_execution_failed: 'failed',
  resource_human_review_requested: 'human_review',
  html_derivation_started: 'generating',
  html_derivation_completed: 'approved',
  html_derivation_failed: 'failed',
})

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
    resourceExecutions: [],
    resourceProgressSummary: null,
    lastSequence: 0,
    seenEventIds: [],
    replayCompleteness: 'complete',
    terminal: false,
  }
}

export function applyRunSnapshot(state, snapshot) {
  const next = {
    ...state,
    runSummary: { ...(state.runSummary || {}), ...snapshot },
    replayCompleteness: snapshot.replay_completeness || state.replayCompleteness,
    terminal: Boolean(snapshot.is_terminal || TERMINAL_STATUSES.has(snapshot.run_status)),
  }
  return applyResourceProgressSnapshot(next, snapshot)
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

function resourceEventValue(event, name, fallback = undefined) {
  return event[name] ?? event.payload?.[name] ?? fallback
}

export function isResourceWorkflowEvent(event) {
  return Boolean(
    resourceEventValue(event, 'resource_spec_id')
      && (resourceEventValue(event, 'representation') || resourceEventValue(event, 'resource_execution_state')),
  )
}

function resourceExecutionState(event) {
  return resourceEventValue(event, 'resource_execution_state')
    || resourceEventValue(event, 'execution_state')
    || RESOURCE_EVENT_STATES[event.event_type]
    || null
}

export function normalizeResourceExecution(source, fallbackSequence = 0) {
  if (!source) return null
  const payload = source.payload || {}
  const resourceSpecId = source.resource_spec_id || payload.resource_spec_id
  if (!resourceSpecId) return null
  const representation = source.representation || payload.representation || 'text'
  const state = source.resource_execution_state
    || source.execution_state
    || source.state
    || payload.resource_execution_state
    || payload.execution_state
    || RESOURCE_EVENT_STATES[source.event_type]
    || 'queued'
  return {
    resource_spec_id: resourceSpecId,
    representation,
    key: `${resourceSpecId}:${representation}`,
    resource_id: source.resource_id ?? payload.resource_id ?? null,
    review_id: source.review_id ?? payload.review_id ?? null,
    resource_type: source.resource_type ?? payload.resource_type ?? '学习资源',
    learning_objective: source.learning_objective ?? payload.learning_objective ?? '',
    resource_execution_state: state,
    attempt: Number(source.attempt ?? payload.attempt ?? 0) || 0,
    error_code: source.error_code ?? payload.error_code ?? null,
    error_message: source.error_message ?? payload.error_message ?? '',
    agent_name: source.agent_name ?? payload.agent_name ?? source.node_name ?? null,
    prompt_version: source.prompt_version ?? payload.prompt_version ?? null,
    artifact_format: source.artifact_format ?? payload.artifact_format ?? null,
    validation_status: source.validation_status ?? payload.validation_status ?? null,
    publication_status: source.publication_status ?? payload.publication_status ?? null,
    claim_metric_status: source.claim_metric_status ?? payload.claim_metric_status ?? null,
    claim_count: source.claim_count ?? payload.claim_count ?? null,
    factual_claim_total: source.factual_claim_total ?? payload.factual_claim_total ?? null,
    supported_claim_total: source.supported_claim_total ?? payload.supported_claim_total ?? null,
    contradicted_claim_total: source.contradicted_claim_total ?? payload.contradicted_claim_total ?? null,
    not_in_evidence_claim_total: source.not_in_evidence_claim_total ?? payload.not_in_evidence_claim_total ?? null,
    claim_factual_pass_rate: source.claim_factual_pass_rate ?? payload.claim_factual_pass_rate ?? null,
    claim_warning_publish: Boolean(source.claim_warning_publish ?? payload.claim_warning_publish),
    display_order: Number(source.display_order ?? payload.display_order ?? 0) || 0,
    updated_at: source.updated_at ?? payload.updated_at ?? source.occurred_at ?? null,
    last_sequence: Number(source.last_sequence ?? source.sequence ?? fallbackSequence) || 0,
  }
}

function mergeResourceExecution(current, incoming) {
  if (!current) return incoming
  const newerAttempt = incoming.attempt > current.attempt
  const sameAttempt = incoming.attempt === current.attempt
  const newerEvent = incoming.last_sequence >= current.last_sequence
  if (newerAttempt || (sameAttempt && newerEvent)) {
    return {
      ...current,
      ...incoming,
      resource_id: incoming.resource_id || current.resource_id,
      review_id: incoming.review_id || current.review_id,
      error_code: incoming.error_code || null,
      error_message: incoming.error_message || '',
    }
  }
  // A delayed/backfilled event may carry metadata omitted from the newer
  // event, but it must never regress the execution state or attempt.
  const next = { ...current }
  for (const [key, value] of Object.entries(incoming)) {
    if ((next[key] == null || next[key] === '') && value != null && value !== '') next[key] = value
  }
  return next
}

function upsertResourceExecution(executions, source, fallbackSequence = 0) {
  const incoming = normalizeResourceExecution(source, fallbackSequence)
  if (!incoming) return executions
  const index = executions.findIndex((item) => item.key === incoming.key)
  const next = [...executions]
  if (index < 0) next.push(incoming)
  else next[index] = mergeResourceExecution(next[index], incoming)
  return next.sort((left, right) => (
    Number(left.display_order || 0) - Number(right.display_order || 0)
      || String(left.resource_type || '').localeCompare(String(right.resource_type || ''), 'zh-CN')
      || (left.representation === 'text' ? -1 : 1)
  ))
}

function progressItems(source) {
  const summary = source?.resource_progress_summary || source?.progress_summary || null
  return source?.resource_executions
    || source?.executions
    || summary?.resource_executions
    || summary?.executions
    || summary?.items
    || []
}

export function applyResourceProgressSnapshot(state, source, { authoritative = false } = {}) {
  if (!source) return state
  let resourceExecutions = state.resourceExecutions || []
  for (const item of progressItems(source)) {
    // A persisted snapshot represents the latest durable state, even when a
    // backfilled historical event has a larger sequence number.
    const snapshotItem = authoritative
      ? { ...item, last_sequence: Number.MAX_SAFE_INTEGER }
      : item
    resourceExecutions = upsertResourceExecution(
      resourceExecutions,
      snapshotItem,
      snapshotItem.last_sequence || 0,
    )
  }
  const summary = source.resource_progress_summary || source.progress_summary
  return {
    ...state,
    resourceExecutions,
    resourceProgressSummary: summary
      ? { ...(state.resourceProgressSummary || {}), ...summary }
      : state.resourceProgressSummary,
  }
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
  if (!Number.isInteger(event.sequence) || event.sequence <= 0) return state
  if (event.event_id && state.seenEventIds.includes(event.event_id)) return state
  const isResourceEvent = isResourceWorkflowEvent(event)
  // Durable SSE events normally arrive in sequence. Resource events are also
  // accepted as delayed backfill, then merged by attempt + per-resource
  // sequence so they can fill a missing card without regressing its state.
  if (event.sequence <= state.lastSequence && !isResourceEvent) return state

  let steps = state.steps
  let markers = state.markers
  let childRuns = state.childRuns
  let resourceExecutions = state.resourceExecutions || []
  if (isResourceEvent) resourceExecutions = upsertResourceExecution(resourceExecutions, event, event.sequence)
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
    resourceExecutions,
    lastSequence: Math.max(state.lastSequence, event.sequence),
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
  state = applyResourceProgressSnapshot(state, timeline, { authoritative: true })
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
  const events = [...(timeline.events || [])]
    .sort((left, right) => Number(left.sequence || left.event_sequence || 0) - Number(right.sequence || right.event_sequence || 0))
  for (const event of events) state = reduceWorkflowEvent(state, event)
  // The execution snapshot is the durable, current source of truth. Events
  // are historical and may describe an earlier attempt or an old status before
  // a targeted retry, so never let replay overwrite current visibility.
  state = applyResourceProgressSnapshot(state, timeline)
  return state
}
