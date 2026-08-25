import assert from 'node:assert/strict'
import { buildCoursewareBatchRequest, coursewareEligibleSources } from '../src/features/courseware/sourcePolicy.js'

const resources = [
  { resource_id: 'lecture-a', resource_type: '讲义', batch_id: 'feedback-a' },
  { resource_id: 'guide-a', resource_type: '实操指南', batch_id: 'feedback-a' },
  { resource_id: 'checklist-a', resource_type: '复习清单', batch_id: 'feedback-a' },
  { resource_id: 'lecture-b', resource_type: '讲义', batch_id: 'feedback-b' },
  { resource_id: 'courseware-a', resource_kind: 'interactive_courseware', batch_id: 'feedback-a' },
]

assert.deepEqual(
  coursewareEligibleSources(resources).map((item) => item.resource_id),
  ['guide-a', 'checklist-a'],
)
assert.deepEqual(buildCoursewareBatchRequest({
  learnerId: 'learner-1', resourceIds: ['lecture-a', 'guide-a'], preferences: { interaction_intensity: 'high' },
}), {
  learner_id: 'learner-1', resource_ids: ['lecture-a', 'guide-a'], learning_goal: null,
  expected_duration_minutes: null, interaction_intensity: 'high',
})
console.log('courseware source policy tests passed')
