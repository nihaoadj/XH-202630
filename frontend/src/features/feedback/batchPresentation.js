import { formatDateTime } from '../../utils/generationDisplay.js'

export function buildFeedbackBatchPresentation({ resources, jobsByRunId, nodeNames, batchLabel, finishedAt, status }) {
  const nodeIds = new Set()
  for (const resource of resources) {
    const job = jobsByRunId.get(resource.run_id)
    const request = job?.request_payload
    const targets = [
      request?.constraints?.target_skill_node_ids,
      request?.target_skill_nodes,
      job?.focus_snapshot?.adopted_node_ids,
    ].find(values => Array.isArray(values) && values.length)
      || (resource.learning_path_node ? [resource.learning_path_node] : (resource.knowledge_points || []).filter(id => nodeNames.has(id)))
    targets.filter(id => typeof id === 'string' && id.trim()).forEach(id => nodeIds.add(id))
  }
  const nodeTitle = [...new Set([...nodeIds].map(id => nodeNames.get(id) || id))].join('、')
  const batchMeta = [batchLabel, `${resources.length} 份资源`, formatDateTime(finishedAt)].join(' ｜ ')
  const label = [nodeTitle, batchMeta, status].filter(Boolean).join(' ｜ ')
  return { nodeTitle, batchMeta, status, label }
}
