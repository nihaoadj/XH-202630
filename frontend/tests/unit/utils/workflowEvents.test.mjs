import assert from 'node:assert/strict'

import { createRunEventClient } from '../../../src/features/runs/api.js'
import {
  applyRunSnapshot,
  createInitialTimelineState,
  hydrateWorkflowTimeline,
  reduceWorkflowEvent,
} from '../../../src/utils/workflowEventReducer.js'
import { normalizeResourceProgressSummary } from '../../../src/utils/generationDisplay.js'
import { buildResourceStatusItems, resourceStatusMeta, validationStatusLabel } from '../../../src/features/generation/resourceStatusPresentation.js'
import {
  associatedStepResources,
  buildClaimRows,
  claimAuditSummary,
  resourceVersionChain,
  textChangeRange,
} from '../../../src/features/generation/generationAudit.js'
import {
  canInspectStep,
  formatDuration,
  workflowNodeMeta,
} from '../../../src/features/generation/workflowPresentation.js'


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

let liveResource = hydrateWorkflowTimeline({
  run: { run_id: 'live-resource', status: 'running', last_event_sequence: 10 },
  resource_executions: [{ resource_spec_id: 'live-spec', representation: 'text', resource_type: '分阶测试题',
    resource_id: 'assessment-v2', attempt: 2, state: 'generated', validation_status: 'validated',
    publication_status: 'unpublished', agent_name: 'AssessmentAgent', claim_warning_publish: true,
    review_status: 'approved', claim_publish_decision: null,
    updated_at: '2026-10-12T00:00:00' }],
  events: [{ event_id: 'live-old-history', sequence: 9, event_type: 'resource_generation_started',
    payload: { resource_spec_id: 'live-spec', representation: 'text', attempt: 2 } }],
})
assert.equal(liveResource.resourceExecutions[0].last_sequence, 10, 'a snapshot must use the actual replay watermark')
assert.equal(liveResource.resourceExecutions[0].resource_execution_state, 'generated')
liveResource = reduceWorkflowEvent(liveResource, {
  event_id: 'live-publish', sequence: 11, event_type: 'resource_published', occurred_at: '2026-10-12T00:01:00Z',
  payload: { resource_spec_id: 'live-spec', representation: 'text', publication_status: 'published' },
})
assert.equal(liveResource.resourceExecutions[0].resource_execution_state, 'approved', 'SSE after the snapshot must update the same attempt')
assert.equal(liveResource.resourceExecutions[0].attempt, 2, 'a sparse event must retain the current attempt')
assert.equal(liveResource.resourceExecutions[0].validation_status, 'validated', 'publication must retain the earlier validation result')
assert.equal(liveResource.resourceExecutions[0].claim_warning_publish, true, 'a sparse event must not erase a Claim warning')
assert.equal(liveResource.resourceExecutions[0].review_status, 'approved', 'a sparse event must retain the explicit review result')
assert.equal(liveResource.resourceExecutions[0].publication_status, 'published')

const beforeDelayedResource = liveResource.resourceExecutions[0]
liveResource = reduceWorkflowEvent(liveResource, {
  event_id: 'live-delayed-failure', sequence: 8, event_type: 'resource_execution_failed',
  payload: { resource_spec_id: 'live-spec', representation: 'text', attempt: 2, error_message: 'old failure' },
})
assert.deepEqual(liveResource.resourceExecutions[0], beforeDelayedResource, 'late history must not restore a superseded error or phase')
liveResource = applyRunSnapshot(liveResource, { resource_progress_summary: { items: [{
  resource_spec_id: 'live-spec', representation: 'text', attempt: 2, resource_execution_state: 'approved',
  publication_status: 'published', claim_warning_publish: false, claim_publish_decision_pending: false,
  claim_publish_decision: 'published_by_user',
  updated_at: '2026-10-12T00:02:00Z',
}] } })
assert.equal(liveResource.resourceExecutions[0].claim_warning_publish, false, 'a newer durable refresh must honor an explicit false')
assert.equal(liveResource.resourceExecutions[0].claim_publish_decision, 'published_by_user')
const beforeOldRefresh = liveResource.resourceExecutions[0]
const delayedBeforePersisted = reduceWorkflowEvent(liveResource, {
  event_id: 'live-old-time-new-sequence', sequence: 12, event_type: 'resource_generation_started',
  occurred_at: '2026-10-12T00:01:30Z',
  payload: { resource_spec_id: 'live-spec', representation: 'text', attempt: 2 },
})
assert.equal(delayedBeforePersisted.resourceExecutions[0].resource_execution_state, 'approved',
  'a delayed event older than the durable row must not undo that newer snapshot even with a higher event sequence')
assert.equal(delayedBeforePersisted.resourceExecutions[0].publication_status, 'published')
liveResource = applyRunSnapshot(liveResource, { resource_progress_summary: { items: [{
  resource_spec_id: 'live-spec', representation: 'text', attempt: 2, resource_execution_state: 'generating',
  publication_status: 'unpublished', updated_at: '2026-10-12T00:00:00Z',
}] } })
assert.deepEqual(liveResource.resourceExecutions[0], beforeOldRefresh, 'an old job response must not regress the newer execution or publication')
liveResource = applyRunSnapshot(liveResource, { resource_progress_summary: { items: [{
  resource_spec_id: 'live-spec', representation: 'text', attempt: 2, resource_execution_state: 'reviewing',
  publication_status: 'unpublished',
}] } }, { authoritative: true, watermark: 10 })
assert.equal(liveResource.resourceExecutions[0].publication_status, 'published', 'a low-watermark legacy response cannot cover a newer SSE event')

liveResource = reduceWorkflowEvent(liveResource, { event_id: 'live-retry', sequence: 12,
  event_type: 'resource_generation_started', payload: { resource_spec_id: 'live-spec', representation: 'text', attempt: 3 } })
assert.equal(liveResource.resourceExecutions[0].attempt, 3)
assert.equal(liveResource.resourceExecutions[0].resource_execution_state, 'generating')
assert.equal(liveResource.resourceExecutions[0].resource_id, null, 'a new attempt cannot inherit the old artifact identity')
assert.notEqual(liveResource.resourceExecutions[0].publication_status, 'published')
assert.equal(liveResource.resourceExecutions[0].validation_status, null)
assert.equal(liveResource.resourceExecutions[0].claim_warning_publish, false)
assert.equal(liveResource.resourceExecutions[0].review_status, null, 'a new attempt must not inherit the previous review')
assert.equal(liveResource.resourceExecutions[0].claim_publish_decision, null)
liveResource = reduceWorkflowEvent(liveResource, { event_id: 'live-old-attempt-publish', sequence: 13,
  event_type: 'resource_published', payload: { resource_spec_id: 'live-spec', representation: 'text', attempt: 2,
    resource_id: 'assessment-v2', publication_status: 'published' } })
assert.equal(liveResource.resourceExecutions[0].resource_execution_state, 'generating', 'a delayed publication from attempt 2 cannot mask attempt 3')
assert.equal(liveResource.resourceExecutions[0].resource_id, null)
liveResource = reduceWorkflowEvent(liveResource, { event_id: 'live-old-sparse-artifact', sequence: 7,
  event_type: 'resource_published', payload: { resource_spec_id: 'live-spec', representation: 'text',
    resource_id: 'assessment-v1', publication_status: 'published', validation_status: 'validated' } })
assert.equal(liveResource.resourceExecutions[0].resource_id, null, 'an old event without an attempt must not reattach a previous artifact')
assert.equal(liveResource.resourceExecutions[0].validation_status, null)
liveResource = applyRunSnapshot(liveResource, { resource_progress_summary: { items: [{
  resource_spec_id: 'live-spec', representation: 'text', attempt: 3, resource_execution_state: 'approved',
  resource_id: 'assessment-v3', validation_status: 'validated', publication_status: 'published',
}] } }, { authoritative: true, watermark: 13 })
assert.equal(liveResource.resourceExecutions[0].publication_status, 'published', 'a sufficiently recent legacy watermark can reconcile a timestamp-free snapshot')
liveResource = reduceWorkflowEvent(liveResource, { event_id: 'live-explicit-null', sequence: 14, event_type: 'resource_approved',
  payload: { resource_spec_id: 'live-spec', representation: 'text', validation_status: null, claim_publish_decision_pending: false } })
assert.equal(liveResource.resourceExecutions[0].validation_status, null, 'an explicit null must not be mistaken for an omitted field')
assert.equal(liveResource.resourceExecutions[0].publication_status, 'published')

const requestedTypes = ['讲义', '分阶测试题', '讲义']
const requestedItems = buildResourceStatusItems([], { requestedTypes, jobStatus: 'queued' })
assert.equal(requestedItems.length, 2, 'request placeholders must deduplicate real requested types')
assert.ok(requestedItems.every(item => item.request_placeholder && !item.resource_spec_id && !item.resource_id), 'request placeholders must not invent execution or artifact IDs')
assert.equal(buildResourceStatusItems([], { requestedTypes, jobStatus: 'completed' }).length, 0, 'missing historical rows must not pretend to be newly queued')
const replacedItems = buildResourceStatusItems([{ resource_spec_id: 'lecture-spec', resource_type: '讲义',
  representation: 'text', resource_execution_state: 'generating' }], { requestedTypes, jobStatus: 'running' })
assert.equal(replacedItems.length, 2, 'a real spec must replace its requested type placeholder')
assert.equal(replacedItems.filter(item => item.resource_type === '讲义').length, 1)

const pendingExecution = { resource_spec_id: 'pending-spec', resource_type: '实操指南', representation: 'text',
  resource_id: 'pending-resource', attempt: 2, resource_execution_state: 'human_review',
  publication_status: 'unpublished', claim_publish_decision_pending: true, claim_metric_status: 'complete' }
const decidedResource = { run_id: 'decision-run', resource_id: 'pending-resource', publication_status: 'published',
  claim_publish_decision_pending: false, claim_publish_decision: 'published_by_user' }
const decidedItems = buildResourceStatusItems([pendingExecution], { runId: 'decision-run', resources: [decidedResource] })
assert.equal(resourceStatusMeta(decidedItems[0]).label, '已发布', 'a resource publication decision must reconcile an unchanged execution timestamp')
assert.equal(decidedItems[0].claim_publish_decision_pending, false)
const retainedItem = buildResourceStatusItems([pendingExecution], { claimReports: {
  'pending-resource': { publication_status: 'unpublished', claim_publish_decision_pending: false,
    claim_publish_decision: 'rejected_by_user' },
} })[0]
assert.equal(retainedItem.claim_publish_decision_pending, false, 'a fresh declined decision must clear the old pending execution hint')
assert.equal(resourceStatusMeta(retainedItem).label, '已保留，未发布')
assert.equal(normalizeResourceProgressSummary({}, decidedItems).published, 1, 'the visible card and delivery count must use the same publication projection')
assert.equal(buildResourceStatusItems([pendingExecution], { runId: 'other-run', resources: [decidedResource] })[0].publication_status,
  'unpublished', 'a resource from another Run must not change this card')
assert.equal(buildResourceStatusItems([pendingExecution], { resources: [{ ...decidedResource, resource_id: 'older-version' }] })[0].publication_status,
  'unpublished', 'publication must never be matched by type or old artifact version')
const failedWithOldArtifact = buildResourceStatusItems([{ ...pendingExecution, resource_execution_state: 'failed' }], { resources: [decidedResource] })[0]
assert.equal(resourceStatusMeta(failedWithOldArtifact).label, '失败', 'a published old artifact must not hide the current attempt failure')
assert.equal(buildResourceStatusItems([{ ...pendingExecution, resource_execution_state: 'approved', publication_status: 'published' }], {
  resources: [{ ...decidedResource, publication_status: 'unpublished' }],
})[0].publication_status, 'published', 'an old artifact projection must not undo confirmed publication')
assert.equal(validationStatusLabel('validated'), '已通过')
assert.equal(validationStatusLabel(null), null, 'missing validation must not be described as passed')
assert.equal(resourceStatusMeta({ resource_execution_state: 'approved', publication_status: 'unpublished' }).label,
  '审核通过，等待发布', 'approval is a separate gate from publication')

const refreshedProgress = normalizeResourceProgressSummary(
  { total: 1, approved: 0, counts: { approved: 0 } },
  [{ resource_spec_id: 'spec-1', representation: 'text', resource_execution_state: 'approved' }],
)
assert.equal(refreshedProgress.approved, 1, 'concrete execution state must override a stale job counter')
assert.equal(refreshedProgress.published, 0, 'review approval must not be presented as publication')

state = reduceWorkflowEvent(state, {
  event_id: 'claim-metric-1', sequence: 6, event_type: 'claim_metric_computed',
  payload: {
    resource_spec_id: 'spec-1', representation: 'text', resource_id: 'resource-1',
    resource_execution_state: 'claim_checking', claim_metric_status: 'complete',
    factual_claim_total: 5, supported_claim_total: 4, not_in_evidence_claim_total: 1,
    claim_factual_pass_rate: 0.8,
  },
})
assert.equal(state.resourceExecutions[0].claim_factual_pass_rate, 0.8)
assert.equal(state.resourceExecutions[0].not_in_evidence_claim_total, 1)

state = reduceWorkflowEvent(state, {
  event_id: 'evt-7',
  sequence: 7,
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

const auditClaims = buildClaimRows({
  run_id: 'run-audit',
  claims: [
    { claim_id: 'claim-supported', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', text: 'supported claim' },
    { claim_id: 'claim-contradicted', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', text: 'contradicted claim' },
    { claim_id: 'claim-uncovered', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', text: 'uncovered claim' },
    { claim_id: 'claim-no-provenance', resource_id: 'resource-a', text: 'claim with no provenance ids' },
  ],
  judgements: [
    { claim_id: 'claim-supported', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', status: 'completed', verdict: 'supported', evidence_ids: ['evidence-1'] },
    { claim_id: 'claim-contradicted', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', status: 'completed', verdict: 'contradicted', evidence_ids: ['evidence-2'] },
    { claim_id: 'claim-uncovered', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', status: 'completed', verdict: 'not_in_evidence', evidence_ids: ['evidence-missing'] },
    { claim_id: 'claim-no-provenance', status: 'completed', verdict: 'supported', evidence_ids: [] },
  ],
}, 'resource-a', 'run-audit', [
  { run_id: 'run-audit', evidence_id: 'evidence-1', text: 'frozen source one' },
  { run_id: 'run-audit', evidence_id: 'evidence-2', text: 'frozen source two' },
  { run_id: 'another-run', evidence_id: 'evidence-1', text: 'source from another run' },
  { run_id: 'another-run', evidence_id: 'unreferenced', text: 'must not be guessed' },
], { version: 'v2', review_id: 'review-2' })
assert.deepEqual(auditClaims.map(({ verdict }) => verdict), ['supported', 'contradicted', 'not_in_evidence', 'supported'])
assert.deepEqual(auditClaims[0].evidence, [{ run_id: 'run-audit', evidence_id: 'evidence-1', text: 'frozen source one' }], 'evidence must join by ID to the selected Run snapshot')
assert.deepEqual(auditClaims[1].evidence, [{ run_id: 'run-audit', evidence_id: 'evidence-2', text: 'frozen source two' }])
assert.deepEqual(auditClaims[2].evidence, [{ evidence_id: 'evidence-missing', missing: true }], 'unknown evidence IDs must be explicit')
assert.deepEqual(auditClaims[3].evidence, [], 'claims without evidence IDs must not be matched by guesswork')
assert.equal(auditClaims[3].provenanceUnavailable, true)

const isolatedClaims = buildClaimRows({
  run_id: 'run-audit',
  claims: [
    { claim_id: 'kept', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2' },
    { claim_id: 'wrong-run', run_id: 'other-run', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2' },
    { claim_id: 'wrong-resource', run_id: 'run-audit', resource_id: 'resource-b', resource_version: 'v2', review_id: 'review-2' },
    { claim_id: 'wrong-version', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v1', review_id: 'review-2' },
    { claim_id: 'wrong-review', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-1' },
  ],
}, 'resource-a', 'run-audit', [], { version: 'v2', review_id: 'review-2' })
assert.deepEqual(isolatedClaims.map(({ claim_id }) => claim_id), ['kept'], 'Run, resource, version, and review mismatches must be isolated')
assert.deepEqual(buildClaimRows({ run_id: 'other-run', claims: [{ claim_id: 'wrong-run', resource_id: 'resource-a' }] }, 'resource-a', 'run-audit'), [])

for (const mismatch of [
  { run_id: 'other-run' },
  { resource_id: 'resource-b' },
  { resource_version: 'v1' },
  { review_id: 'review-1' },
]) {
  const [row] = buildClaimRows({
    claims: [{ claim_id: 'claim-mismatch', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2' }],
    judgements: [{ claim_id: 'claim-mismatch', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2', status: 'completed', verdict: 'supported', evidence_ids: ['evidence-1'], ...mismatch }],
  }, 'resource-a', 'run-audit', [{ run_id: 'run-audit', evidence_id: 'evidence-1' }], { version: 'v2', review_id: 'review-2' })
  assert.equal(row.verdict, 'incomplete', `mismatched judgement provenance ${JSON.stringify(mismatch)} must not attach`)
  assert.deepEqual(row.evidence, [])
}
const [missingReviewIdentity] = buildClaimRows({
  claims: [{ claim_id: 'claim-missing-review-identity', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', review_id: 'review-2' }],
  judgements: [{ claim_id: 'claim-missing-review-identity', run_id: 'run-audit', resource_id: 'resource-a', resource_version: 'v2', status: 'completed', verdict: 'supported' }],
}, 'resource-a', 'run-audit', [], { version: 'v2', review_id: 'review-2' })
assert.equal(missingReviewIdentity.verdict, 'incomplete', 'a complete Claim identity must not attach a judgement missing review_id')

assert.equal(claimAuditSummary(null, false), '本任务未启用 Claim 审核')
assert.equal(claimAuditSummary({ metric_status: 'incomplete' }), '事实判定未完成')
assert.equal(claimAuditSummary({ metric_status: 'not_applicable' }), '通用 Claim 审核不适用')
assert.equal(claimAuditSummary({ metric_status: 'legacy_unavailable' }), '历史记录缺少 Claim 审核数据')
assert.equal(claimAuditSummary({ metric_status: 'complete', factual_claim_total: 0 }), '没有纳入本次审核的事实 Claim')
assert.equal(claimAuditSummary({ metric_status: 'complete', factual_claim_total: 3, supported_claim_total: 3 }), '已审事实均获证据支持')
assert.equal(claimAuditSummary({ metric_status: 'complete', factual_claim_total: 3, supported_claim_total: 2 }), '发现需要关注的事实')

const resourceVersions = [
  { run_id: 'run-audit', resource_id: 'spec-a-v1', resource_spec_id: 'spec-a', representation: 'text', version: 1, resource_type: '讲义' },
  { run_id: 'run-audit', resource_id: 'spec-a-v2', resource_spec_id: 'spec-a', representation: 'text', version: 2, resource_type: '讲义', parent_resource_id: 'legacy-parent' },
  { run_id: 'run-audit', resource_id: 'spec-a-html', resource_spec_id: 'spec-a', representation: 'html', version: 3, resource_type: '讲义' },
  { run_id: 'run-audit', resource_id: 'spec-b-v1', resource_spec_id: 'spec-b', representation: 'text', version: 1, resource_type: '讲义' },
  { run_id: 'run-audit', resource_id: 'legacy-parent', version: 0, resource_type: '讲义' },
  { run_id: 'other-run', resource_id: 'spec-a-other-run', resource_spec_id: 'spec-a', representation: 'text', version: 4, resource_type: '讲义' },
]
assert.deepEqual(resourceVersionChain(resourceVersions, resourceVersions[1], 'run-audit').map(({ resource_id }) => resource_id), ['spec-a-v1', 'spec-a-v2'], 'chain must match Run, spec, and representation, excluding legacy parents and same-type other specs')
const legacyChain = resourceVersionChain([
  { run_id: 'run-audit', resource_id: 'legacy-parent', version: 1, resource_type: '讲义' },
  { run_id: 'run-audit', resource_id: 'legacy-child', parent_resource_id: 'legacy-parent', version: 2, resource_type: '讲义' },
  { run_id: 'run-audit', resource_id: 'unrelated-same-type', version: 1, resource_type: '讲义' },
  { run_id: 'other-run', resource_id: 'other-run-parent', version: 1, resource_type: '讲义' },
], { run_id: 'run-audit', resource_id: 'legacy-child' }, 'run-audit')
assert.deepEqual(legacyChain.map(({ resource_id }) => resource_id), ['legacy-parent', 'legacy-child'], 'legacy parent links should remain traversable within the selected Run')

assert.deepEqual(textChangeRange('alpha\nbeta', 'alpha\nbeta'), {
  changed: false, before: '', after: '', beforeRange: '无变化行', afterRange: '无变化行', truncated: false,
})
assert.deepEqual(textChangeRange('alpha', 'alpha\nbeta'), {
  changed: true, before: '', after: 'beta', beforeRange: '无变化行', afterRange: '2–2', truncated: false,
})
assert.deepEqual(textChangeRange('alpha\nbeta', 'alpha'), {
  changed: true, before: 'beta', after: '', beforeRange: '2–2', afterRange: '无变化行', truncated: false,
})
assert.deepEqual(textChangeRange('alpha\nbeta\nomega', 'alpha\ngamma\nomega'), {
  changed: true, before: 'beta', after: 'gamma', beforeRange: '2–2', afterRange: '2–2', truncated: false,
})
const budgetRange = textChangeRange(`before\n${'x'.repeat(12005)}\nafter`, `before\n${'y'.repeat(12005)}\nafter`)
assert.equal(budgetRange.before.length, 12000)
assert.equal(budgetRange.after.length, 12000)
assert.equal(budgetRange.truncated, true, 'long changed lines must respect the 12000-character display budget')

const inspectableNodeNames = [
  'diagnose', 'retrieve', 'plan', 'generate', 'review', 'claim_judge',
]
for (const nodeName of inspectableNodeNames) {
  assert.equal(canInspectStep({ node_name: nodeName }), true, `${nodeName} should be inspectable by its persisted node_name`)
  assert.equal(workflowNodeMeta({ node_name: nodeName }).key, nodeName)
}
for (const nodeName of ['evidence_gate', 'claim_extract']) {
  assert.equal(workflowNodeMeta({ node_name: nodeName }).key, nodeName, `${nodeName} should retain its persisted role`)
  assert.equal(canInspectStep({ node_name: nodeName }), false, `${nodeName} should remain a passive status node without a detail action`)
}
for (const nodeName of [
  'prepare_revision', 'prepare_claim_revision', 'finalize_draft', 'claim_decide', 'finalize',
  'finalize_evidence_insufficient', 'unknown_node',
]) {
  assert.equal(canInspectStep({ node_name: nodeName }), false, `${nodeName} should not open workflow details`)
}

const legacyAgentAliases = {
  diagnosis: 'diagnose', retriever: 'retrieve', evidence_gate: 'evidence_gate', planner: 'plan',
  generator: 'generate', reviewer: 'review', claim_extractor: 'claim_extract', claim_judge: 'claim_judge',
}
for (const [agentName, nodeName] of Object.entries(legacyAgentAliases)) {
  assert.equal(workflowNodeMeta({ agent_name: agentName }).key, nodeName, `${agentName} should map only when node_name is absent`)
  assert.equal(canInspectStep({ agent_name: agentName }), inspectableNodeNames.includes(nodeName),
    `${agentName} legacy record should retain only the declared detail capability`)
}
for (const agentName of ['supervisor', 'claim_supervisor', 'other_unknown']) {
  assert.equal(canInspectStep({ agent_name: agentName }), false, `${agentName} must not be promoted to an inspectable node`)
}
for (const agentName of ['diagnose', 'review', 'generate']) {
  assert.equal(canInspectStep({ agent_name: agentName }), false, `${agentName} is not a declared legacy alias when node_name is absent`)
}
assert.equal(canInspectStep({ node_name: 'future_node', agent_name: 'reviewer' }), false,
  'an explicit unknown node_name must not gain review access through agent_name')
assert.equal(workflowNodeMeta({ node_name: 'prepare_revision', agent_name: 'reviewer' }).key, 'prepare_revision',
  'an auxiliary node must keep its persisted identity when agent_name matches a business alias')

assert.equal(formatDuration(45), '45 ms')
assert.equal(formatDuration(1600), '1.6 秒')
assert.equal(formatDuration(60000), '1 分')
assert.equal(formatDuration(Number.NaN), '—')
assert.equal(formatDuration(-1), '—')

const associatedResourceSnapshot = {
  reviews: [
    { run_id: 'run-audit', review_id: 'review-v1', resource_id: 'resource-v1' },
    { run_id: 'run-audit', review_id: 'review-v2', resource_id: 'resource-v2' },
    { run_id: 'other-run', review_id: 'review-other', resource_id: 'resource-other' },
  ],
  resource_versions: [
    { run_id: 'run-audit', resource_id: 'resource-v1', version: 1 },
    { run_id: 'run-audit', resource_id: 'resource-v2', version: 2 },
    { run_id: 'run-audit', resource_id: 'resource-unrelated', version: 1 },
    { run_id: 'other-run', resource_id: 'resource-other', version: 1 },
  ],
}
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { resource_ids: ['resource-v1'] }, 'run-audit'),
  [{ run_id: 'run-audit', resource_id: 'resource-v1', version: 1 }],
  'step details may include only resources explicitly linked by resource_ids in the selected Run',
)
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { review_ids: ['review-v2'] }, 'run-audit'),
  [{ run_id: 'run-audit', resource_id: 'resource-v2', version: 2 }],
  'step details may resolve review_ids to the review resource in the same Run',
)
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { resource_ids: ['resource-v1'], review_ids: ['review-v2'] }, 'run-audit'),
  associatedResourceSnapshot.resource_versions.slice(0, 2),
  'explicit resource and review links should be combined without guessing unrelated resources',
)
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { run_id: 'other-run', resource_ids: ['resource-v1'] }, 'run-audit'),
  [],
  'a step owned by another Run must not inherit selected-Run resource versions',
)
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { resource_ids: ['resource-other'], review_ids: ['review-other'] }, 'run-audit'),
  [],
  'resources and reviews from another Run must not be attached',
)
assert.deepEqual(
  associatedStepResources(associatedResourceSnapshot, { node_name: 'diagnose' }, 'run-audit'),
  [],
  'an unbound key workflow node must not auto-select an unrelated resource',
)

const hydratedWithAuditFields = hydrateWorkflowTimeline({
  run: { run_id: 'run-hydrated', status: 'running', last_event_sequence: 5 },
  steps: [{
    step_id: 'step-audit', step_sequence: 1, node_name: 'claim_judge', status: 'success',
    input_summary: 'claim input', output_summary: 'claim output', decision_reason: 'supported by source',
    evidence_refs: ['evidence-1'], resource_ids: ['resource-a'], review_ids: ['review-2'],
  }],
})
const afterSummarylessSse = reduceWorkflowEvent(hydratedWithAuditFields, {
  event_id: 'summaryless-step-update', sequence: 6, event_type: 'step_succeeded',
  step_id: 'step-audit', step_sequence: 1, node_name: 'claim_judge', status: 'success', payload: {},
})
assert.deepEqual({
  input: afterSummarylessSse.steps[0].input_summary,
  output: afterSummarylessSse.steps[0].output_summary,
  decision: afterSummarylessSse.steps[0].decision_reason,
  evidence: afterSummarylessSse.steps[0].evidence_refs,
  resources: afterSummarylessSse.steps[0].resource_ids,
  reviews: afterSummarylessSse.steps[0].review_ids,
}, {
  input: 'claim input', output: 'claim output', decision: 'supported by source',
  evidence: ['evidence-1'], resources: ['resource-a'], reviews: ['review-2'],
}, 'a summaryless SSE update must preserve hydrated audit fields')

console.log('workflow event reducer/client tests passed')
