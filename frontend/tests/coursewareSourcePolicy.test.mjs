import assert from 'node:assert/strict'
import { sameFeedbackBatchSources } from '../src/features/courseware/sourcePolicy.js'

const resources = [
  { resource_id: 'lecture-a', resource_type: '讲义', batch_id: 'feedback-a' },
  { resource_id: 'guide-a', resource_type: '实操指南', batch_id: 'feedback-a' },
  { resource_id: 'lecture-b', resource_type: '讲义', batch_id: 'feedback-b' },
  { resource_id: 'courseware-a', resource_kind: 'interactive_courseware', batch_id: 'feedback-a' },
]

assert.deepEqual(
  sameFeedbackBatchSources(resources, 'feedback-a').map((item) => item.resource_id),
  ['lecture-a', 'guide-a'],
)
assert.deepEqual(sameFeedbackBatchSources(resources, 'feedback-b').map((item) => item.resource_id), ['lecture-b'])
assert.deepEqual(sameFeedbackBatchSources(resources, ''), [])
console.log('courseware source policy tests passed')
