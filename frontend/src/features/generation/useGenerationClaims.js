import { resourceApi, runApi } from '../../api/index.js'

/** Load and present Claim results without changing publication or refresh order. */
export function useGenerationClaims({
  selectedRunId,
  selectedLearnerId,
  timelineState,
  resources,
  claimReports,
  selectedClaimReportId,
  claimReportVisible,
  claimDecisionLoading,
  isMounted,
  requestVersion,
  nextRequestVersion,
  refreshStatus,
  messages,
}) {
  async function loadClaimReports(runId = selectedRunId.value) {
    if (!runId) return
    const version = nextRequestVersion()
    const learnerId = selectedLearnerId.value
    const isCurrent = () => isMounted() && version === requestVersion() && learnerId === selectedLearnerId.value && runId === selectedRunId.value
    try {
      const response = await runApi.claims(runId)
      if (!isCurrent()) return
      const payload = response.data || {}
      const judgements = new Map((payload.judgements || []).map((item) => [item.claim_id, item]))
      const next = {}
      for (const [resourceId, metric] of Object.entries(payload.resource_metrics || {})) {
        const factual = Number(metric.factual_claim_total || 0)
        const supported = Number(metric.supported_claim_total || 0)
        next[resourceId] = {
          ...metric,
          claim_factual_pass_rate: factual ? supported / factual : null,
          claim_warning_publish: Boolean(
            timelineState.value.resourceExecutions.find((item) => item.resource_id === resourceId)?.claim_warning_publish
            ?? resources.value.find((item) => item.resource_id === resourceId)?.claim_warning_publish
          ),
          claim_publish_decision_pending: Boolean(
            timelineState.value.resourceExecutions.find((item) => item.resource_id === resourceId)?.claim_publish_decision_pending
            ?? resources.value.find((item) => item.resource_id === resourceId)?.claim_publish_decision_pending
          ),
          issues: (payload.claims || []).filter((claim) => {
            const verdict = judgements.get(claim.claim_id)?.verdict
            return claim.resource_id === resourceId && claim.claim_type === 'factual' && ['not_in_evidence', 'contradicted'].includes(verdict)
          }).map((claim) => ({
            claim_id: claim.claim_id,
            claim_text: claim.claim_text,
            verdict: judgements.get(claim.claim_id)?.verdict,
            reason: judgements.get(claim.claim_id)?.reason,
          })),
        }
      }
      claimReports.value = next
    } catch (error) {
      if (!isCurrent()) return
      if (error?.response?.status !== 404) console.error(error)
    }
  }

  function openClaimReport(resourceId) {
    selectedClaimReportId.value = resourceId
    claimReportVisible.value = true
  }

  function claimPassRateLabel(report) {
    return report.claim_factual_pass_rate == null ? '不适用' : `${(report.claim_factual_pass_rate * 100).toFixed(1)}%`
  }

  function claimIssueCount(report) {
    return Array.isArray(report?.issues) ? report.issues.length : 0
  }

  function claimReportStatusLabel(status) {
    return ({ complete: '审核完成', incomplete: '需要关注', not_applicable: '不适用' }[status] || status || '待审核')
  }

  function claimReportStatusClass(status) {
    return status === 'complete' ? 'is-complete' : 'is-attention'
  }

  function claimRateStyle(report) {
    const rate = Math.max(0, Math.min(1, Number(report?.claim_factual_pass_rate) || 0))
    return { '--claim-rate': `${rate * 100}%` }
  }

  async function decideClaimPublication(publish) {
    const resourceId = selectedClaimReportId.value
    if (!resourceId || claimDecisionLoading.value) return
    claimDecisionLoading.value = true
    try {
      await resourceApi.decideClaimPublication(resourceId, publish)
      messages.success(publish ? '资源已发布。' : '资源已保留为未发布。')
      claimReportVisible.value = false
      await refreshStatus()
      await loadClaimReports(selectedRunId.value)
    } catch (error) {
      messages.error(error?.response?.data?.detail || '发布决定提交失败')
    } finally {
      claimDecisionLoading.value = false
    }
  }

  return {
    loadClaimReports,
    openClaimReport,
    claimPassRateLabel,
    claimIssueCount,
    claimReportStatusLabel,
    claimReportStatusClass,
    claimRateStyle,
    decideClaimPublication
  }
}
