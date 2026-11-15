import { resourceShelfTypeLabel } from './resourceShelfOrder.js'

const timestamp = value => String(value?.created_at || value?.published_at || '')
const jobFor = (resource, jobs) => jobs.find(job => job.run_id === resource?.run_id)

export function resourceStudyMarker(resource, resources) {
  const peers = resources.filter(item => resourceShelfTypeLabel(item) === resourceShelfTypeLabel(resource))
    .sort((a, b) => timestamp(a).localeCompare(timestamp(b)) || String(a.resource_id).localeCompare(String(b.resource_id)))
  return peers.length > 1 ? ` · ${peers.findIndex(item => item.resource_id === resource.resource_id) + 1}` : ''
}

export function resourceStudyContext(resource, resources, jobs) {
  const job = jobFor(resource, jobs)
  const constraints = job?.request_payload?.constraints || {}
  const correction = constraints.selection_type === 'correction_package' || Boolean(constraints.correction_focus_snapshot)
  const stage = correction
    ? resourceShelfTypeLabel(resource) === '分阶测试题' ? '纠错后复测' : '纠错学习'
    : job?.round_binding ? '初次学习' : '学习材料'
  const peers = resources.filter(item => resourceShelfTypeLabel(item) === resourceShelfTypeLabel(resource))
    .sort((a, b) => timestamp(b).localeCompare(timestamp(a)) || String(b.resource_id).localeCompare(String(a.resource_id)))
  const recency = peers.length > 1 ? peers[0].resource_id === resource.resource_id ? '最新' : '历史' : ''
  return [stage, recency].filter(Boolean).join(' · ')
}

export function resourceFeedbackLocation({ learnerId, batchId, resource, jobs }) {
  if (!learnerId || !batchId) return null
  const binding = jobFor(resource, jobs)?.round_binding
  const query = { learnerId, batchId }
  if (binding?.round_id && binding?.stage_id) {
    Object.assign(query, { runId: resource.run_id, roundId: binding.round_id,
      stageId: binding.stage_id, memberId: binding.member_id })
  }
  return { path: '/feedback', query }
}

export function resolveResourceFeedbackBinding(jobs, batchId, runId = '') {
  const exact = jobs.find(job => job.run_id === runId)
  if (exact?.round_binding) return exact.round_binding
  const candidates = jobs.filter(job => (job.batch_id || job.run_id) === batchId && job.round_binding)
    .sort((a, b) => timestamp(b).localeCompare(timestamp(a)) || String(b.run_id).localeCompare(String(a.run_id)))
  return (candidates.find(job => job.request_payload?.resource_types?.includes('分阶测试题')) || candidates[0])?.round_binding || null
}
