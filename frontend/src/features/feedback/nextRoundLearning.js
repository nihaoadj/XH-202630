export function isSelectable(node) {
  return !node.blocked_by_node_ids?.length && node.eligibility_status !== 'blocked'
}

export function nextRoundLearning(candidates, action, recommendedIntent) {
  const options = candidates?.generation_options || {}
  const eligible = nodes => (nodes || []).filter(isSelectable)
  const advance = {
    intent: options.recommendation_type === 'advance'
      || (options.recommendation_type === 'current_tier' && recommendedIntent === 'upgrade_learning')
      ? 'upgrade_learning' : 'learn_new_knowledge',
    nodes: eligible(options.learn_new_knowledge),
  }
  const reinforce = { intent: 'reinforce_weakness', nodes: eligible(options.reinforce_weakness) }
  const prerequisites = eligible(options.learning_candidates)
  const remediation = { intent: 'downgrade_learning', nodes: prerequisites }
  const repair = candidates?.remediation_recommendation
  if (repair?.node && isSelectable(repair.node)) {
    const isPrerequisite = ['prerequisite', 'downgrade'].includes(repair.kind)
    return {
      intent: isPrerequisite ? remediation.intent : reinforce.intent,
      nodes: isPrerequisite
        ? [repair.node, ...prerequisites.filter(node => node.skill_node_id !== repair.node.skill_node_id)]
        : [repair.node],
      repairNodeId: repair.node.skill_node_id,
    }
  }
  if (action === 'advance') return advance
  if (action === 'practice') return reinforce
  if (action === 'remediate') return prerequisites.length ? remediation : reinforce
  if (recommendedIntent === remediation.intent) return prerequisites.length ? remediation : reinforce
  if (recommendedIntent === reinforce.intent) return reinforce
  return { intent: advance.intent, nodes: action === 'hold' ? [] : advance.nodes }
}
