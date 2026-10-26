import { resourceApi } from '../learning-documents/api.js'
import { runApi } from '../runs/queryApi.js'
import { watch } from 'vue'
import { buildClaimRows, claimAuditSummary } from './generationAudit.js'
import { buildResourceStatusItems } from './resourceStatusPresentation.js'

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
  watch([selectedRunId, selectedLearnerId], () => {
    nextRequestVersion()
    claimReports.value = {}
    claimReportVisible.value = false
    selectedClaimReportId.value = ''
  }, { flush: 'sync' })

  async function loadClaimReports(runId = selectedRunId.value) {
    if (!runId) return
    const version = nextRequestVersion()
    const learnerId = selectedLearnerId.value
    const isCurrent = () => isMounted() && version === requestVersion() && learnerId === selectedLearnerId.value && runId === selectedRunId.value
    try {
      const [claimsResult, timelineResult] = await Promise.allSettled([
        runApi.claims(runId), runApi.timeline(runId, { limit: 1 }),
      ])
      if (!isCurrent()) return
      if (claimsResult.status !== 'fulfilled') throw claimsResult.reason
      const payload = claimsResult.value.data || {}
      if (payload.run_id && payload.run_id !== runId) throw new Error('Claim response Run mismatch')
      const timeline = timelineResult.status === 'fulfilled' ? timelineResult.value.data || {} : {}
      const sourceAvailable = timelineResult.status === 'fulfilled' && (!timeline.run?.run_id || timeline.run.run_id === runId)
      const publications = buildResourceStatusItems(timelineState.value.resourceExecutions, {
        resources: [...resources.value, ...(sourceAvailable ? timeline.resource_versions || [] : [])], runId,
      })
      const next = {}
      for (const [resourceId, metric] of Object.entries(payload.resource_metrics || {})) {
        const factual = Number(metric.factual_claim_total || 0)
        const supported = Number(metric.supported_claim_total || 0)
        const rows = buildClaimRows(payload, resourceId, runId, sourceAvailable ? timeline.evidence : [],
          sourceAvailable ? timeline.resource_versions?.find(item => item.resource_id === resourceId) : null)
        const artifact = sourceAvailable ? timeline.resource_versions?.find(item => item.resource_id === resourceId) : null
        const publication = publications.find(item => item.resource_id === resourceId) || artifact
          || resources.value.find(item => item.resource_id === resourceId)
        next[resourceId] = {
          ...metric,
          claim_factual_pass_rate: metric.metric_status === 'complete' && factual ? supported / factual : null,
          rows,
          sourceError: sourceAvailable ? '' : '冻结来源加载失败，可刷新报告重试。',
          publication_status: publication?.publication_status,
          claim_publish_decision: publication?.claim_publish_decision,
          claim_warning_publish: Boolean(publication?.claim_warning_publish),
          claim_publish_decision_pending: Boolean(publication?.claim_publish_decision_pending),
          issues: rows.filter(row => row.claim_type === 'factual' && ['not_in_evidence', 'contradicted'].includes(row.verdict)),
        }
      }
      claimReports.value = next
    } catch (error) {
      if (!isCurrent()) return
      claimReports.value = {}
      if (error?.response?.status !== 404) console.error(error)
    }
  }

  function openClaimReport(resourceId) {
    selectedClaimReportId.value = resourceId
    claimReportVisible.value = true
    loadClaimReports()
  }

  function claimPassRateLabel(report) {
    if (report.metric_status === 'incomplete') return '未完成'
    return report.claim_factual_pass_rate == null ? '无分母' : `${(report.claim_factual_pass_rate * 100).toFixed(1)}%`
  }

  function claimIssueCount(report) {
    return Array.isArray(report?.issues) ? report.issues.length : 0
  }

  function claimReportStatusLabel(status) {
    return ({ complete: '审核完成', incomplete: '判定未完成', not_applicable: '不适用', legacy_unavailable: '历史数据缺失' }[status] || status || '待审核')
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
    claimAuditSummary,
    openClaimReport,
    claimPassRateLabel,
    claimIssueCount,
    claimReportStatusLabel,
    claimReportStatusClass,
    claimRateStyle,
    decideClaimPublication
  }
}
