// Read-only projections. Evidence always comes from the selected Run's frozen snapshot.
export const verdictLabels = {
  supported: '获得证据支持', contradicted: '与证据矛盾',
  not_in_evidence: '当前证据未支持', incomplete: '未完成判定', non_factual: '非事实陈述',
}

// Node details are limited to resources explicitly linked to this execution.
export function associatedStepResources(snapshot, step, runId) {
  if (!step || (step.run_id && step.run_id !== runId)) return []
  const ids = new Set(step.resource_ids || [])
  const reviewIds = new Set(step.review_ids || [])
  for (const review of snapshot.reviews || []) {
    if (review.run_id === runId && reviewIds.has(review.review_id)) ids.add(review.resource_id)
  }
  return (snapshot.resource_versions || []).filter(item => item.run_id === runId && ids.has(item.resource_id))
}

export function claimAuditSummary(report, enabled = true) {
  if (!enabled) return '本任务未启用 Claim 审核'
  if (!report || report.metric_status === 'legacy_unavailable') return '历史记录缺少 Claim 审核数据'
  if (report.metric_status === 'not_applicable') return '通用 Claim 审核不适用'
  if (report.metric_status !== 'complete' || Number(report.incomplete_claim_total || 0) > 0) return '事实判定未完成'
  const total = Number(report.factual_claim_total || 0)
  if (!total) return '没有纳入本次审核的事实 Claim'
  if (Number(report.supported_claim_total || 0) === total) return '已审事实均获证据支持'
  return '发现需要关注的事实'
}

export function buildClaimRows(payload, resourceId, runId, evidence = [], resource = null) {
  if (payload.run_id && payload.run_id !== runId) return []
  const snapshots = new Map(evidence.filter(item => item.run_id === runId).map(item => [item.evidence_id, item]))
  const judgements = new Map()
  for (const item of payload.judgements || []) {
    const entries = judgements.get(item.claim_id) || []
    entries.push(item); judgements.set(item.claim_id, entries)
  }
  return (payload.claims || []).filter(claim => claim.resource_id === resourceId
    && (!claim.run_id || claim.run_id === runId)
    && (!resource?.version || !claim.resource_version || claim.resource_version === resource.version)
    && (!resource?.review_id || !claim.review_id || claim.review_id === resource.review_id))
    .map(claim => {
      const hasIdentity = Boolean(claim.run_id && claim.resource_version && claim.review_id)
      const judgement = (judgements.get(claim.claim_id) || []).find(item =>
        (!item.run_id || item.run_id === runId)
        && (!item.resource_id || item.resource_id === resourceId)
        && ['run_id', 'resource_id', 'resource_version', 'review_id'].every(key =>
          hasIdentity ? item[key] === claim[key] : item[key] == null || claim[key] == null || item[key] === claim[key]))
      const completed = judgement && (!judgement.status || judgement.status === 'completed')
      const verdict = completed ? judgement.verdict || 'incomplete' : 'incomplete'
      return {
        ...claim, verdict, reason: judgement?.reason || '没有可关联的完成判定。',
        provenanceUnavailable: !claim.run_id || !claim.resource_version || !claim.review_id,
        evidence: completed ? [...new Set(judgement.evidence_ids || [])].map(id =>
          snapshots.get(id) || { evidence_id: id, missing: true }) : [],
      }
    })
}

export function resourceVersionChain(versions, anchor, runId) {
  if (!anchor || (anchor.run_id && anchor.run_id !== runId)) return []
  const inRun = versions.filter(item => item.run_id === runId)
  let family
  if (anchor.resource_spec_id) {
    family = inRun.filter(item => item.resource_spec_id === anchor.resource_spec_id
      && (item.representation || 'text') === (anchor.representation || 'text'))
  } else {
    const ids = new Set([anchor.resource_id])
    let changed = true
    while (changed) {
      changed = false
      for (const item of inRun) {
        if (ids.has(item.resource_id) && item.parent_resource_id && !ids.has(item.parent_resource_id)) {
          ids.add(item.parent_resource_id); changed = true
        }
        if (item.parent_resource_id && ids.has(item.parent_resource_id) && !ids.has(item.resource_id)) {
          ids.add(item.resource_id); changed = true
        }
      }
    }
    family = inRun.filter(item => ids.has(item.resource_id))
  }
  return family.sort((a, b) => Number(a.version || 0) - Number(b.version || 0)
    || String(a.resource_id).localeCompare(String(b.resource_id)))
}

// Linear common-prefix/suffix range; deliberately not a minimal edit diff.
export function textChangeRange(before, after, limit = 12000) {
  const left = String(before ?? '').split('\n')
  const right = String(after ?? '').split('\n')
  let start = 0
  while (start < left.length && start < right.length && left[start] === right[start]) start++
  let leftEnd = left.length, rightEnd = right.length
  while (leftEnd > start && rightEnd > start && left[leftEnd - 1] === right[rightEnd - 1]) { leftEnd--; rightEnd-- }
  const oldText = left.slice(start, leftEnd).join('\n'), newText = right.slice(start, rightEnd).join('\n')
  return {
    changed: leftEnd > start || rightEnd > start,
    before: oldText.slice(0, limit), after: newText.slice(0, limit),
    beforeRange: leftEnd > start ? `${start + 1}–${leftEnd}` : '无变化行',
    afterRange: rightEnd > start ? `${start + 1}–${rightEnd}` : '无变化行',
    truncated: oldText.length > limit || newText.length > limit,
  }
}

export function reviewStatusLabel(status) {
  return ({ approved: '审核通过', revision_requested: '要求返工', rejected: '审核拒绝',
    human_review: '待复核', pass: '审核通过', revise: '要求返工', reject: '审核拒绝', pending: '待审核', failed: '执行失败', success: '执行成功',
    running: '执行中', completed: '执行完成' })[status] || status || '没有审核记录'
}
