export const confirmedRouteKey = (account, learner, attempt) => `confirmed-feedback-route:${account || ''}:${learner}:${attempt}`
export function readConfirmedRoute(storage, key) {
  try {
    const value = JSON.parse(storage.getItem(key) || 'null')
    return value?.confirmed && value.payload && value.label ? value : null
  } catch { return null }
}
export function saveConfirmedRoute(storage, key, value) {
  try { storage.setItem(key, JSON.stringify(value)) } catch { /* Keep in-memory confirmation. */ }
}
export function chosenRouteLabel(intent) {
  return ({ upgrade_learning: '下一节点', learn_new_knowledge: '下一节点',
    reinforce_weakness: '强化巩固', downgrade_learning: '补救学习', correction: '强化巩固' })[intent] || '下一轮学习'
}

export function restoreServerChoice(server, candidates, cached) {
  if (!server?.confirmed) return null
  const same = cached?.roundId === server.roundId && cached?.stageId === server.stageId
  const choice = { ...server, label: server.label === '下一轮学习' && same ? cached.label : server.label }
  const nodes = server.nodes || []
  const primary = nodes.find(node => node.skill_node_id === server.payload.primary_node_id)
  const intent = same ? cached.payload.primary_learning_intent : 'learn_new_knowledge'
  choice.payload = { ...server.payload, ...(server.route === 'learning' ? { primary_learning_intent: intent } : {}) }
  choice.candidates = { ...candidates,
    correction_targets: server.route === 'correction' ? server.payload.targets : candidates.correction_targets,
    ...(primary ? { remediation_recommendation: same ? cached.candidates?.remediation_recommendation : null,
      generation_options: { ...candidates.generation_options,
        learn_new_knowledge: [primary], reinforce_weakness: [primary], learning_candidates: [primary] },
      eligible_review_nodes: nodes.filter(node => node.skill_node_id !== primary.skill_node_id) } : {}),
  }
  return choice
}
