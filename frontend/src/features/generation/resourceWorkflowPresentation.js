import { workflowNodeMeta } from './workflowPresentation.js'

const SHARED_NODES = new Set(['diagnose', 'retrieve', 'evidence_gate', 'plan', 'reuse_context', 'finalize_evidence_insufficient'])
const IDENTITY_FIELDS = ['resource_id', 'resource_spec_id', 'resource_family_id', 'resource_type', 'representation', 'version', 'parent_resource_id', 'review_id', 'run_id']
const EVENT_FIELDS = [...IDENTITY_FIELDS, 'resource_ids', 'review_ids', 'attempt', 'resource_execution_state',
  'publication_status', 'claim_metric_status', 'claim_publish_decision_pending', 'claim_publish_decision',
  'factual_claim_total', 'supported_claim_total', 'contradicted_claim_total', 'not_in_evidence_claim_total']

const inRun = (item, runId) => item && (!item.run_id || !runId || item.run_id === runId)
const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string' && item) : []
const pick = (item, fields) => Object.fromEntries(fields.filter(key => item[key] != null).map(key => [key, item[key]]))

/** Keep identities, not document bodies or private audit payloads, in the live graph. */
export function workflowResourceIdentity(item) {
  return pick(item, IDENTITY_FIELDS)
}

export function workflowResourceEvent(event) {
  const payload = pick(event.payload || {}, EVENT_FIELDS)
  if (!payload.resource_id && !payload.resource_spec_id && !strings(payload.resource_ids).length && !strings(payload.review_ids).length) return null
  return {
    ...pick(event, ['event_id', 'run_id', 'step_id', 'step_sequence', 'node_name', 'event_type', 'status', 'occurred_at']),
    sequence: Number(event.sequence ?? event.event_sequence ?? 0), payload,
  }
}

/** All sets are scoped to the current Run; a matching type is never identity. */
export function buildResourceWorkflow({ trace = [], events = [], versions = [], reviews = [], resource, runId = '' } = {}) {
  if (!resource || !inRun(resource, runId)) return { trace: [], omitted: 0 }
  const representation = resource.representation || 'text'
  const candidates = [...versions, resource].filter(item => inRun(item, runId))
  const byId = new Map()
  for (const item of candidates) if (item.resource_id) byId.set(item.resource_id, { ...byId.get(item.resource_id), ...item })
  const ids = new Set()
  function matches(item) {
    if (!inRun(item, runId) || (item.representation || 'text') !== representation) return false
    if (resource.resource_spec_id && item.resource_spec_id) return item.resource_spec_id === resource.resource_spec_id
    return Boolean(item.resource_id && (item.resource_id === resource.resource_id || ids.has(item.resource_id)))
  }
  for (const item of candidates) if (matches(item)) ids.add(item.resource_id)
  const scopedEvents = events.filter(event => inRun(event, runId))
  // Events can identify an artifact before its resource_versions refresh arrives.
  for (const event of scopedEvents) {
    const payload = event.payload || {}
    if (matches(payload) && payload.resource_id) ids.add(payload.resource_id)
  }
  // Legacy versions are linked only by explicit ancestry, with conflicting spec
  // identities rejecting the edge. Never merge two same-type siblings.
  let changed = true
  while (changed) {
    changed = false
    for (const item of candidates) {
      if ((item.representation || 'text') !== representation) continue
      if (resource.resource_spec_id && item.resource_spec_id && resource.resource_spec_id !== item.resource_spec_id) continue
      if (ids.has(item.parent_resource_id) || (ids.has(item.resource_id) && item.parent_resource_id)) {
        for (const id of [item.resource_id, item.parent_resource_id]) {
          const target = byId.get(id)
          if (id && target && inRun(target, runId)
            && (!resource.resource_spec_id || !target.resource_spec_id || target.resource_spec_id === resource.resource_spec_id)
            && !ids.has(id)) { ids.add(id); changed = true }
        }
      }
    }
  }
  function eventMatches(event) {
    const p = event.payload || {}
    if ((p.representation || 'text') !== representation) return false
    if (resource.resource_spec_id && p.resource_spec_id && p.resource_spec_id !== resource.resource_spec_id) return false
    return Boolean((resource.resource_spec_id && p.resource_spec_id === resource.resource_spec_id)
      || ids.has(p.resource_id) || strings(p.resource_ids).some(id => ids.has(id)))
  }
  const linkedEvents = scopedEvents.filter(eventMatches).sort((a, b) => a.sequence - b.sequence)
  const linkedReviews = reviews.filter(item => inRun(item, runId) && ids.has(item.resource_id))
  const reviewIds = new Set(linkedReviews.map(item => item.review_id))
  const result = []
  let omitted = 0
  const steps = trace.filter(item => inRun(item, runId))
  const sequence = step => Number(step.sequence ?? step.step_sequence ?? 0)
  for (const step of steps) {
    const node = workflowNodeMeta(step).key
    if (SHARED_NODES.has(node)) {
      result.push({ ...step, scope_label: '共享阶段', duration_scope: '共享耗时' })
      continue
    }
    const stepEvents = linkedEvents.filter(event => event.step_id && event.step_id === step.step_id)
    const linkedIds = new Set(strings(step.resource_ids).filter(id => ids.has(id)))
    for (const id of strings(step.review_ids)) {
      if (reviewIds.has(id)) linkedIds.add(linkedReviews.find(item => item.review_id === id).resource_id)
    }
    for (const event of stepEvents) {
      const p = event.payload || {}
      if (p.resource_id && ids.has(p.resource_id)) linkedIds.add(p.resource_id)
      for (const id of strings(p.resource_ids)) if (ids.has(id)) linkedIds.add(id)
    }
    if (['prepare_revision', 'prepare_claim_revision'].includes(node)) {
      // These backend steps reference every batch artifact, including approved
      // siblings. Only the next recorded generation scope proves a target.
      const nextGenerate = steps.filter(item => sequence(item) > sequence(step) && workflowNodeMeta(item).key === 'generate')
        .sort((a, b) => sequence(a) - sequence(b))[0]
      const targeted = nextGenerate && (strings(nextGenerate.resource_ids).some(id => ids.has(id))
        || linkedEvents.some(event => event.step_id === nextGenerate.step_id))
      if (!targeted) continue
    }
    if (!linkedIds.size && !stepEvents.length) {
      // Known sibling-only steps are expected, not a missing-record warning.
      if (!strings(step.resource_ids).length && !strings(step.review_ids).length
        && !scopedEvents.some(event => event.step_id === step.step_id)) omitted += 1
      continue
    }
    const knownVersions = [...linkedIds].map(id => byId.get(id)?.version).filter(value => Number.isInteger(value) && value > 0)
    const projected = {
      ...step,
      scope_label: '资源关联', duration_scope: '批次耗时',
      version_label: [...new Set(knownVersions)].sort((a, b) => a - b).map(value => `v${value}`).join(' / '),
      resource_scope: { runId, specId: resource.resource_spec_id || '', representation, resourceIds: [...linkedIds] },
      // A step's success means its batch invocation completed, not that every
      // artifact passed. Use only same-step, same-resource evidence below.
      display_status: step.status === 'running' ? 'pending' : 'recorded',
      display_status_label: step.status === 'running' ? '批次处理中' : '批次已记录',
      display_action: '本资源结果见执行详情',
    }
    const outcome = resourceStepOutcome(node, stepEvents)
    if (outcome) Object.assign(projected, outcome)
    else if (['failed', 'error', 'timeout'].includes(step.status)) {
      projected.display_status_label = '批次执行异常'
      projected.display_action = '本资源结果未单独记录'
    }
    result.push(projected)
  }
  return { trace: result, omitted }
}

function resourceStepOutcome(node, events) {
  const last = types => [...events].reverse().find(event => types.includes(event.event_type))
  if (node === 'generate') {
    const event = last(['resource_generated', 'resource_version_created', 'resource_human_review_requested', 'resource_execution_failed'])
    if (!event) return last(['resource_execution_queued'])
      ? { display_status: 'queued', display_status_label: '已排队', display_action: '已记录本资源的生成请求' } : null
    const state = event.payload.resource_execution_state
    if (state === 'failed' || event.event_type === 'resource_execution_failed') return { display_status: 'failed', display_status_label: '生成失败', display_action: '本次生成未完成' }
    if (state === 'human_review') return { display_status: 'human_review', display_status_label: '生成降级', display_action: '已保留降级产物，尚待处理' }
    return { display_status: 'success', display_status_label: '已生成', display_action: '本次资源正文已生成' }
  }
  if (node === 'review') {
    const event = last(['review_persisted'])
    if (!event) return null
    const state = event.payload.resource_execution_state || event.status
    return ({
      approved: { display_status: 'success', display_status_label: '审核通过', display_action: '本次普通审核通过' },
      approve: { display_status: 'success', display_status_label: '审核通过', display_action: '本次普通审核通过' },
      revision_requested: { display_status: 'degraded', display_status_label: '需修订', display_action: '本次普通审核要求修订' },
      revise: { display_status: 'degraded', display_status_label: '需修订', display_action: '本次普通审核要求修订' },
      rejected: { display_status: 'failed', display_status_label: '未通过', display_action: '本次普通审核未通过' },
      reject: { display_status: 'failed', display_status_label: '未通过', display_action: '本次普通审核未通过' },
      human_review: { display_status: 'human_review', display_status_label: '待复核', display_action: '本次审核未形成通过结论' },
    })[state] || null
  }
  if (['claim_judge', 'claim_evidence_rejudge'].includes(node)) {
    const event = last(['claim_metric_computed'])
    if (!event) return null
    const p = event.payload
    if (p.claim_metric_status === 'not_applicable') return { display_status: 'skipped', display_status_label: '不适用', display_action: '通用事实核验不适用' }
    if (p.claim_metric_status !== 'complete') return { display_status: 'degraded', display_status_label: '判定未完成', display_action: '不能据此判断事实已通过' }
    const total = p.factual_claim_total, supported = p.supported_claim_total
    if (Number.isInteger(total) && total > 0 && supported === total) return { display_status: 'success', display_status_label: '已审事实获支持', display_action: '本次已审事实均获证据支持' }
    if (Number.isInteger(total) && total > 0 && Number.isInteger(supported) && supported < total) return { display_status: 'degraded', display_status_label: '发现事实风险', display_action: '部分已审事实未获证据支持' }
    if (total === 0) return { display_status: 'recorded', display_status_label: '无待核验事实', display_action: '本次没有纳入核验的事实陈述' }
  }
  // Publication is a separate fact; never turn finalize success into published.
  if (['finalize', 'claim_decide', 'finalize_draft', 'review'].includes(node)) {
    const event = last(['resource_published'])
    if (event) return { display_status: 'success', display_status_label: '已发布', display_action: '关联版本已发布' }
  }
  return null
}
