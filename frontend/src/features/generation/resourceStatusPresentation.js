import { resourceExecutionStateMeta } from '../../utils/generationDisplay.js'

function logicalState(items) {
  const states = items.map(item => item.resource_execution_state)
  for (const state of ['failed', 'human_review', 'revision_requested', 'claim_checking', 'reviewing', 'generating']) {
    if (states.includes(state)) return state
  }
  if (states.includes('queued')) return states.every(state => state === 'queued') ? 'queued' : 'generating'
  if (states.every(state => state === 'approved')) return 'approved'
  return states.includes('generated') ? 'generated' : states[0] || 'queued'
}

/** Request placeholders are presentation only; they never enter the event ledger. */
export function buildResourceStatusItems(executions = [], {
  requestedTypes = [], jobStatus = '', resources = [], runId = '', claimReports = {},
} = {}) {
  const groups = new Map()
  for (const item of executions) {
    const key = item.resource_spec_id || `${item.resource_type}:${item.representation || 'text'}`
    const group = groups.get(key) || []
    group.push(item)
    groups.set(key, group)
  }
  const publishedSources = new Map(resources
    .filter(resource => resource.resource_id && (!runId || !resource.run_id || resource.run_id === runId))
    .map(resource => [resource.resource_id, resource]))
  const items = [...groups.values()].map(group => {
    const text = group.find(item => item.representation === 'text') || group[0]
    const item = {
      ...text,
      key: text.resource_spec_id || text.key,
      resource_execution_state: logicalState(group),
      validation_status: [...new Set(group.map(row => row.validation_status).filter(Boolean))].join(' / '),
      error_code: group.find(row => row.error_code)?.error_code || text.error_code,
    }
    // Publication decisions update the artifact, independently of execution
    // timestamps. Join by its exact ID, never by resource type or old version.
    const wasPending = item.claim_publish_decision_pending
    const resource = publishedSources.get(item.resource_id)?.publication_status
      ? publishedSources.get(item.resource_id) : claimReports[item.resource_id]
    if (resource && !(item.publication_status === 'published' && resource.publication_status === 'unpublished')) {
      for (const field of ['publication_status', 'claim_publish_decision_pending', 'claim_warning_publish', 'claim_publish_decision', 'review_status']) {
        if (resource[field] != null) item[field] = resource[field]
      }
    }
    if (item.publication_status === 'published') {
      const resolvedDecision = wasPending || item.claim_publish_decision === 'published_by_user'
      item.claim_publish_decision_pending = false
      if (item.resource_execution_state === 'human_review' && resolvedDecision) {
        item.resource_execution_state = 'approved'
      }
    }
    return item
  })
  if (['queued', 'running'].includes(jobStatus)) {
    const recordedTypes = new Set(items.map(item => item.resource_type))
    for (const [index, type] of [...new Set(requestedTypes)].entries()) {
      if (typeof type !== 'string' || !type || recordedTypes.has(type)) continue
      items.push({ key: `request:${index}:${type}`, resource_type: type, representation: 'text',
        resource_execution_state: 'queued', publication_status: 'unpublished',
        display_order: index + 1, request_placeholder: true })
    }
  }
  return items.sort((left, right) => Number(left.display_order || 0) - Number(right.display_order || 0)
    || String(left.resource_type || '').localeCompare(String(right.resource_type || ''), 'zh-CN'))
}

export function resourceStatusMeta(item, { retryEnabled = true, reviewEnabled = true } = {}) {
  const state = item.resource_execution_state
  if (state === 'approved') {
    return item.publication_status === 'published'
      ? { label: '已发布', type: 'success' }
      : { label: '审核通过，等待发布', type: 'warning' }
  }
  if (state === 'human_review' && item.claim_publish_decision_pending) return { label: '待你决定发布', type: 'warning' }
  if (state === 'human_review' && item.claim_publish_decision === 'rejected_by_user') return { label: '已保留，未发布', type: 'warning' }
  if (state === 'generated') return { label: reviewEnabled ? '等待审核' : '草稿已生成', type: 'info' }
  if (state === 'revision_requested') return { label: retryEnabled ? '返工中' : '重新生成中', type: 'warning' }
  return resourceExecutionStateMeta(state)
}

export function validationStatusLabel(status) {
  return ({ pending: '待校验', validating: '校验中', validated: '已通过', passed: '已通过',
    failed: '未通过', skipped: '未执行', not_applicable: '不适用' })[status] || status
}

export function resourceAgentLabel(name) {
  return ({ AssessmentAgent: '测评生成', TextResourceAgent: '讲义生成', PracticeAgent: '实操生成',
    CaseStudyAgent: '案例生成', ChecklistAgent: '清单生成', generator: '资源生成', reviewer: '审核纠偏' })[name] || name
}
