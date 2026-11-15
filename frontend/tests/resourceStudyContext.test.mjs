import assert from 'node:assert/strict'
import { resourceFeedbackLocation, resourceStudyContext, resourceStudyMarker, resolveResourceFeedbackBinding } from '../src/utils/resourceStudyContext.js'
import { chooseStudyBatch, orderStudyBatches } from '../src/utils/resourceBatchOrder.js'

const initial = { round_id: 'round', stage_id: 'initial', member_id: 'member' }
const correction = { ...initial, stage_id: 'correction' }
const jobs = [
  { run_id: 'old', batch_id: 'batch', created_at: '2026-11-14T00:00:00Z', round_binding: initial,
    request_payload: { resource_types: ['分阶测试题'] } },
  { run_id: 'new', batch_id: 'batch', created_at: '2026-11-14T01:00:00Z', round_binding: correction,
    request_payload: { resource_types: ['分阶测试题'], constraints: { selection_type: 'correction_package' } } },
]
const resources = [
  { resource_id: 'a', resource_type: '分阶测试题', run_id: 'old', created_at: jobs[0].created_at },
  { resource_id: 'b', resource_type: '分阶测试题', run_id: 'new', created_at: jobs[1].created_at },
]
assert.equal(resourceStudyContext(resources[0], resources, jobs), '初次学习 · 历史')
assert.equal(resourceStudyContext(resources[1], resources, jobs), '纠错后复测 · 最新')
assert.equal(resourceStudyMarker(resources[0], resources), ' · 1')
assert.equal(resourceStudyMarker(resources[1], resources), ' · 2')
assert.equal(resourceStudyMarker(resources[0], [resources[0]]), '')
for (const [index, expected] of [[0, initial], [1, correction]]) {
  assert.deepEqual(resourceFeedbackLocation({ learnerId: 'learner', batchId: 'batch', resource: resources[index], jobs }), {
    path: '/feedback', query: { learnerId: 'learner', batchId: 'batch', runId: resources[index].run_id,
      roundId: 'round', stageId: expected.stage_id, memberId: 'member' },
  })
}
assert.equal(resolveResourceFeedbackBinding(jobs, 'batch'), correction)
assert.equal(resolveResourceFeedbackBinding([...jobs].reverse(), 'batch', 'old'), initial)
assert.equal(resolveResourceFeedbackBinding(jobs, 'other'), null)
assert.deepEqual(resourceFeedbackLocation({ learnerId: 'learner', batchId: 'legacy', resource: {}, jobs }), {
  path: '/feedback', query: { learnerId: 'learner', batchId: 'legacy' },
})
assert.equal(resourceFeedbackLocation({ learnerId: '', batchId: 'batch', jobs }), null)
assert.deepEqual(resources.map(r => r.resource_id), ['a', 'b'])
console.log('resource study context: selected-stage navigation, legacy fallback and recency passed')

const groups = [
  { runId: 'old-batch', resources: [{ resource_id: 'old-resource', run_id: 'old-run', created_at: '2026-11-13T00:00:00Z' }] },
  { runId: 'new-batch', resources: [{ resource_id: 'first', created_at: '2026-11-12T00:00:00Z' },
    { resource_id: 'latest', run_id: 'latest-run', created_at: '2026-11-14T00:00:00Z' }] },
]
const ordered = orderStudyBatches(groups)
assert.deepEqual(ordered.map(group => [group.runId, group.batchNumber]), [['new-batch', 2], ['old-batch', 1]])
assert.equal(ordered[0].latestCreatedAt, '2026-11-14T00:00:00Z')
assert.equal(chooseStudyBatch(ordered), 'new-batch')
assert.equal(chooseStudyBatch(ordered, { resourceId: 'old-resource' }), 'old-batch')
assert.equal(chooseStudyBatch(ordered, { runId: 'old-run' }), 'old-batch')
assert.equal(chooseStudyBatch(ordered, { runId: 'missing' }), 'new-batch')
assert.equal(chooseStudyBatch([]), '')
assert.equal(groups[0].runId, 'old-batch')
console.log('resource batch descending order, latest default, preserved numbers and explicit deep links passed')
