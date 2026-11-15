import assert from 'node:assert/strict'
import { createRenderer, nextTick, ref } from 'vue'
import { buildResourceWorkflow, workflowResourceEvent, workflowResourceIdentity } from '../src/features/generation/resourceWorkflowPresentation.js'
import { hydrateWorkflowTimeline, reduceWorkflowEvent } from '../src/utils/workflowEventReducer.js'
import { associatedStepResources } from '../src/features/generation/generationAudit.js'
import { useGenerationAudit } from '../src/features/generation/useGenerationAudit.js'
import { runApi } from '../src/features/runs/queryApi.js'

const checks = []
function check(name, callback) { return Promise.resolve().then(callback).then(() => checks.push(name)) }
const version = (id, spec, number, extra = {}) => ({ resource_id: id, resource_spec_id: spec, representation: 'text', version: number, run_id: 'run-a', ...extra })
const versions = [version('a1', 'spec-a', 1), version('b1', 'spec-b', 1), version('b2', 'spec-b', 2, { parent_resource_id: 'b1' })]
const step = (id, seq, node, ids = [], extra = {}) => ({ step_id: id, sequence: seq, node_name: node, status: 'success', resource_ids: ids, run_id: 'run-a', ...extra })
const trace = [step('diagnosis', 1, 'diagnose'), step('retrieval', 2, 'retrieve'), step('gate', 3, 'evidence_gate'), step('plan', 4, 'plan'),
  step('gen1', 5, 'generate', ['a1', 'b1']), step('review1', 6, 'review', ['a1', 'b1']),
  step('prepare', 7, 'prepare_revision', ['a1', 'b1']), step('gen2', 8, 'generate', ['b2']), step('review2', 9, 'review', ['b2']),
  step('claim', 10, 'claim_judge', ['a1', 'b2']), step('finish', 11, 'finalize', ['a1', 'b2'])]
let number = 0
const event = (type, stepId, id, spec, payload = {}, extra = {}) => ({ event_id: `event-${++number}`, sequence: number,
  run_id: 'run-a', event_type: type, step_id: stepId, payload: { resource_id: id, resource_spec_id: spec, representation: 'text', ...payload }, ...extra })
const events = [
  event('resource_generated', 'gen1', 'a1', 'spec-a', { resource_execution_state: 'generated' }),
  event('resource_generated', 'gen1', 'b1', 'spec-b', { resource_execution_state: 'generated' }),
  event('review_persisted', 'review1', 'a1', 'spec-a', { resource_execution_state: 'approved' }),
  event('review_persisted', 'review1', 'b1', 'spec-b', { resource_execution_state: 'revision_requested' }),
  event('resource_generated', 'gen2', 'b2', 'spec-b', { resource_execution_state: 'generated' }),
  event('review_persisted', 'review2', 'b2', 'spec-b', { resource_execution_state: 'approved' }),
  event('claim_metric_computed', 'claim', 'a1', 'spec-a', { claim_metric_status: 'complete', factual_claim_total: 3, supported_claim_total: 3 }),
  event('claim_metric_computed', 'claim', 'b2', 'spec-b', { claim_metric_status: 'complete', factual_claim_total: 3, supported_claim_total: 2 }),
  event('resource_published', 'finish', 'a1', 'spec-a', { publication_status: 'published' }),
]
const project = (resource, changes = {}) => buildResourceWorkflow({ runId: 'run-a', trace, events, versions, resource, ...changes })
const a = { resource_spec_id: 'spec-a', representation: 'text', resource_id: 'a1' }
const b = { resource_spec_id: 'spec-b', representation: 'text', resource_id: 'b2' }
const find = (projection, id) => projection.trace.find(item => item.step_id === id)

await check('shared preparation repeats; only the actual revision target carries revision history', () => {
  const pa = project(a), pb = project(b)
  assert.deepEqual(pa.trace.slice(0, 4).map(item => item.step_id), ['diagnosis', 'retrieval', 'gate', 'plan'])
  assert.deepEqual(pb.trace.slice(0, 4).map(item => item.step_id), ['diagnosis', 'retrieval', 'gate', 'plan'])
  assert.equal(find(pa, 'prepare'), undefined, 'prepare references all artifacts but did not revise A')
  assert.equal(find(pa, 'gen2'), undefined)
  assert.equal(find(pa, 'review2'), undefined)
  assert.ok(find(pb, 'prepare'))
  assert.equal(find(pb, 'review1').display_status_label, '需修订')
  assert.equal(find(pb, 'review2').display_status_label, '审核通过')
  assert.equal(find(pb, 'gen2').version_label, 'v2')
  assert.equal(find(pb, 'review1').version_label, 'v1')
  assert.deepEqual(find(pb, 'review1').resource_scope.resourceIds, ['b1'])
})
await check('ordinary review, facts and publication remain independent, exact-step evidence only', () => {
  assert.equal(find(project(a), 'finish').display_status_label, '已发布')
  assert.equal(find(project(b), 'finish').display_status_label, '批次已记录')
  assert.equal(find(project(b), 'claim').display_status_label, '发现事实风险')
  assert.equal(find(project(b), 'review1').display_status_label, '需修订', 'later approval must not rewrite earlier review')
  const withoutEvents = project({ ...b, resource_execution_state: 'approved', publication_status: 'published' }, { events: [] })
  assert.equal(find(withoutEvents, 'review1').display_status_label, '批次已记录')
  assert.equal(find(withoutEvents, 'finish').display_status, 'recorded')
  assert.equal(find(withoutEvents, 'review1').duration_scope, '批次耗时')
  assert.equal(find(withoutEvents, 'diagnosis').duration_scope, '共享耗时')
})
await check('same-type siblings, foreign Runs and conflicting identity never merge', () => {
  const sameTypes = versions.map(item => ({ ...item, resource_type: '讲义' }))
  const result = project({ ...a, resource_type: '讲义' }, { versions: sameTypes })
  assert.equal(find(result, 'gen2'), undefined)
  assert.equal(find(project(a, { trace: [...trace, step('foreign', 12, 'generate', ['a1'], { run_id: 'run-b' })] }), 'foreign'), undefined)
  assert.equal(find(project(a, { events: [event('review_persisted', 'review1', 'a1', 'spec-b', { resource_execution_state: 'approved' })] }), 'review1').display_status, 'recorded')
  assert.deepEqual(project({ ...a, run_id: 'run-b' }).trace, [])
})
await check('queued resources without artifacts and incomplete legacy history remain honest', () => {
  const queued = event('resource_execution_queued', 'gen-live', null, 'spec-b', { attempt: 2 })
  const result = project(b, { trace: [...trace.slice(0, 4), step('gen-live', 5, 'generate', [], { status: 'running' })], events: [queued] })
  assert.equal(find(result, 'gen-live').display_status_label, '已排队')
  const legacy = project(a, { trace: [step('unknown-resource', 5, 'review')], events: [] })
  assert.deepEqual(legacy.trace, []); assert.equal(legacy.omitted, 1)
  assert.equal(project(null).trace.length, 0)
  const placeholder = project({ request_placeholder: true, resource_type: '讲义' })
  assert.equal(placeholder.trace.length, 4, 'a request name must not match artifact names')
  const reuse = project(a, { trace: [step('reuse', 1, 'reuse_context')] })
  assert.equal(reuse.trace[0].node_name, 'reuse_context')
  assert.equal(reuse.trace.length, 1, 'do not invent source diagnostic/retrieval records')
})
await check('event identities support missing version refresh; conflicts reject legacy ancestry', () => {
  const result = project(b, { versions: [] })
  assert.equal(find(result, 'review1').display_status_label, '需修订')
  const conflicted = project(a, { versions: [...versions, version('other', 'spec-z', 2, { parent_resource_id: 'a1' })], trace: [step('bad', 5, 'generate', ['other'])], events: [] })
  assert.equal(conflicted.trace.length, 0)
})
await check('hydration keeps lightweight identities and late resource evidence without accepting another Run', () => {
  const initial = hydrateWorkflowTimeline({ run: { run_id: 'run-a', status: 'completed' }, steps: trace.map(item => ({ ...item, step_sequence: item.sequence })), events,
    resource_versions: versions.map(item => ({ ...item, content_text: 'private body' })), reviews: [{ run_id: 'run-a', review_id: 'review-b1', resource_id: 'b1', suggestion: 'do not retain' }] })
  assert.ok(initial.resourceEvents.length)
  assert.equal(initial.resourceVersions[0].content_text, undefined)
  assert.equal(initial.resourceReviews[0].suggestion, undefined)
  const foreign = event('resource_generated', 'gen1', 'foreign', 'spec-a', { resource_execution_state: 'generated' }, { run_id: 'run-other' })
  assert.equal(reduceWorkflowEvent(initial, foreign), initial)
  const duplicate = reduceWorkflowEvent(initial, events[0])
  assert.equal(duplicate, initial)
  const sparse = event('resource_published', 'finish', 'a1', 'spec-a', { publication_status: 'published' })
  const updated = reduceWorkflowEvent(initial, sparse)
  assert.equal(updated.resourceVersions.find(item => item.resource_id === 'a1').version, 1)
  assert.equal(workflowResourceEvent({ ...sparse, payload: { ...sparse.payload, content_text: 'secret', prompt: 'secret' } }).payload.content_text, undefined)
  assert.equal(workflowResourceIdentity({ ...versions[0], content_text: 'secret' }).content_text, undefined)
})
await check('details preserve the clicked old version and exclude every sibling', () => {
  const projected = find(project(b), 'review1')
  const snapshot = { resource_versions: versions, reviews: [] }
  assert.deepEqual(associatedStepResources(snapshot, projected, 'run-a').map(item => item.resource_id), ['b1'])
  assert.deepEqual(associatedStepResources(snapshot, { ...projected, resource_scope: { ...projected.resource_scope, runId: 'other' } }, 'run-a'), [])
  const partial = find(project(b, { trace: [step('gen1', 5, 'generate', [], { status: 'running' })] }), 'gen1')
  assert.deepEqual(associatedStepResources(snapshot, partial, 'run-a').map(item => item.resource_id), ['b1'], 'worker event can supply the exact artifact before batch completion')
})

const renderer = createRenderer({ createElement: () => ({ children: [] }), createText: text => ({ text }), createComment: () => ({}),
  setText() {}, setElementText() {}, insert(node, parent) { parent.children.push(node); node.parent = parent }, remove() {}, parentNode: node => node.parent, nextSibling: () => null, patchProp() {} })
await check('same-Run resource switch closes and invalidates late detail responses', async () => {
  const calls = [], originals = Object.fromEntries(['timeline', 'claims', 'claimEvidenceRetrieval'].map(key => [key, runApi[key]]))
  for (const key of Object.keys(originals)) runApi[key] = () => new Promise(resolve => calls.push({ key, resolve }))
  let audit
  const app = renderer.createApp({ setup() { audit = useGenerationAudit({ selectedRunId: ref('run-a'), selectedLearnerId: ref('learner') }); return () => null } })
  app.mount({ children: [] })
  const settle = group => { for (const call of group) call.resolve({ data: call.key === 'timeline'
    ? { run: { run_id: 'run-a' }, steps: trace, resource_versions: versions, reviews: [] } : { run_id: 'run-a' } }) }
  try {
    audit.openStep(find(project(a), 'review1'))
    const first = calls.slice()
    audit.close()
    audit.openStep(find(project(b), 'review1'))
    settle(calls.slice(3)); await nextTick(); await new Promise(resolve => setImmediate(resolve))
    assert.equal(audit.resourceId.value, 'b1')
    assert.deepEqual(audit.step.value.resource_scope.resourceIds, ['b1'])
    settle(first); await nextTick(); await new Promise(resolve => setImmediate(resolve))
    assert.equal(audit.resourceId.value, 'b1')
    audit.close(); assert.equal(audit.visible.value, false)
  } finally { app.unmount(); Object.assign(runApi, originals) }
})
console.log(`PASS: ${checks.length} resource workflow checks`)
