import assert from 'node:assert/strict'

import { createRunEventClient } from '../../../src/features/runs/api.js'
import {
  applyRunSnapshot,
  createInitialTimelineState,
  hydrateWorkflowTimeline,
  reduceWorkflowEvent,
} from '../../../src/utils/workflowEventReducer.js'
import { normalizeResourceProgressSummary } from '../../../src/utils/generationDisplay.js'


class FakeEventSource {
  static latest = null

  constructor(url) {
    this.url = url
    this.listeners = new Map()
    this.closed = false
    FakeEventSource.latest = this
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback)
  }

  emit(name, data) {
    this.listeners.get(name)?.({ data: JSON.stringify(data) })
  }

  close() {
    this.closed = true
  }
}

globalThis.EventSource = FakeEventSource

let state = createInitialTimelineState()
state = applyRunSnapshot(state, {
  run_id: 'run-1',
  run_status: 'running',
  last_event_sequence: 2,
  replay_completeness: 'complete',
})
assert.equal(state.steps.length, 0, 'snapshot must not invent a Step')

const started = {
  run_id: 'run-1',
  event_id: 'evt-3',
  sequence: 3,
  event_type: 'step_started',
  step_id: 'step-1',
  step_sequence: 1,
  node_name: 'generator',
  status: 'running',
  payload: {},
}
state = reduceWorkflowEvent(state, started)
state = reduceWorkflowEvent(state, started)
assert.equal(state.steps.length, 1, 'duplicate sequence must not duplicate Step')
assert.equal(state.steps[0].status, 'running')

state = reduceWorkflowEvent(state, { ...started, event_id: 'evt-4', sequence: 4, event_type: 'step_succeeded', status: 'success' })
assert.equal(state.steps.length, 1)
assert.equal(state.steps[0].status, 'success')

const hydrated = hydrateWorkflowTimeline({
  run: { run_id: 'run-visible', status: 'completed' },
  resource_executions: [{
    run_id: 'run-visible', resource_spec_id: 'spec-1', representation: 'text',
    resource_type: '讲义', state: 'approved', publication_status: 'published',
  }],
  events: [{
    event_id: 'historic-rollback', sequence: 10, event_type: 'resource_human_review_requested',
    payload: { resource_spec_id: 'spec-1', representation: 'text', state: 'human_review' },
  }],
})
assert.equal(hydrated.resourceExecutions[0].resource_execution_state, 'approved', 'durable snapshot must override stale events')
assert.equal(hydrated.resourceExecutions[0].publication_status, 'published')

const refreshedProgress = normalizeResourceProgressSummary(
  { total: 1, approved: 0, counts: { approved: 0 } },
  [{ resource_spec_id: 'spec-1', representation: 'text', resource_execution_state: 'approved' }],
)
assert.equal(refreshedProgress.approved, 1, 'concrete execution state must override a stale job counter')
assert.equal(refreshedProgress.published, 0, 'review approval must not be presented as publication')

state = reduceWorkflowEvent(state, {
  event_id: 'evt-5',
  sequence: 5,
  event_type: 'followup_generation_created',
  status: 'queued',
  payload: { child_run_id: 'child-run', attempt_id: 'attempt-1' },
})
assert.equal(state.childRuns[0].run_id, 'child-run')

let workflowEvents = 0
let fallbacks = 0
const client = createRunEventClient({
  runId: 'run-1',
  afterSequence: 2,
  onWorkflowEvent: () => { workflowEvents += 1 },
  onFallback: () => { fallbacks += 1 },
})
client.connect()
assert.match(FakeEventSource.latest.url, /after_sequence=2/)
FakeEventSource.latest.emit('step_started', started)
FakeEventSource.latest.emit('step_started', started)
assert.equal(workflowEvents, 1, 'EventSource wrapper must also dedupe sequences')
FakeEventSource.latest.onerror()
assert.equal(client.isClosed(), false, 'a transient disconnect leaves native reconnect enabled')
FakeEventSource.latest.emit('step_succeeded', {
  ...started, event_id: 'evt-4', sequence: 4, event_type: 'step_succeeded', status: 'success',
})
assert.equal(workflowEvents, 2, 'events after transport recovery continue from the durable cursor')
FakeEventSource.latest.onerror()
FakeEventSource.latest.onerror()
FakeEventSource.latest.onerror()
assert.equal(fallbacks, 1)
assert.equal(client.isClosed(), true)

let terminal = false
const terminalClient = createRunEventClient({
  runId: 'run-2',
  onTerminal: () => { terminal = true },
})
terminalClient.connect()
FakeEventSource.latest.emit('run_completed', {
  event_id: 'terminal-1', sequence: 1, event_type: 'run_completed', payload: {},
})
assert.equal(terminal, true)
assert.equal(terminalClient.isClosed(), true)

console.log('workflow event reducer/client tests passed')
