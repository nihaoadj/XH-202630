export function extractSupplementalRequirements(source) {
  const constraints = source?.request_payload?.constraints || source?.constraints || {}
  const value = constraints.supplemental_requirements
  return typeof value === 'string' ? value.trim() : ''
}

export function formatSupplementalRequirements(source, fallback = '未填写') {
  const value = extractSupplementalRequirements(source)
  return value || fallback
}

export function formatTaskLabel(task) {
  const prefix = task.job_status === 'running' || task.job_status === 'queued' ? '当前' : '历史'
  const when = task.finished_at || task.created_at || ''
  return `${prefix} / ${task.run_id.slice(0, 8).toUpperCase()} / ${formatDateTime(when)}`
}

export function formatResourceLabel(resource, directionName = '') {
  const parts = [resource.resource_type || '资源', resource.difficulty || '难度未知']
  if (directionName) parts.push(directionName)
  return parts.join(' / ')
}

export function parseServerDate(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = String(value).trim()
  if (!text) return null
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value) {
  if (!value) return '-'
  const date = parseServerDate(value)
  if (!date) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const RESOURCE_EXECUTION_STATE_META = Object.freeze({
  queued: { label: '等待生成', type: 'info', order: 10 },
  generating: { label: '生成中', type: 'warning', order: 20 },
  generated: { label: '已生成', type: 'primary', order: 30 },
  reviewing: { label: '审核中', type: 'warning', order: 40 },
  revision_requested: { label: '返工中', type: 'warning', order: 45 },
  claim_checking: { label: 'Claim 审核中', type: 'warning', order: 50 },
  approved: { label: '已批准', type: 'success', order: 60 },
  human_review: { label: '待人工复核', type: 'warning', order: 70 },
  failed: { label: '失败', type: 'danger', order: 80 },
})

export function resourceExecutionStateMeta(state) {
  return RESOURCE_EXECUTION_STATE_META[state] || {
    label: state || '等待处理',
    type: 'info',
    order: 0,
  }
}

export function resourceRepresentationLabel(representation) {
  if (representation === 'text_html') return '文本 + 互动实践'
  return representation === 'html' ? '互动实践' : '文本'
}

export function resourceExecutionKey(execution) {
  return `${execution?.resource_spec_id || 'unknown'}:${execution?.representation || 'text'}`
}

export function normalizeResourceProgressSummary(summary, executions = []) {
  const counts = summary?.state_counts || summary?.counts || {}
  const count = (name) => Number(counts[name] ?? summary?.[`${name}_count`] ?? 0) || 0
  const reportedTotal = Number(
    summary?.total
      ?? summary?.total_count
      ?? summary?.total_resources
      ?? summary?.total_executions
      ?? executions.length,
  ) || 0
  // A queued snapshot can carry an initial total=0 while its first execution
  // has already arrived over SSE. Prefer the concrete execution list in that
  // transient state so the UI never shows the misleading "0/0" badge.
  const logicalExecutions = new Map()
  for (const execution of executions) {
    const key = execution?.resource_spec_id || `${execution?.resource_type || 'resource'}:${execution?.representation || 'text'}`
    const values = logicalExecutions.get(key) || []
    values.push(execution?.resource_execution_state || 'queued')
    logicalExecutions.set(key, values)
  }
  // A practical guide's canonical text and interactive HTML are one resource
  // for user-facing progress. Prefer that logical count whenever events exist.
  const total = logicalExecutions.size || (reportedTotal > 0 ? reportedTotal : executions.length)
  const approved = count('approved')
  const failed = count('failed')
  const humanReview = count('human_review')
  const completed = logicalExecutions.size
    ? [...logicalExecutions.values()].filter((states) => states.every((state) => (
      ['approved', 'failed', 'human_review'].includes(state)
    ))).length
    : Number(summary?.completed_count ?? summary?.completed ?? approved + failed + humanReview) || 0
  return {
    total,
    approved,
    failed,
    human_review: humanReview,
    completed: Math.min(total || completed, completed),
    state_counts: { ...counts },
    can_finalize: Boolean(summary?.can_finalize),
  }
}
