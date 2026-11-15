/** Pure presentation for the optional Claim evidence retrieval summary. */
const STATUS_LABELS = {
  not_requested: '未开启',
  not_applicable: '不适用',
  pending: '待开始',
  querying: '正在生成检索查询',
  retrieving: '正在补检知识库',
  rejudging: '正在重新核对',
  completed: '补检完成并已生效',
  no_new_evidence: '未找到新增有效证据',
  unavailable: '补检未完成，保留首次判定',
  budget_exhausted: '补检额度用尽，保留首次判定',
  blocked: '补检发现反证或来源冲突',
  interrupted: '补检中断，保留首次判定',
}

const REASON_LABELS = {
  no_new_evidence: '检索到内容与已有证据相同',
  no_query: '没有生成可执行的检索查询',
  evidence_snapshot_missing: '补证快照缺失',
  evidence_context_oversize: '证据范围超出单批上限',
  rejudge_incomplete: '重判批次未全部完成',
  retrieval_failed: '检索未完成',
  budget_exhausted: '预算或截止时间用尽',
  contradicted: '新增证据与陈述相反',
  evidence_conflict: '来源之间存在无法区分的冲突',
}

export function supplementStatusLabel(status) {
  return STATUS_LABELS[status] || status || '未记录'
}

export function supplementReasonLabel(reasonCode) {
  return reasonCode ? REASON_LABELS[reasonCode] || '原因未记录' : ''
}

export function shouldShowSupplement(summary) {
  if (!summary || typeof summary !== 'object') return false
  if (summary.requested === true) return true
  return Array.isArray(summary.sessions) && summary.sessions.length > 0
}

export function supplementSummaryText(summary) {
  if (!shouldShowSupplement(summary)) return ''
  if (summary.requested !== true) {
    return '历史任务未开启证据补检，展示首次判定。'
  }
  const factual = Number(summary.factual_claim_total || 0)
  if (!factual) return '本资源没有可补检的事实陈述。'
  return `首次缺证 ${Number(summary.initial_not_in_evidence_total || 0)} 条 · 补检后缺证 ${Number(summary.effective_not_in_evidence_total || 0)} 条（事实陈述共 ${factual} 条）`
}

/** One row per session, always distinguishing round 0 from the active round. */
export function supplementSessionRows(summary) {
  if (!summary || !Array.isArray(summary.sessions)) return []
  return summary.sessions.map((session, index) => ({
    key: session.session_id || `session-${index}`,
    versionLabel: `资源版本 v${session.resource_version}`,
    status: session.status,
    statusLabel: supplementStatusLabel(session.status),
    reason: supplementReasonLabel(session.reason_code),
    active: session.active === true,
    hardBlock: session.hard_block === true,
    roundLabel: session.active === true ? '补检后（已生效）' : '首次判定（仍生效）',
    targetTotal: Number(session.target_claim_total || 0),
    attemptedTotal: Number(session.attempted_claim_total || 0),
    remainingTotal: Number(session.remaining_claim_total || 0),
    queryTotal: Number(session.query_total || 0),
    evidenceScopeIds: Array.isArray(session.evidence_scope_ids) ? session.evidence_scope_ids : [],
  }))
}
