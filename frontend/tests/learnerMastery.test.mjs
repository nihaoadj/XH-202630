import assert from 'node:assert/strict'
import {
  focusReason,
  masteryPercent,
  relationshipLabels,
  statusLabel,
} from '../src/features/reports/masteryViewModel.js'

assert.equal(statusLabel('self_reported'), '低置信自评')
assert.equal(statusLabel('weak'), '客观薄弱')
assert.equal(masteryPercent({ mastery_score: 0.594 }), '59%')
assert.equal(masteryPercent({ mastery_score: null }), '未测量')
assert.equal(focusReason('OBJECTIVE_SCORE_BELOW_0_60'), '客观测评分低于 60%')
assert.deepEqual(
  relationshipLabels(
    { prerequisites: ['a'], children: ['c'] },
    [{ skill_node_id: 'a', name: '基础' }, { skill_node_id: 'c', name: '进阶' }],
  ),
  { prerequisites: ['基础'], children: ['进阶'] },
)

console.log('learner mastery view-model tests passed')
