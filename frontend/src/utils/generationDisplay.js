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
