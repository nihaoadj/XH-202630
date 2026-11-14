import assert from 'node:assert/strict'
import { nextRoundLearning } from '../src/features/feedback/nextRoundLearning.js'
import { chosenRouteLabel, confirmedRouteKey, readConfirmedRoute, saveConfirmedRoute, restoreServerChoice } from '../src/features/feedback/confirmedRoute.js'

const values = new Map()
const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
const key = confirmedRouteKey('user', 'learner', 'attempt')
const confirmation = { confirmed: true, route: 'learning', label: chosenRouteLabel('downgrade_learning'),
  payload: { primary_node_id: 'prerequisite', primary_resource_types: ['讲义'] } }
saveConfirmedRoute(storage, key, confirmation)
assert.deepEqual(readConfirmedRoute(storage, key), confirmation)
assert.equal(readConfirmedRoute(storage, confirmedRouteKey('other', 'learner', 'attempt')), null)
assert.equal(readConfirmedRoute(storage, confirmedRouteKey('user', 'learner', 'new-attempt')), null)
assert.equal(chosenRouteLabel('reinforce_weakness'), '强化巩固')
assert.equal(chosenRouteLabel('upgrade_learning'), '下一节点')
assert.equal(readConfirmedRoute({ getItem: () => '{' }, key), null)
const historical = restoreServerChoice({ confirmed: true, route: 'correction', label: '强化巩固',
  payload: { targets: [{ node_id: 'old-node', source_attempt_id: 'old-attempt' }], include_claim_check: false },
  nodes: [{ skill_node_id: 'old-node', name: '原始节点', tier: 1 }], roundId: 'old-round', stageId: 'saved-stage',
}, { correction_targets: [], generation_options: {} }, null)
assert.equal(historical.label, '强化巩固')
assert.deepEqual(historical.candidates.correction_targets, historical.payload.targets)
assert.equal(restoreServerChoice(null, {}, null), null)

const node = id => ({ skill_node_id: id, name: id, tier: 1 })
const candidates = {
  generation_options: {
    recommendation_type: 'current_tier',
    learn_new_knowledge: [node('next'), { ...node('blocked'), blocked_by_node_ids: ['required'] }],
    reinforce_weakness: [node('current')],
    learning_candidates: [node('prerequisite')],
  },
}
assert.deepEqual(nextRoundLearning(candidates, 'advance'), {
  intent: 'learn_new_knowledge', nodes: [node('next')],
})
assert.deepEqual(nextRoundLearning(candidates, 'practice'), {
  intent: 'reinforce_weakness', nodes: [node('current')],
})
assert.deepEqual(nextRoundLearning(candidates, 'remediate'), {
  intent: 'downgrade_learning', nodes: [node('prerequisite')],
})
const withoutPrerequisites = {
  ...candidates, generation_options: { ...candidates.generation_options, learning_candidates: [] },
}
assert.equal(nextRoundLearning(withoutPrerequisites, 'remediate').intent, 'reinforce_weakness')
for (const kind of ['return_to_original', 'practice_prerequisite', 'downgrade', 'prerequisite']) {
  const repair = nextRoundLearning({
    ...candidates, remediation_recommendation: { kind, node: node('repair') },
  }, 'advance')
  assert.equal(repair.repairNodeId, 'repair')
  assert.equal(repair.nodes[0].skill_node_id, 'repair')
  assert.equal(repair.intent, ['downgrade', 'prerequisite'].includes(kind) ? 'downgrade_learning' : 'reinforce_weakness')
}
assert.equal(nextRoundLearning({
  ...candidates, generation_options: { ...candidates.generation_options, recommendation_type: 'advance' },
}, 'advance').intent, 'upgrade_learning')
assert.deepEqual(nextRoundLearning(candidates, 'hold').nodes, [])
assert.equal(nextRoundLearning(candidates, '', 'reinforce_weakness').intent, 'reinforce_weakness')
assert.equal(nextRoundLearning(candidates, 'advance', 'downgrade_learning').intent, 'learn_new_knowledge')
console.log('PASS: next-round candidates follow assessment and remediation')
